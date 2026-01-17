"""
FastAPI application for receiving Microsoft Graph webhook notifications.
"""

import os
import json
import logging
from json import JSONDecodeError
from contextlib import asynccontextmanager
from typing import Optional

from fastapi import FastAPI, Request, Response, HTTPException, status
from fastapi.responses import PlainTextResponse
from pydantic import ValidationError
from pydantic_settings import BaseSettings
from dotenv import load_dotenv

from app.storage import init_db, save_notification, get_message_by_id, get_db
from app.schema import (
    NotificationCollection, 
    GraphNotification,
    SubscriptionCreateRequest,
    SubscriptionResponse,
    SubscriptionListResponse
)
from app.utils import setup_logging, validate_client_state, extract_resource_path
from app.worker import start_worker, stop_worker
from app.subscription import (
    create_teams_subscription,
    list_subscriptions as get_subscriptions_list,
    delete_subscription as remove_subscription
)

# Load environment variables
load_dotenv()

logger = logging.getLogger(__name__)


class Settings(BaseSettings):
    """Application settings from environment variables."""
    
    tenant_id: str
    client_id: str
    client_secret: str
    ngrok_url: str
    client_state_secret: str
    db_path: str = "sqlite:///./teams_mvp.db"
    log_level: str = "INFO"
    
    class Config:
        env_file = ".env"
        case_sensitive = False


# Global settings instance
settings: Optional[Settings] = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Lifespan context manager for FastAPI startup and shutdown.
    """
    # Startup
    global settings
    settings = Settings()
    
    setup_logging(settings.log_level)
    logger.info("Starting Teams Message Webhook MVP")
    
    # Initialize database
    init_db(settings.db_path)
    logger.info("Database initialized")
    
    # Start background worker
    await start_worker(
        settings.tenant_id,
        settings.client_id,
        settings.client_secret
    )
    logger.info("Background worker started")
    
    yield
    
    # Shutdown
    logger.info("Shutting down application")
    await stop_worker()


# Create FastAPI app
app = FastAPI(
    title="Teams Message Webhook MVP",
    description="Receive and process Microsoft Graph change notifications for Teams messages",
    version="0.1.0",
    lifespan=lifespan
)


@app.get("/")
async def root():
    """Health check endpoint."""
    return {
        "status": "running",
        "service": "Teams Message Webhook MVP"
    }


@app.get("/health")
async def health():
    """Detailed health check."""
    return {
        "status": "healthy",
        "database": "connected",
        "worker": "running"
    }


@app.post("/graph-webhook")
async def graph_webhook(request: Request):
    """
    Webhook endpoint for Microsoft Graph change notifications.
    
    Handles:
    1. Validation requests (returns validationToken)
    2. Change notifications (validates clientState and queues for processing)
    """
    try:
        # Get query parameters for validation
        validation_token = request.query_params.get("validationToken")
        
        # If validation token is present, respond with it (subscription validation)
        if validation_token:
            logger.info("Received subscription validation request")
            return PlainTextResponse(
                content=validation_token,
                status_code=status.HTTP_200_OK
            )
        
        # Parse notification body safely (handle empty or non-JSON bodies)
        raw_body = await request.body()
        if not raw_body:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Request body is empty"
            )
        try:
            body = json.loads(raw_body)
        except JSONDecodeError:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Request body must be valid JSON"
            )
        logger.debug(f"Received webhook payload: {body}")
        
        # Parse notifications
        try:
            notification_collection = NotificationCollection(**body)
        except ValidationError as e:
            logger.error(f"Invalid notification format: {e}")
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid notification format"
            )
        
        # Process each notification
        notifications_processed = 0
        
        for notification in notification_collection.value:
            # Validate clientState
            if not validate_client_state(
                notification.client_state,
                settings.client_state_secret
            ):
                logger.warning(
                    f"Invalid clientState for subscription {notification.subscription_id}"
                )
                continue
            
            try:
                # Extract resource path
                resource = extract_resource_path(notification.model_dump(by_alias=True))
                
                # Save notification to database for processing
                notification_id = save_notification(
                    subscription_id=notification.subscription_id,
                    resource=resource,
                    payload=notification.model_dump(by_alias=True)
                )
                
                logger.info(
                    f"Queued notification {notification_id} for "
                    f"subscription {notification.subscription_id}"
                )
                notifications_processed += 1
                
            except Exception as e:
                logger.error(f"Failed to process notification: {e}")
                continue
        
        logger.info(f"Processed {notifications_processed} notifications")
        
        # Return 202 Accepted
        return Response(status_code=status.HTTP_202_ACCEPTED)
        
    except Exception as e:
        logger.error(f"Webhook error: {e}")
        # Return 500 to trigger Graph retry
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Internal server error"
        )


@app.post("/test-notification")
async def test_notification(notification: dict):
    """
    Test endpoint to manually submit a notification payload.
    Useful for local testing without Graph.
    """
    try:
        # Parse and validate
        notification_data = GraphNotification(**notification)
        
        # Extract resource
        resource = extract_resource_path(notification)
        
        # Save to database
        notification_id = save_notification(
            subscription_id=notification_data.subscription_id,
            resource=resource,
            payload=notification
        )
        
        logger.info(f"Test notification saved with ID {notification_id}")
        
        return {
            "status": "accepted",
            "notification_id": notification_id
        }
        
    except Exception as e:
        logger.error(f"Test notification error: {e}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )


@app.post("/subscriptions", response_model=SubscriptionResponse, status_code=status.HTTP_201_CREATED)
async def create_subscription(request: SubscriptionCreateRequest):
    """
    Create a new Microsoft Graph subscription.
    
    This endpoint creates a subscription to monitor changes in Teams messages.
    The webhook will receive notifications when messages are created or updated.
    """
    try:
        # Construct notification URL
        notification_url = f"{settings.ngrok_url}/graph-webhook"
        
        logger.info(f"Creating subscription for resource: {request.resource}")
        
        # Create subscription using global settings
        subscription_data = create_teams_subscription(
            tenant_id=settings.tenant_id,
            client_id=settings.client_id,
            client_secret=settings.client_secret,
            resource=request.resource,
            notification_url=notification_url,
            client_state=settings.client_state_secret,
            expiration_hours=request.expiration_hours
        )
        
        logger.info(f"Subscription created with ID: {subscription_data['id']}")
        
        return SubscriptionResponse(**subscription_data)
        
    except Exception as e:
        logger.error(f"Failed to create subscription: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to create subscription: {str(e)}"
        )


@app.get("/subscriptions", response_model=SubscriptionListResponse)
async def list_subscriptions():
    """
    List all active Microsoft Graph subscriptions.
    
    Returns all subscriptions created for this application.
    """
    try:
        logger.info("Fetching all subscriptions")
        
        # List subscriptions using global settings
        subscriptions_data = get_subscriptions_list(
            tenant_id=settings.tenant_id,
            client_id=settings.client_id,
            client_secret=settings.client_secret
        )
        
        subscriptions = [
            SubscriptionResponse(**sub) for sub in subscriptions_data
        ]
        
        logger.info(f"Found {len(subscriptions)} active subscriptions")
        
        return SubscriptionListResponse(
            subscriptions=subscriptions,
            count=len(subscriptions)
        )
        
    except Exception as e:
        logger.error(f"Failed to list subscriptions: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to list subscriptions: {str(e)}"
        )


@app.delete("/subscriptions/{subscription_id}")
async def delete_subscription(subscription_id: str):
    """
    Delete a Microsoft Graph subscription.
    
    Removes the subscription so no further notifications will be received.
    """
    try:
        logger.info(f"Deleting subscription: {subscription_id}")
        
        # Delete subscription using global settings
        remove_subscription(
            tenant_id=settings.tenant_id,
            client_id=settings.client_id,
            client_secret=settings.client_secret,
            subscription_id=subscription_id
        )
        
        logger.info(f"Subscription {subscription_id} deleted successfully")
        
        return {
            "status": "deleted",
            "subscription_id": subscription_id
        }
        
    except Exception as e:
        logger.error(f"Failed to delete subscription: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to delete subscription: {str(e)}"
        )


@app.get("/messages")
async def get_all_messages(limit: int = 50):
    """
    Retrieve all messages stored in the database.
    
    Returns the most recently ingested messages.
    
    Query Parameters:
    - limit: Maximum number of messages to return (default: 50, max: 500)
    """
    try:
        if limit > 500:
            limit = 500
        
        db = get_db()
        with db.get_session() as session:
            messages = session.query(Message).order_by(
                Message.ingested_at.desc()
            ).limit(limit).all()
            
            result = []
            for msg in messages:
                result.append({
                    "id": msg.id,
                    "message_id": msg.message_id,
                    "normalized_json": json.loads(msg.normalized_json),
                    "raw_json": json.loads(msg.raw_json),
                    "ingested_at": msg.ingested_at.isoformat() if msg.ingested_at else None
                })
            
            logger.info(f"Retrieved {len(result)} messages")
            return {
                "count": len(result),
                "messages": result
            }
    
    except Exception as e:
        logger.error(f"Failed to retrieve messages: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to retrieve messages: {str(e)}"
        )


@app.get("/messages/{message_id}")
async def get_message(message_id: str):
    """
    Retrieve a specific message by Teams message ID.
    
    Path Parameters:
    - message_id: The Teams message ID
    """
    try:
        message = get_message_by_id(message_id)
        
        if not message:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Message {message_id} not found"
            )
        
        return {
            "id": message.id,
            "message_id": message.message_id,
            "normalized_json": json.loads(message.normalized_json),
            "raw_json": json.loads(message.raw_json),
            "ingested_at": message.ingested_at.isoformat() if message.ingested_at else None
        }
    
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to retrieve message: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to retrieve message: {str(e)}"
        )


if __name__ == "__main__":
    import uvicorn
    
    uvicorn.run(
        "app.main:app",
        host="0.0.0.0",
        port=8000,
        reload=True,
        log_level="info"
    )
