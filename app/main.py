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
from fastapi.responses import PlainTextResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from pydantic import ValidationError
from pydantic_settings import BaseSettings
from dotenv import load_dotenv

from app.storage import init_db, get_message_by_id, get_db, Message, save_notification, save_message
from app.auth import OAuthHandler
from app.utils import setup_logging, validate_client_state
from app.worker import start_worker, stop_worker
from app.graph_client import GraphClient
from app.schema import NotificationCollection, SubscriptionCreateRequest
from app.schema import normalize_message
from app.subscription import (
    create_teams_subscription,
    list_subscriptions,
    delete_subscription as delete_subscription_fn,
)
import hmac
import hashlib
from app.schema import NotificationCollection

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
    disable_oauth_state_validation: bool = False
    db_path: str = "sqlite:///./teams_mvp.db"
    log_level: str = "INFO"
    oauth_redirect_uri: str = "https://teamspoc.onrender.com/auth/callback"
    
    class Config:
        env_file = ".env"
        case_sensitive = False


# Global settings instance
settings: Optional[Settings] = None
oauth_handler: Optional[OAuthHandler] = None
# State tokens for CSRF protection
oauth_states: set = set()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Lifespan context manager for FastAPI startup and shutdown.
    """
    # Startup
    global settings, oauth_handler
    settings = Settings()
    
    # Initialize OAuth handler
    oauth_handler = OAuthHandler(
        tenant_id=settings.tenant_id,
        client_id=settings.client_id,
        client_secret=settings.client_secret,
        redirect_uri=settings.oauth_redirect_uri
    )
    
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
    title="Teams Message OAuth Client",
    description="OAuth 2.0 app to fetch Teams messages. Users sign in and grant permission - no admin consent needed.",
    version="1.0.0",
    lifespan=lifespan
)
# Mount frontend UI
app.mount("/ui", StaticFiles(directory="app/static", html=True), name="ui")

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
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
        "service": "Teams Message OAuth Client"
    }


# ============= Webhook Endpoint =============

@app.post("/graph-webhook")
async def graph_webhook(request: Request):
    """
    Receive Microsoft Graph change notifications.
    Handles both validation and actual notifications.
    """
    # Handle validation request (GET with validationToken)
    validation_token = request.query_params.get("validationToken")
    if validation_token:
        logger.info(f"Webhook validation request received")
        return PlainTextResponse(content=validation_token, status_code=200)
    
    # Handle notification POST
    try:
        body = await request.json()
        logger.info(f"Webhook notification received")
        
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
        for notification in notification_collection.value:
            # Validate client state
            if not validate_client_state(
                notification.client_state,
                settings.client_state_secret
            ):
                logger.warning(f"Invalid client state in notification")
                continue
            
            # Save notification to database for processing
            notification_id = save_notification(
                subscription_id=notification.subscription_id,
                resource=notification.resource,
                payload=notification.model_dump()
            )
            
            logger.info(
                f"Saved notification {notification_id} for "
                f"subscription {notification.subscription_id}"
            )
        
        return {"status": "accepted"}
        
    except JSONDecodeError:
        logger.error("Invalid JSON in webhook request")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid JSON"
        )
    except Exception as e:
        logger.error(f"Webhook processing error: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Webhook processing failed"
        )


# ============= OAuth & User Data Endpoints =============

@app.get("/auth/login")
async def auth_login():
    """
    Initiate OAuth login flow.
    Redirects user to Microsoft login page.
    
    Usage: Visit https://teamspoc.onrender.com/auth/login in browser
    """
    auth_url, state = oauth_handler.get_authorization_url()
    # Set signed state cookie to avoid losing in-memory state across instances
    response = RedirectResponse(url=auth_url)
    sig = hmac.new(
        settings.client_state_secret.encode("utf-8"),
        state.encode("utf-8"),
        hashlib.sha256
    ).hexdigest()
    response.set_cookie(
        key="oauth_state",
        value=state,
        max_age=600,
        secure=True,
        httponly=True,
        samesite="lax"
    )
    response.set_cookie(
        key="oauth_state_sig",
        value=sig,
        max_age=600,
        secure=True,
        httponly=True,
        samesite="lax"
    )
    logger.info(f"OAuth login initiated")
    return response


@app.get("/auth/callback")
async def auth_callback(request: Request, code: Optional[str] = None, state: Optional[str] = None, error: Optional[str] = None):
    """
    OAuth callback endpoint (automatic redirect from Microsoft).
    Exchanges authorization code for access token.
    Returns user info on success.
    """
    try:
        if error:
            logger.error(f"OAuth error: {error}")
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"OAuth error: {error}"
            )
        
        if not code or not state:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Missing code or state parameter"
            )
        
        # Verify state using signed cookies (resilient across restarts/load balancing)
        if not settings.disable_oauth_state_validation:
            stored_state = request.cookies.get("oauth_state")
            stored_sig = request.cookies.get("oauth_state_sig")
            if not stored_state or stored_state != state:
                logger.warning(f"Invalid state token: {state}")
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Invalid state token"
                )
            expected_sig = hmac.new(
                settings.client_state_secret.encode("utf-8"),
                stored_state.encode("utf-8"),
                hashlib.sha256
            ).hexdigest()
            if stored_sig != expected_sig:
                logger.warning("Invalid state signature")
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Invalid state token"
                )
        else:
            logger.warning("OAuth state validation disabled via configuration. Enable for production.")
        
        # Exchange code for token
        session = oauth_handler.exchange_code_for_token(code)
        
        if not session:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Failed to exchange code for token"
            )
        
        logger.info(f"User authenticated: {session.user_email}")
        
        # Redirect to UI with user_id for convenience
        resp = RedirectResponse(url=f"/ui?user_id={session.user_id}")
        # Also set cookie with user_id
        resp.set_cookie(
            key="user_id",
            value=session.user_id,
            max_age=3600,
            secure=True,
            httponly=False,
            samesite="lax"
        )
        return resp
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"OAuth callback error: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Authentication failed"
        )


@app.post("/auth/logout")
async def auth_logout(user_id: str):
    """
    Logout user by removing their session.
    
    Parameters:
    - user_id: The user's Microsoft ID (from login callback)
    """
    try:
        oauth_handler.logout(user_id)
        return {"status": "logged_out", "user_id": user_id}
    except Exception as e:
        logger.error(f"Logout error: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Logout failed"
        )


# ============= User Messages Endpoint (OAuth) =============

@app.get("/api/user/messages")
async def get_user_messages(user_id: str, team_id: Optional[str] = None, channel_id: Optional[str] = None, limit: int = 50):
    """
    Get messages from user's Teams and channels.
    
    Parameters:
    - user_id: The user's Microsoft ID (from login callback) [REQUIRED]
    - team_id: Specific team ID (optional)
    - channel_id: Specific channel ID in the team (optional)
    - limit: Max messages to return (default 50, max 500)
    
    Examples:
    - Get all chats: /api/user/messages?user_id=USER_ID
    - Get channel messages: /api/user/messages?user_id=USER_ID&team_id=TEAM_ID&channel_id=CHANNEL_ID&limit=10
    """
    try:
        if limit > 500:
            limit = 500
        
        session = oauth_handler.get_session(user_id)
        if not session:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="User not authenticated. Call /auth/login first."
            )
        
        token = oauth_handler.get_valid_token(user_id)
        if not token:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Token expired or unavailable. Please login again."
            )
        
        client = GraphClient(
            settings.tenant_id,
            settings.client_id,
            settings.client_secret,
            user_token=token
        )
        
        # Build Graph API endpoint
        if team_id and channel_id:
            # Specific channel messages
            endpoint = f"/teams/{team_id}/channels/{channel_id}/messages?$top={limit}"
            logger.info(f"Fetching channel messages for user {user_id}: team={team_id}, channel={channel_id}")
            response = client._make_request("GET", endpoint)
            messages = response.json().get("value", [])
        else:
            # Get all user's chats first, then fetch messages from each
            logger.info(f"Fetching chats for user {user_id}")
            chats_response = client._make_request("GET", "/me/chats?$top=50")
            chats = chats_response.json().get("value", [])
            
            # Fetch messages from each chat
            messages = []
            for chat in chats[:min(10, len(chats))]:  # Limit to first 10 chats to avoid timeout
                chat_id = chat.get("id")
                if chat_id:
                    try:
                        msg_response = client._make_request("GET", f"/me/chats/{chat_id}/messages?$top=5")
                        chat_messages = msg_response.json().get("value", [])
                        messages.extend(chat_messages)
                        if len(messages) >= limit:
                            break
                    except Exception as e:
                        logger.warning(f"Failed to fetch messages from chat {chat_id}: {e}")
                        continue
            
            messages = messages[:limit]
        
        logger.info(f"Retrieved {len(messages)} messages for user: {user_id}")
        
        return {
            "count": len(messages),
            "messages": messages
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to retrieve messages: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to retrieve messages: {str(e)}"
        )


# ============= Ingest User Messages (store to DB) =============

@app.post("/api/user/messages/ingest")
async def ingest_user_messages(user_id: str, team_id: Optional[str] = None, channel_id: Optional[str] = None, limit: int = 50):
    """
    Fetch user's messages (delegated) and store normalized messages in the DB.
    Uses same logic as /api/user/messages but persists via save_message.
    """
    try:
        if limit > 500:
            limit = 500

        session_obj = oauth_handler.get_session(user_id)
        if not session_obj:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="User not authenticated. Call /auth/login first."
            )

        token = oauth_handler.get_valid_token(user_id)
        if not token:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Token expired or unavailable. Please login again."
            )

        client = GraphClient(
            settings.tenant_id,
            settings.client_id,
            settings.client_secret,
            user_token=token
        )

        fetched = []
        if team_id and channel_id:
            endpoint = f"/teams/{team_id}/channels/{channel_id}/messages?$top={limit}"
            logger.info(f"Ingesting channel messages for user {user_id}: team={team_id}, channel={channel_id}")
            response = client._make_request("GET", endpoint)
            fetched = response.json().get("value", [])
        else:
            logger.info(f"Ingesting chats for user {user_id}")
            chats_response = client._make_request("GET", "/me/chats?$top=50")
            chats = chats_response.json().get("value", [])
            messages = []
            for chat in chats[:min(10, len(chats))]:
                chat_id = chat.get("id")
                if chat_id:
                    try:
                        msg_response = client._make_request("GET", f"/me/chats/{chat_id}/messages?$top=5")
                        chat_messages = msg_response.json().get("value", [])
                        messages.extend(chat_messages)
                        if len(messages) >= limit:
                            break
                    except Exception as e:
                        logger.warning(f"Failed to fetch messages from chat {chat_id}: {e}")
                        continue
            fetched = messages[:limit]

        # Normalize and store
        stored = 0
        for msg in fetched:
            try:
                normalized = normalize_message(msg)
                save_message(
                    message_id=normalized.message_id,
                    normalized_data=normalized.model_dump(mode='json'),
                    raw_data=msg
                )
                stored += 1
            except Exception as e:
                logger.warning(f"Failed to normalize/store message: {e}")

        logger.info(f"Stored {stored} messages for user {user_id}")
        return {"stored": stored}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to ingest messages: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to ingest messages: {str(e)}"
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


# ============= Subscription Management Endpoints =============

@app.post("/subscriptions")
async def create_subscription_api(req: SubscriptionCreateRequest):
    try:
        notification_url = f"{settings.ngrok_url.rstrip('/')}/graph-webhook"
        sub = create_teams_subscription(
            tenant_id=settings.tenant_id,
            client_id=settings.client_id,
            client_secret=settings.client_secret,
            resource=req.resource,
            notification_url=notification_url,
            client_state=settings.client_state_secret,
            expiration_hours=req.expiration_hours,
        )
        return sub
    except Exception as e:
        logger.error(f"Create subscription failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/subscriptions")
async def list_subscriptions_api():
    try:
        subs = list_subscriptions(
            tenant_id=settings.tenant_id,
            client_id=settings.client_id,
            client_secret=settings.client_secret,
        )
        return {"subscriptions": subs, "count": len(subs)}
    except Exception as e:
        logger.error(f"List subscriptions failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.delete("/subscriptions/{subscription_id}")
async def delete_subscription_api(subscription_id: str):
    try:
        delete_subscription_fn(
            tenant_id=settings.tenant_id,
            client_id=settings.client_id,
            client_secret=settings.client_secret,
            subscription_id=subscription_id,
        )
        return {"message": "Subscription deleted successfully"}
    except Exception as e:
        logger.error(f"Delete subscription failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))
