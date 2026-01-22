"""
Background worker for processing Teams message notifications.
Polls the database for pending notifications and fetches full message details.
"""

import asyncio
import logging
from typing import Optional

from app.storage import (
    get_pending_notifications,
    mark_notification_processing,
    mark_notification_done,
    mark_notification_failed,
    save_message
)
from app.graph_client import GraphClient
from app.schema import normalize_message

logger = logging.getLogger(__name__)

# Global worker state
_worker_task: Optional[asyncio.Task] = None
_worker_running = False
_graph_client: Optional[GraphClient] = None
_oauth_handler = None
_tenant_id = None
_client_id = None
_client_secret = None


async def process_notification(notification_id: int, resource: str, creator_id: Optional[str] = None) -> None:
    """
    Process a single notification by fetching the message and normalizing it.
    
    Args:
        notification_id: Database notification ID
        resource: Resource path to fetch
        creator_id: User ID who created the subscription (for delegated token)
    """
    try:
        logger.info(f"Processing notification {notification_id}")
        
        # Mark as processing
        mark_notification_processing(notification_id)
        
        # Determine which token to use
        graph_client = None
        if creator_id and _oauth_handler:
            # Try to use creator's delegated token
            user_token = _oauth_handler.get_valid_token(creator_id)
            if user_token:
                logger.info(f"Using delegated token for user {creator_id}")
                graph_client = GraphClient(
                    _tenant_id,
                    _client_id,
                    _client_secret,
                    user_token=user_token
                )
            else:
                logger.warning(f"No valid token for user {creator_id}, using app token")
        
        # Fall back to app token if no delegated token available
        if not graph_client:
            graph_client = _graph_client
        
        # Fetch message from Graph
        message_data = graph_client.get_message(resource)
        
        # Normalize message
        normalized = normalize_message(message_data)
        
        # Save to database
        save_message(
            message_id=normalized.message_id,
            normalized_data=normalized.model_dump(mode='json'),
            raw_data=message_data
        )
        
        # Mark notification as done
        mark_notification_done(notification_id)
        
        logger.info(
            f"Successfully processed notification {notification_id}, "
            f"message {normalized.message_id}"
        )
        
    except Exception as e:
        error_msg = f"Failed to process notification {notification_id}: {e}"
        logger.error(error_msg)
        mark_notification_failed(notification_id, str(e))


async def worker_loop() -> None:
    """
    Main worker loop that polls for pending notifications.
    """
    logger.info("Worker loop started")
    
    while _worker_running:
        try:
            # Get pending notifications
            notifications = get_pending_notifications(limit=10)
            
            if notifications:
                logger.info(f"Found {len(notifications)} pending notifications")
                
                # Process each notification
                for notification in notifications:
                    if not _worker_running:
                        break
                    
                    await process_notification(
                        notification.id,
                        notification.resource,
                        notification.creator_id
                    )
                
            else:
                # No notifications, sleep before next poll
                await asyncio.sleep(5)
                
        except Exception as e:
            logger.error(f"Worker loop error: {e}")
            await asyncio.sleep(10)  # Back off on error
    
    logger.info("Worker loop stopped")


async def start_worker(tenant_id: str, client_id: str, client_secret: str, oauth_handler=None) -> None:
    """
    Start the background worker.
    
    Args:
        tenant_id: Azure AD tenant ID
        client_id: Application client ID
        client_secret: Client secret
        oauth_handler: OAuth handler for delegated tokens (optional)
    """
    global _worker_task, _worker_running, _graph_client, _oauth_handler, _tenant_id, _client_id, _client_secret
    
    if _worker_running:
        logger.warning("Worker already running")
        return
    
    logger.info("Starting background worker")
    
    # Store credentials for creating per-user clients
    _tenant_id = tenant_id
    _client_id = client_id
    _client_secret = client_secret
    _oauth_handler = oauth_handler
    
    # Initialize Graph client for app-only access (fallback)
    _graph_client = GraphClient(tenant_id, client_id, client_secret)
    
    # Start worker loop
    _worker_running = True
    _worker_task = asyncio.create_task(worker_loop())
    
    logger.info("Background worker started")


async def stop_worker() -> None:
    """
    Stop the background worker gracefully.
    """
    global _worker_task, _worker_running
    
    if not _worker_running:
        logger.warning("Worker not running")
        return
    
    logger.info("Stopping background worker")
    
    _worker_running = False
    
    if _worker_task:
        # Wait for worker to finish current work
        try:
            await asyncio.wait_for(_worker_task, timeout=30)
        except asyncio.TimeoutError:
            logger.warning("Worker did not stop gracefully, cancelling")
            _worker_task.cancel()
            try:
                await _worker_task
            except asyncio.CancelledError:
                pass
    
    logger.info("Background worker stopped")


def is_worker_running() -> bool:
    """
    Check if worker is running.
    
    Returns:
        True if running, False otherwise
    """
    return _worker_running
