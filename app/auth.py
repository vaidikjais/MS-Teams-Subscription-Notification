"""
OAuth 2.0 authentication handler for delegated user access.
Handles Microsoft login, token management, and user session.
"""

import logging
import json
import secrets
from datetime import datetime, timedelta
from typing import Optional, Dict, Any
from urllib.parse import urlencode, parse_qs, urlparse
import requests

logger = logging.getLogger(__name__)


class OAuthSession:
    """Stores user OAuth tokens and metadata."""
    
    def __init__(self, access_token: str, refresh_token: str, expires_at: datetime, user_id: str, user_email: str):
        self.access_token = access_token
        self.refresh_token = refresh_token
        self.expires_at = expires_at
        self.user_id = user_id
        self.user_email = user_email
        self.created_at = datetime.utcnow()
    
    def is_expired(self) -> bool:
        """Check if token is expired."""
        return datetime.utcnow() >= self.expires_at - timedelta(minutes=5)
    
    def to_dict(self) -> Dict[str, Any]:
        """Serialize session to dict for storage."""
        return {
            "access_token": self.access_token,
            "refresh_token": self.refresh_token,
            "expires_at": self.expires_at.isoformat(),
            "user_id": self.user_id,
            "user_email": self.user_email,
            "created_at": self.created_at.isoformat()
        }
    
    @staticmethod
    def from_dict(data: Dict[str, Any]) -> "OAuthSession":
        """Deserialize session from dict."""
        return OAuthSession(
            access_token=data["access_token"],
            refresh_token=data["refresh_token"],
            expires_at=datetime.fromisoformat(data["expires_at"]),
            user_id=data["user_id"],
            user_email=data["user_email"]
        )


class OAuthHandler:
    """Handles OAuth 2.0 flow for Microsoft Graph."""
    
    OAUTH_AUTHORIZE_URL = "https://login.microsoftonline.com/{tenant_id}/oauth2/v2.0/authorize"
    OAUTH_TOKEN_URL = "https://login.microsoftonline.com/{tenant_id}/oauth2/v2.0/token"
    GRAPH_ME_URL = "https://graph.microsoft.com/v1.0/me"
    
    # Scopes required for delegated access
    SCOPES = [
        "Chat.Read",
        "ChannelMessage.Read",  # For Teams channel subscriptions
        "User.Read",
        "offline_access"  # For refresh token
    ]
    
    def __init__(self, tenant_id: str, client_id: str, client_secret: str, redirect_uri: str):
        self.tenant_id = tenant_id
        self.client_id = client_id
        self.client_secret = client_secret
        self.redirect_uri = redirect_uri
        # In-memory session store (in production, use database)
        self.sessions: Dict[str, OAuthSession] = {}
        logger.info("OAuth handler initialized")
    
    def get_authorization_url(self, state: Optional[str] = None) -> tuple[str, str]:
        """
        Generate Microsoft OAuth authorization URL.
        
        Returns:
            Tuple of (authorization_url, state_token)
        """
        if not state:
            state = secrets.token_urlsafe(32)
        
        params = {
            "client_id": self.client_id,
            "response_type": "code",
            "redirect_uri": self.redirect_uri,
            "response_mode": "query",
            "scope": " ".join(self.SCOPES),
            "state": state,
            "prompt": "select_account"
        }
        
        auth_url = self.OAUTH_AUTHORIZE_URL.format(tenant_id=self.tenant_id)
        url = f"{auth_url}?{urlencode(params)}"
        
        logger.info(f"Generated authorization URL for state: {state}")
        return url, state
    
    def exchange_code_for_token(self, code: str) -> Optional[OAuthSession]:
        """
        Exchange authorization code for access and refresh tokens.
        
        Args:
            code: Authorization code from callback
            
        Returns:
            OAuthSession with tokens and user info, or None if failed
        """
        token_url = self.OAUTH_TOKEN_URL.format(tenant_id=self.tenant_id)
        
        data = {
            "client_id": self.client_id,
            "client_secret": self.client_secret,
            "code": code,
            "redirect_uri": self.redirect_uri,
            "grant_type": "authorization_code",
            "scope": " ".join(self.SCOPES)
        }
        
        try:
            logger.info("Exchanging authorization code for tokens")
            response = requests.post(token_url, data=data, timeout=10)
            response.raise_for_status()
            
            token_data = response.json()
            access_token = token_data["access_token"]
            refresh_token = token_data.get("refresh_token")
            expires_in = token_data.get("expires_in", 3600)
            expires_at = datetime.utcnow() + timedelta(seconds=expires_in)
            
            # Get user info
            user_id, user_email = self._get_user_info(access_token)
            
            if not user_id or not user_email:
                logger.error("Failed to get user info")
                return None
            
            session = OAuthSession(
                access_token=access_token,
                refresh_token=refresh_token,
                expires_at=expires_at,
                user_id=user_id,
                user_email=user_email
            )
            
            # Store session
            self.sessions[user_id] = session
            
            logger.info(f"Successfully authenticated user: {user_email}")
            return session
            
        except requests.exceptions.RequestException as e:
            logger.error(f"Token exchange failed: {e}")
            return None
    
    def refresh_access_token(self, user_id: str) -> Optional[OAuthSession]:
        """
        Refresh access token using refresh token.
        
        Args:
            user_id: User ID
            
        Returns:
            Updated OAuthSession, or None if failed
        """
        session = self.sessions.get(user_id)
        if not session or not session.refresh_token:
            logger.warning(f"No refresh token for user: {user_id}")
            return None
        
        token_url = self.OAUTH_TOKEN_URL.format(tenant_id=self.tenant_id)
        
        data = {
            "client_id": self.client_id,
            "client_secret": self.client_secret,
            "refresh_token": session.refresh_token,
            "grant_type": "refresh_token",
            "scope": " ".join(self.SCOPES)
        }
        
        try:
            logger.info(f"Refreshing token for user: {user_id}")
            response = requests.post(token_url, data=data, timeout=10)
            response.raise_for_status()
            
            token_data = response.json()
            access_token = token_data["access_token"]
            expires_in = token_data.get("expires_in", 3600)
            expires_at = datetime.utcnow() + timedelta(seconds=expires_in)
            
            # Update session
            session.access_token = access_token
            session.expires_at = expires_at
            
            logger.info(f"Token refreshed for user: {user_id}")
            return session
            
        except requests.exceptions.RequestException as e:
            logger.error(f"Token refresh failed: {e}")
            return None
    
    def get_valid_token(self, user_id: str) -> Optional[str]:
        """
        Get a valid access token for user, refreshing if needed.
        
        Args:
            user_id: User ID
            
        Returns:
            Valid access token, or None if unavailable
        """
        session = self.sessions.get(user_id)
        if not session:
            logger.warning(f"No session found for user: {user_id}")
            return None
        
        if session.is_expired():
            refreshed = self.refresh_access_token(user_id)
            if not refreshed:
                return None
            session = refreshed
        
        return session.access_token
    
    def get_session(self, user_id: str) -> Optional[OAuthSession]:
        """Get session for user."""
        return self.sessions.get(user_id)
    
    def logout(self, user_id: str) -> None:
        """Remove session for user."""
        if user_id in self.sessions:
            del self.sessions[user_id]
            logger.info(f"User logged out: {user_id}")
    
    def _get_user_info(self, access_token: str) -> tuple[Optional[str], Optional[str]]:
        """
        Fetch user info (ID and email) from Microsoft Graph.
        
        Returns:
            Tuple of (user_id, email) or (None, None) if failed
        """
        headers = {"Authorization": f"Bearer {access_token}"}
        
        try:
            response = requests.get(self.GRAPH_ME_URL, headers=headers, timeout=10)
            response.raise_for_status()
            
            user_data = response.json()
            user_id = user_data.get("id")
            email = user_data.get("userPrincipalName") or user_data.get("mail")
            
            logger.info(f"Retrieved user info: {email}")
            return user_id, email
            
        except requests.exceptions.RequestException as e:
            logger.error(f"Failed to get user info: {e}")
            return None, None
