#!/usr/bin/env python3
"""
CLI script to create a Microsoft Graph subscription for Teams messages.

Usage:
    python scripts/create_subscription.py --resource "/teams/{team-id}/channels/{channel-id}/messages"
"""

import argparse
import sys
import os
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv
from app.subscription import create_teams_subscription
from app.utils import setup_logging

# Load environment
load_dotenv()


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Create a Microsoft Graph subscription for Teams messages"
    )
    
    parser.add_argument(
        "--resource",
        required=True,
        help="Resource path to monitor (e.g., /teams/{id}/channels/{id}/messages)"
    )
    
    parser.add_argument(
        "--expiration-hours",
        type=int,
        default=1,
        help="Subscription expiration in hours (default: 1)"
    )
    
    parser.add_argument(
        "--webhook-url",
        help="Override webhook URL (default: from NGROK_URL env)"
    )
    
    args = parser.parse_args()
    
    # Setup logging
    setup_logging(os.getenv("LOG_LEVEL", "INFO"))
    
    # Get configuration from environment
    tenant_id = os.getenv("TENANT_ID")
    client_id = os.getenv("CLIENT_ID")
    client_secret = os.getenv("CLIENT_SECRET")
    ngrok_url = args.webhook_url or os.getenv("NGROK_URL")
    client_state = os.getenv("CLIENT_STATE_SECRET")
    
    # Validate configuration
    if not all([tenant_id, client_id, client_secret, ngrok_url, client_state]):
        print("ERROR: Missing required environment variables.")
        print("Please ensure .env file contains:")
        print("  - TENANT_ID")
        print("  - CLIENT_ID")
        print("  - CLIENT_SECRET")
        print("  - NGROK_URL")
        print("  - CLIENT_STATE_SECRET")
        sys.exit(1)
    
    # Build notification URL
    notification_url = f"{ngrok_url.rstrip('/')}/graph-webhook"
    
    print(f"\nCreating subscription...")
    print(f"Resource: {args.resource}")
    print(f"Webhook URL: {notification_url}")
    print(f"Expiration: {args.expiration_hours} hours")
    print()
    
    try:
        # Create subscription
        subscription = create_teams_subscription(
            tenant_id=tenant_id,
            client_id=client_id,
            client_secret=client_secret,
            resource=args.resource,
            notification_url=notification_url,
            client_state=client_state,
            expiration_hours=args.expiration_hours
        )
        
        print("✅ Subscription created successfully!")
        print()
        print(f"Subscription ID: {subscription['id']}")
        print(f"Resource: {subscription['resource']}")
        print(f"Expiration: {subscription['expirationDateTime']}")
        print()
        print("Save the subscription ID to renew or delete it later.")
        
    except Exception as e:
        print(f"❌ Failed to create subscription: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
