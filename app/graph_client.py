from datetime import datetime, timedelta
from typing import Optional, Dict, Any
import logging
import requests

logger = logging.getLogger(__name__)


class GraphClient:
    """Client for Microsoft Graph API with app-only authentication."""
    
    GRAPH_BASE_URL = "https://graph.microsoft.com/v1.0"
    TOKEN_URL = "https://login.microsoftonline.com/{tenant_id}/oauth2/v2.0/token"
    
    def __init__(self, tenant_id: str, client_id: str, client_secret: str):
        self.tenant_id = tenant_id
        self.client_id = client_id
        self.client_secret = client_secret
        self._token: Optional[str] = None
        self._token_expiry: Optional[datetime] = None
        logger.info("Graph client initialized")
    
    def get_access_token(self, force_refresh: bool = False) -> str:
        """Get valid access token, refreshing if necessary."""
        if not force_refresh and self._token and self._token_expiry:
            if datetime.utcnow() < self._token_expiry - timedelta(minutes=5):
                logger.debug("Using cached access token")
                return self._token
        
        logger.info("Acquiring new access token")
        token_url = self.TOKEN_URL.format(tenant_id=self.tenant_id)
        
        data = {
            "client_id": self.client_id,
            "client_secret": self.client_secret,
            "scope": "https://graph.microsoft.com/.default",
            "grant_type": "client_credentials"
        }
        
        try:
            response = requests.post(token_url, data=data, timeout=10)
            response.raise_for_status()
            
            token_data = response.json()
            self._token = token_data["access_token"]
            expires_in = token_data.get("expires_in", 3600)
            self._token_expiry = datetime.utcnow() + timedelta(seconds=expires_in)
            
            logger.info(f"Access token acquired, expires in {expires_in}s")
            return self._token
            
        except requests.exceptions.RequestException as e:
            logger.error(f"Failed to acquire access token: {e}")
            raise Exception(f"Token acquisition failed: {e}")
    
    def _make_request(self, method: str, url: str, **kwargs) -> requests.Response:
        """Make authenticated request to Graph API with retry logic."""
        if not url.startswith("http"):
            url = f"{self.GRAPH_BASE_URL}{url}"
        
        token = self.get_access_token()
        headers = kwargs.pop("headers", {})
        headers["Authorization"] = f"Bearer {token}"
        
        max_retries = 3
        retry_delay = 1
        
        for attempt in range(max_retries):
            try:
                response = requests.request(method, url, headers=headers, timeout=30, **kwargs)
                
                if response.status_code == 429:
                    retry_after = int(response.headers.get("Retry-After", 60))
                    logger.warning(f"Rate limited, retry after {retry_after}s")
                    if attempt < max_retries - 1:
                        import time
                        time.sleep(retry_after)
                        continue
                
                if response.status_code == 401 and attempt < max_retries - 1:
                    logger.warning("Unauthorized, refreshing token")
                    self.get_access_token(force_refresh=True)
                    token = self._token
                    headers["Authorization"] = f"Bearer {token}"
                    continue
                
                response.raise_for_status()
                return response
                
            except requests.exceptions.RequestException as e:
                # Log detailed error response if available
                error_detail = ""
                if hasattr(e, 'response') and e.response is not None:
                    try:
                        error_json = e.response.json()
                        error_detail = f" - Details: {error_json}"
                    except:
                        error_detail = f" - Response: {e.response.text[:200]}"
                
                logger.error(f"Request failed (attempt {attempt + 1}/{max_retries}): {e}{error_detail}")
                if attempt < max_retries - 1:
                    import time
                    time.sleep(retry_delay * (2 ** attempt))
                else:
                    raise Exception(f"Request failed after {max_retries} attempts: {e}{error_detail}")
        
        raise Exception("Request failed")
    
    def get_message(self, resource_path: str) -> Dict[str, Any]:
        """Fetch Teams message from Graph API."""
        logger.info(f"Fetching message from {resource_path}")
        
        if resource_path.startswith("https://"):
            from urllib.parse import urlparse
            resource_path = urlparse(resource_path).path
        
        if "/v1.0/" in resource_path:
            resource_path = resource_path.split("/v1.0/", 1)[1]
        elif "/beta/" in resource_path:
            resource_path = resource_path.split("/beta/", 1)[1]
        
        if not resource_path.startswith("/"):
            resource_path = f"/{resource_path}"
        
        response = self._make_request("GET", resource_path)
        message_data = response.json()
        logger.info(f"Successfully fetched message {message_data.get('id')}")
        return message_data
    
    def create_subscription(self, resource: str, notification_url: str, 
                           client_state: str, expiration_hours: int = 1) -> Dict[str, Any]:
        """Create Graph change notification subscription."""
        expiration = datetime.utcnow() + timedelta(hours=expiration_hours)
        expiration_str = expiration.strftime("%Y-%m-%dT%H:%M:%S.0000000Z")
        
        subscription_data = {
            "changeType": "created,updated",
            "notificationUrl": notification_url,
            "resource": resource,
            "expirationDateTime": expiration_str,
            "clientState": client_state
        }
        
        logger.info(f"Creating subscription for {resource}")
        response = self._make_request("POST", "/subscriptions", json=subscription_data)
        subscription = response.json()
        logger.info(f"Created subscription {subscription.get('id')}")
        return subscription
    
    def renew_subscription(self, subscription_id: str, expiration_hours: int = 1) -> Dict[str, Any]:
        """Renew existing subscription."""
        expiration = datetime.utcnow() + timedelta(hours=expiration_hours)
        expiration_str = expiration.strftime("%Y-%m-%dT%H:%M:%S.0000000Z")
        
        logger.info(f"Renewing subscription {subscription_id}")
        response = self._make_request("PATCH", f"/subscriptions/{subscription_id}", 
                                     json={"expirationDateTime": expiration_str})
        return response.json()
    
    def delete_subscription(self, subscription_id: str) -> None:
        """Delete subscription."""
        logger.info(f"Deleting subscription {subscription_id}")
        self._make_request("DELETE", f"/subscriptions/{subscription_id}")
        logger.info(f"Deleted subscription {subscription_id}")
    
    def list_subscriptions(self) -> list:
        """List all active subscriptions."""
        logger.info("Listing subscriptions")
        response = self._make_request("GET", "/subscriptions")
        subscriptions = response.json().get("value", [])
        logger.info(f"Found {len(subscriptions)} subscriptions")
        return subscriptions
