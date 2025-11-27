"""
Tests for subscription creation.
"""

import pytest
from unittest.mock import Mock, patch, MagicMock

from app.subscription import create_teams_subscription


@patch('app.subscription.GraphClient')
def test_create_subscription_success(mock_graph_client_class):
    """Test successful subscription creation."""
    # Setup mock
    mock_client = Mock()
    mock_graph_client_class.return_value = mock_client
    
    expected_subscription = {
        "id": "sub-123",
        "resource": "/teams/team-id/channels/channel-id/messages",
        "notificationUrl": "https://example.com/webhook",
        "expirationDateTime": "2025-11-22T11:30:00Z",
        "clientState": "secret123"
    }
    
    mock_client.create_subscription.return_value = expected_subscription
    
    # Call function
    result = create_teams_subscription(
        tenant_id="tenant-123",
        client_id="client-456",
        client_secret="secret",
        resource="/teams/team-id/channels/channel-id/messages",
        notification_url="https://example.com/webhook",
        client_state="secret123",
        expiration_hours=1
    )
    
    # Verify GraphClient was initialized correctly
    mock_graph_client_class.assert_called_once_with(
        "tenant-123",
        "client-456",
        "secret"
    )
    
    # Verify create_subscription was called with correct parameters
    mock_client.create_subscription.assert_called_once_with(
        resource="/teams/team-id/channels/channel-id/messages",
        notification_url="https://example.com/webhook",
        client_state="secret123",
        expiration_hours=1
    )
    
    # Verify result
    assert result == expected_subscription
    assert result["id"] == "sub-123"


@patch('app.subscription.GraphClient')
def test_create_subscription_validates_parameters(mock_graph_client_class):
    """Test that subscription creation validates required fields."""
    mock_client = Mock()
    mock_graph_client_class.return_value = mock_client
    
    mock_client.create_subscription.return_value = {
        "id": "sub-456",
        "resource": "/teams/test/channels/test/messages",
        "notificationUrl": "https://webhook.example.com",
        "expirationDateTime": "2025-11-23T10:00:00Z"
    }
    
    # Call with all required parameters
    result = create_teams_subscription(
        tenant_id="tenant-id",
        client_id="client-id",
        client_secret="client-secret",
        resource="/teams/test/channels/test/messages",
        notification_url="https://webhook.example.com",
        client_state="state-secret"
    )
    
    # Verify the subscription was created
    assert result["id"] == "sub-456"
    
    # Verify create_subscription received the client_state
    call_kwargs = mock_client.create_subscription.call_args[1]
    assert call_kwargs["client_state"] == "state-secret"


@patch('app.subscription.GraphClient')
def test_create_subscription_with_custom_expiration(mock_graph_client_class):
    """Test subscription creation with custom expiration."""
    mock_client = Mock()
    mock_graph_client_class.return_value = mock_client
    
    mock_client.create_subscription.return_value = {
        "id": "sub-789",
        "expirationDateTime": "2025-11-22T14:00:00Z"
    }
    
    # Call with custom expiration
    create_teams_subscription(
        tenant_id="tenant",
        client_id="client",
        client_secret="secret",
        resource="/teams/t/channels/c/messages",
        notification_url="https://example.com/webhook",
        client_state="state",
        expiration_hours=3
    )
    
    # Verify expiration_hours was passed
    call_kwargs = mock_client.create_subscription.call_args[1]
    assert call_kwargs["expiration_hours"] == 3


@patch('app.subscription.GraphClient')
def test_create_subscription_handles_errors(mock_graph_client_class):
    """Test that subscription creation handles API errors."""
    mock_client = Mock()
    mock_graph_client_class.return_value = mock_client
    
    # Simulate an error
    mock_client.create_subscription.side_effect = Exception("API Error")
    
    # Verify exception is propagated
    with pytest.raises(Exception, match="API Error"):
        create_teams_subscription(
            tenant_id="tenant",
            client_id="client",
            client_secret="secret",
            resource="/teams/t/channels/c/messages",
            notification_url="https://example.com/webhook",
            client_state="state"
        )
