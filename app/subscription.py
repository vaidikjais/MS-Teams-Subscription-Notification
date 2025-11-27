"""Functions for managing Microsoft Graph subscriptions."""

import logging
from typing import Dict, Any
from app.graph_client import GraphClient

logger = logging.getLogger(__name__)


def create_teams_subscription(tenant_id: str, client_id: str, client_secret: str,
                             resource: str, notification_url: str, client_state: str,
                             expiration_hours: int = 1) -> Dict[str, Any]:
    """Create subscription for Teams messages."""
    logger.info(f"Creating subscription for resource: {resource}")
    client = GraphClient(tenant_id, client_id, client_secret)
    subscription = client.create_subscription(resource, notification_url, client_state, expiration_hours)
    logger.info(f"Created subscription: {subscription.get('id')}")
    return subscription


def renew_subscription(tenant_id: str, client_id: str, client_secret: str,
                      subscription_id: str, expiration_hours: int = 1) -> Dict[str, Any]:
    """Renew existing subscription."""
    logger.info(f"Renewing subscription: {subscription_id}")
    client = GraphClient(tenant_id, client_id, client_secret)
    subscription = client.renew_subscription(subscription_id, expiration_hours)
    logger.info(f"Renewed subscription: {subscription_id}")
    return subscription


def list_subscriptions(tenant_id: str, client_id: str, client_secret: str) -> list:
    """List all active subscriptions."""
    logger.info("Listing subscriptions")
    client = GraphClient(tenant_id, client_id, client_secret)
    subscriptions = client.list_subscriptions()
    logger.info(f"Found {len(subscriptions)} subscriptions")
    return subscriptions


def delete_subscription(tenant_id: str, client_id: str, client_secret: str, subscription_id: str) -> None:
    """Delete subscription."""
    logger.info(f"Deleting subscription: {subscription_id}")
    client = GraphClient(tenant_id, client_id, client_secret)
    client.delete_subscription(subscription_id)
    logger.info(f"Deleted subscription: {subscription_id}")
