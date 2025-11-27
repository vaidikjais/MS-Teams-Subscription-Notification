#!/usr/bin/env python3
"""Get chat IDs for subscription creation."""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv
import os
from app.graph_client import GraphClient

load_dotenv()


def main():
    client = GraphClient(
        os.getenv("TENANT_ID"),
        os.getenv("CLIENT_ID"),
        os.getenv("CLIENT_SECRET")
    )
    
    print("\n=== Your Chats ===\n")
    
    try:
        response = client._make_request("GET", "/me/chats")
        chats = response.json()
        
        for i, chat in enumerate(chats.get("value", []), 1):
            chat_type = chat.get("chatType", "unknown")
            topic = chat.get("topic", "No topic")
            
            print(f"{i}. {topic}")
            print(f"   Type: {chat_type}")
            print(f"   Chat ID: {chat['id']}")
            print(f"   Resource: /chats/{chat['id']}/messages")
            print()
        
        print("\n💡 To subscribe to ALL chats:")
        print("   Resource: /chats/getAllMessages")
            
    except Exception as e:
        print(f"❌ Error: {e}")
        print("\nMake sure you have Chat.Read.All permission granted!")


if __name__ == "__main__":
    main()
