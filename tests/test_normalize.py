"""
Tests for message normalization.
"""

import pytest
from datetime import datetime

from app.schema import normalize_message, NormalizedMessage, strip_html


def test_strip_html():
    """Test HTML stripping function."""
    # Basic HTML
    html = "<p>Hello <strong>world</strong>!</p>"
    assert strip_html(html) == "Hello world!"
    
    # HTML entities
    html = "&lt;div&gt; Test &amp; Example &quot;quoted&quot;"
    assert strip_html(html) == "<div> Test & Example \"quoted\""
    
    # Multiple spaces
    html = "<p>Too    many   spaces</p>"
    assert strip_html(html) == "Too many spaces"
    
    # Empty
    assert strip_html("") == ""
    assert strip_html(None) == ""


def test_normalize_basic_message():
    """Test normalization of a basic Teams message."""
    graph_message = {
        "id": "1234567890",
        "createdDateTime": "2025-11-22T10:30:00Z",
        "from": {
            "user": {
                "id": "user-123",
                "displayName": "John Doe"
            }
        },
        "body": {
            "contentType": "html",
            "content": "<p>Hello team!</p>"
        },
        "webUrl": "https://teams.microsoft.com/l/message/19%3Achannel-id%40thread.tacv2/1234567890?groupId=team-id-123",
        "mentions": [],
        "attachments": []
    }
    
    normalized = normalize_message(graph_message)
    
    assert isinstance(normalized, NormalizedMessage)
    assert normalized.message_id == "1234567890"
    assert normalized.sender_id == "user-123"
    assert normalized.sender_name == "John Doe"
    assert normalized.body_text == "Hello team!"
    assert normalized.team_id == "team-id-123"
    assert len(normalized.mentions) == 0
    assert len(normalized.attachments) == 0


def test_normalize_message_with_mentions():
    """Test normalization of a message with mentions."""
    graph_message = {
        "id": "msg-001",
        "createdDateTime": "2025-11-22T15:45:00Z",
        "from": {
            "user": {
                "id": "user-456",
                "displayName": "Jane Smith"
            }
        },
        "body": {
            "contentType": "html",
            "content": "<p><at>@John Doe</at> can you help?</p>"
        },
        "webUrl": "https://teams.microsoft.com/l/message/channel-id/msg-001?groupId=team-id",
        "mentions": [
            {
                "id": 0,
                "mentionText": "@John Doe",
                "mentioned": {
                    "user": {
                        "id": "user-789",
                        "displayName": "John Doe"
                    }
                }
            }
        ],
        "attachments": []
    }
    
    normalized = normalize_message(graph_message)
    
    assert normalized.message_id == "msg-001"
    assert len(normalized.mentions) == 1
    assert normalized.mentions[0].user_id == "user-789"
    assert normalized.mentions[0].display_name == "John Doe"
    assert normalized.mentions[0].mentioned_text == "@John Doe"


def test_normalize_message_with_attachments():
    """Test normalization of a message with attachments."""
    graph_message = {
        "id": "msg-002",
        "createdDateTime": "2025-11-22T16:00:00Z",
        "from": {
            "user": {
                "id": "user-111",
                "displayName": "Alice Brown"
            }
        },
        "body": {
            "contentType": "html",
            "content": "<p>Check out this file</p>"
        },
        "webUrl": "https://teams.microsoft.com/l/message/channel-id/msg-002?groupId=team-id",
        "mentions": [],
        "attachments": [
            {
                "id": "attach-001",
                "contentType": "application/pdf",
                "contentUrl": "https://example.com/file.pdf",
                "name": "document.pdf"
            }
        ]
    }
    
    normalized = normalize_message(graph_message)
    
    assert normalized.message_id == "msg-002"
    assert len(normalized.attachments) == 1
    assert normalized.attachments[0].id == "attach-001"
    assert normalized.attachments[0].content_type == "application/pdf"
    assert normalized.attachments[0].name == "document.pdf"


def test_normalize_message_missing_id():
    """Test that normalization fails without message ID."""
    graph_message = {
        "createdDateTime": "2025-11-22T10:30:00Z",
        "from": {"user": {"id": "user-123"}},
        "body": {"content": "Test"}
    }
    
    with pytest.raises(ValueError, match="Message ID is required"):
        normalize_message(graph_message)


def test_normalize_message_missing_datetime():
    """Test that normalization fails without created datetime."""
    graph_message = {
        "id": "msg-003",
        "from": {"user": {"id": "user-123"}},
        "body": {"content": "Test"}
    }
    
    with pytest.raises(ValueError, match="Created datetime is required"):
        normalize_message(graph_message)


def test_normalize_message_preserves_raw_json():
    """Test that raw JSON is preserved in normalized message."""
    graph_message = {
        "id": "msg-004",
        "createdDateTime": "2025-11-22T10:30:00Z",
        "from": {
            "user": {
                "id": "user-123",
                "displayName": "Test User"
            }
        },
        "body": {
            "content": "Test message"
        },
        "customField": "custom value"
    }
    
    normalized = normalize_message(graph_message)
    
    assert normalized.raw_json == graph_message
    assert "customField" in normalized.raw_json
