"""
Pytest configuration and shared fixtures.
"""

import pytest
import os
import sys
from pathlib import Path

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))


@pytest.fixture
def sample_graph_message():
    """Sample Graph API message response."""
    return {
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
            "content": "<p>Hello <strong>team</strong>!</p>"
        },
        "webUrl": "https://teams.microsoft.com/l/message/19%3Achannel-id%40thread.tacv2/1234567890?groupId=team-id-123",
        "mentions": [],
        "attachments": []
    }


@pytest.fixture
def sample_notification():
    """Sample Graph notification."""
    return {
        "subscriptionId": "sub-123",
        "clientState": "test-secret",
        "changeType": "created",
        "resource": "teams/team-id/channels/channel-id/messages/msg-id",
        "resourceData": {
            "@odata.type": "#Microsoft.Graph.chatMessage",
            "@odata.id": "teams/team-id/channels/channel-id/messages/msg-id",
            "id": "msg-id"
        }
    }


@pytest.fixture
def mock_env_vars(monkeypatch):
    """Mock environment variables for testing."""
    monkeypatch.setenv("TENANT_ID", "test-tenant-id")
    monkeypatch.setenv("CLIENT_ID", "test-client-id")
    monkeypatch.setenv("CLIENT_SECRET", "test-client-secret")
    monkeypatch.setenv("NGROK_URL", "https://test.ngrok.io")
    monkeypatch.setenv("CLIENT_STATE_SECRET", "test-secret")
    monkeypatch.setenv("DB_PATH", "sqlite:///:memory:")
    monkeypatch.setenv("LOG_LEVEL", "ERROR")
