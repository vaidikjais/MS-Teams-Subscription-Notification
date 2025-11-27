"""Utility functions for validation, logging, and helpers."""

import logging
import sys
import re
from typing import Optional


def setup_logging(log_level: str = "INFO") -> None:
    """Configure application logging."""
    numeric_level = getattr(logging, log_level.upper(), logging.INFO)
    logging.basicConfig(
        level=numeric_level,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        handlers=[logging.StreamHandler(sys.stdout)]
    )


def validate_client_state(received_state: Optional[str], expected_state: str) -> bool:
    """Validate clientState from Graph notification."""
    return received_state == expected_state if received_state else False


def extract_resource_path(notification_data: dict) -> str:
    """Extract resource path from notification data."""
    resource = notification_data.get("resource")
    if resource:
        return resource
    
    resource_data = notification_data.get("resourceData", {})
    odata_id = resource_data.get("@odata.id")
    if odata_id:
        return odata_id
    
    resource_id = resource_data.get("id")
    if resource_id:
        return f"/messages/{resource_id}"
    
    raise ValueError("Could not extract resource path from notification")


def parse_resource_ids(resource_path: str) -> dict:
    """Parse team, channel, and message IDs from resource path."""
    ids = {"team_id": None, "channel_id": None, "message_id": None}
    pattern = r'/teams/([^/]+)/channels/([^/]+)/messages/([^/]+)'
    match = re.search(pattern, resource_path)
    
    if match:
        ids["team_id"] = match.group(1)
        ids["channel_id"] = match.group(2)
        ids["message_id"] = match.group(3)
    
    return ids
