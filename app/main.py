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
from fastapi.middleware.cors import CORSMiddleware
from pydantic import ValidationError
from pydantic_settings import BaseSettings
from dotenv import load_dotenv

from app.storage import init_db, get_message_by_id, get_db, Message
from app.auth import OAuthHandler
from app.utils import setup_logging
from app.worker import start_worker, stop_worker
from app.graph_client import GraphClient

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


# ============= OAuth & User Data Endpoints =============

@app.get("/auth/login")
async def auth_login():
    """
    Initiate OAuth login flow.
    Redirects user to Microsoft login page.
    
    Usage: Visit https://teamspoc.onrender.com/auth/login in browser
    """
    auth_url, state = oauth_handler.get_authorization_url()
    oauth_states.add(state)
    logger.info(f"OAuth login initiated")
    return RedirectResponse(url=auth_url)


@app.get("/auth/callback")
async def auth_callback(code: Optional[str] = None, state: Optional[str] = None, error: Optional[str] = None):
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
        
        # Verify state (CSRF protection)
        if state not in oauth_states:
            logger.warning(f"Invalid state token: {state}")
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid state token"
            )
        oauth_states.discard(state)
        
        # Exchange code for token
        session = oauth_handler.exchange_code_for_token(code)
        
        if not session:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Failed to exchange code for token"
            )
        
        logger.info(f"User authenticated: {session.user_email}")
        
        # Return success response with user info
        return {
            "status": "success",
            "message": "Successfully authenticated",
            "user": {
                "id": session.user_id,
                "email": session.user_email
            }
        }
        
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
        else:
            # All user's chat messages
            endpoint = f"/me/chats/getAllMessages?$top={limit}"
            logger.info(f"Fetching all chat messages for user {user_id}")
        
        response = client._make_request("GET", endpoint)
        messages = response.json().get("value", [])
        
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
