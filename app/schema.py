"""
Pydantic models for normalized Teams messages and validation.
"""

from datetime import datetime
from typing import Optional, List, Dict, Any
from pydantic import BaseModel, Field
import re
import logging

logger = logging.getLogger(__name__)


class Mention(BaseModel):
    """Model for a user mention in a message."""
    
    user_id: Optional[str] = None
    display_name: Optional[str] = None
    mentioned_text: Optional[str] = None


class Attachment(BaseModel):
    """Model for a message attachment."""
    
    id: Optional[str] = None
    content_type: Optional[str] = None
    content_url: Optional[str] = None
    name: Optional[str] = None


class NormalizedMessage(BaseModel):
    """Normalized Teams message schema."""
    
    message_id: str = Field(..., description="Unique message ID")
    created_datetime: datetime = Field(..., description="Message creation timestamp")
    team_id: Optional[str] = Field(None, description="Team ID (if available)")
    channel_id: Optional[str] = Field(None, description="Channel ID (if available)")
    sender_id: Optional[str] = Field(None, description="Sender user ID")
    sender_name: Optional[str] = Field(None, description="Sender display name")
    body_text: str = Field("", description="Message body text (HTML stripped)")
    mentions: List[Mention] = Field(default_factory=list, description="List of mentions")
    attachments: List[Attachment] = Field(default_factory=list, description="List of attachments")
    raw_json: Dict[str, Any] = Field(..., description="Original Graph API response")
    
    class Config:
        json_schema_extra = {
            "example": {
                "message_id": "1234567890",
                "created_datetime": "2025-11-22T10:30:00Z",
                "team_id": "team-id-123",
                "channel_id": "channel-id-456",
                "sender_id": "user-id-789",
                "sender_name": "John Doe",
                "body_text": "Hello team! This is a test message.",
                "mentions": [],
                "attachments": [],
                "raw_json": {}
            }
        }


def strip_html(html_content: str) -> str:
    """
    Strip HTML tags from content.
    
    Args:
        html_content: HTML string
        
    Returns:
        Plain text content
    """
    if not html_content:
        return ""
    
    # Remove HTML tags
    text = re.sub(r'<[^>]+>', '', html_content)
    
    # Decode common HTML entities
    text = text.replace('&nbsp;', ' ')
    text = text.replace('&lt;', '<')
    text = text.replace('&gt;', '>')
    text = text.replace('&amp;', '&')
    text = text.replace('&quot;', '"')
    text = text.replace('&#39;', "'")
    
    # Clean up whitespace
    text = re.sub(r'\s+', ' ', text).strip()
    
    return text


def normalize_message(graph_message: Dict[str, Any]) -> NormalizedMessage:
    """
    Normalize a Graph API message response into our schema.
    
    Args:
        graph_message: Raw message data from Graph API
        
    Returns:
        NormalizedMessage object
        
    Raises:
        ValueError: If required fields are missing
    """
    try:
        # Extract basic fields
        message_id = graph_message.get("id")
        if not message_id:
            raise ValueError("Message ID is required")
        
        created_datetime_str = graph_message.get("createdDateTime")
        if not created_datetime_str:
            raise ValueError("Created datetime is required")
        
        # Parse datetime
        created_datetime = datetime.fromisoformat(
            created_datetime_str.replace("Z", "+00:00")
        )
        
        # Extract IDs from webUrl or other fields
        team_id = None
        channel_id = None
        
        web_url = graph_message.get("webUrl", "")
        if web_url:
            # Parse team and channel IDs from webUrl
            # Format: https://teams.microsoft.com/l/message/{channel-id}/...?groupId={team-id}
            team_match = re.search(r'groupId=([^&]+)', web_url)
            if team_match:
                team_id = team_match.group(1)
            
            channel_match = re.search(r'/l/message/([^/]+)/', web_url)
            if channel_match:
                channel_id = channel_match.group(1).split('@')[0]
        
        # Extract sender info
        sender = graph_message.get("from", {})
        sender_user = sender.get("user", {})
        sender_id = sender_user.get("id")
        sender_name = sender_user.get("displayName")
        
        # Extract and clean body text
        body = graph_message.get("body", {})
        body_content = body.get("content", "")
        body_text = strip_html(body_content)
        
        # Extract mentions
        mentions = []
        mentions_data = graph_message.get("mentions", [])
        for mention_data in mentions_data:
            mentioned = mention_data.get("mentioned", {})
            mention = Mention(
                user_id=mentioned.get("user", {}).get("id"),
                display_name=mentioned.get("user", {}).get("displayName"),
                mentioned_text=mention_data.get("mentionText")
            )
            mentions.append(mention)
        
        # Extract attachments
        attachments = []
        attachments_data = graph_message.get("attachments", [])
        for attachment_data in attachments_data:
            attachment = Attachment(
                id=attachment_data.get("id"),
                content_type=attachment_data.get("contentType"),
                content_url=attachment_data.get("contentUrl"),
                name=attachment_data.get("name")
            )
            attachments.append(attachment)
        
        # Create normalized message
        normalized = NormalizedMessage(
            message_id=message_id,
            created_datetime=created_datetime,
            team_id=team_id,
            channel_id=channel_id,
            sender_id=sender_id,
            sender_name=sender_name,
            body_text=body_text,
            mentions=mentions,
            attachments=attachments,
            raw_json=graph_message
        )
        
        logger.info(f"Normalized message {message_id}")
        return normalized
        
    except Exception as e:
        logger.error(f"Failed to normalize message: {e}")
        raise ValueError(f"Message normalization failed: {e}")


class GraphNotification(BaseModel):
    """Model for Graph change notification."""
    
    subscription_id: str = Field(..., alias="subscriptionId")
    client_state: Optional[str] = Field(None, alias="clientState")
    change_type: str = Field(..., alias="changeType")
    resource: str
    resource_data: Optional[Dict[str, Any]] = Field(None, alias="resourceData")
    subscription_expiration_datetime: Optional[str] = Field(
        None, alias="subscriptionExpirationDateTime"
    )
    
    class Config:
        populate_by_name = True


class NotificationCollection(BaseModel):
    """Collection of notifications from Graph webhook."""
    
    validation_tokens: Optional[List[str]] = Field(None, alias="validationTokens")
    value: List[GraphNotification] = Field(default_factory=list)
    
    class Config:
        populate_by_name = True


class SubscriptionCreateRequest(BaseModel):
    """Request model for creating a new subscription."""
    
    resource: str = Field(
        ...,
        description="Resource path to monitor (e.g., /teams/{team-id}/channels/{channel-id}/messages)",
        example="/teams/abc123/channels/19:def456@thread.tacv2/messages"
    )
    expiration_hours: int = Field(
        default=1,
        ge=1,
        le=4230,
        description="Subscription expiration in hours (max 4230 hours for Teams channel messages)"
    )


class SubscriptionResponse(BaseModel):
    """Response model for subscription details."""
    
    id: str = Field(..., description="Subscription ID")
    resource: str = Field(..., description="Resource being monitored")
    change_type: str = Field(..., alias="changeType", description="Types of changes monitored")
    notification_url: str = Field(..., alias="notificationUrl", description="Webhook URL")
    expiration_datetime: str = Field(..., alias="expirationDateTime", description="When subscription expires")
    client_state: Optional[str] = Field(None, alias="clientState", description="Client state secret")
    
    class Config:
        populate_by_name = True


class SubscriptionListResponse(BaseModel):
    """Response model for listing subscriptions."""
    
    subscriptions: List[SubscriptionResponse] = Field(default_factory=list)
    count: int = Field(..., description="Number of active subscriptions")
