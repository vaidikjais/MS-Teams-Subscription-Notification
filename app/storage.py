"""
Storage module for SQLite database operations.
Manages notifications and normalized messages.
"""

from datetime import datetime
from typing import List, Optional
import json
import logging

from sqlalchemy import create_engine, Column, Integer, String, Text, DateTime
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, Session

logger = logging.getLogger(__name__)

Base = declarative_base()


class Notification(Base):
    """Model for storing raw Graph notifications."""
    
    __tablename__ = "notifications"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    subscription_id = Column(String(255), nullable=False, index=True)
    resource = Column(String(500), nullable=False)
    payload_json = Column(Text, nullable=False)
    status = Column(String(50), default="pending", index=True)  # pending, processing, done, failed
    created_at = Column(DateTime, default=datetime.utcnow)
    attempts = Column(Integer, default=0)
    error_message = Column(Text, nullable=True)
    

class Message(Base):
    """Model for storing normalized Teams messages."""
    
    __tablename__ = "messages"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    message_id = Column(String(255), unique=True, nullable=False, index=True)
    normalized_json = Column(Text, nullable=False)
    raw_json = Column(Text, nullable=False)
    ingested_at = Column(DateTime, default=datetime.utcnow)


class Database:
    """Database manager for SQLite operations."""
    
    def __init__(self, db_url: str):
        """
        Initialize database connection.
        
        Args:
            db_url: SQLAlchemy database URL
        """
        self.engine = create_engine(db_url, echo=False)
        self.SessionLocal = sessionmaker(bind=self.engine, autoflush=False, autocommit=False)
        Base.metadata.create_all(bind=self.engine)
        logger.info(f"Database initialized at {db_url}")
    
    def get_session(self) -> Session:
        """Get a new database session."""
        return self.SessionLocal()


# Global database instance (initialized in main.py)
_db: Optional[Database] = None


def init_db(db_url: str) -> Database:
    """
    Initialize the global database instance.
    
    Args:
        db_url: SQLAlchemy database URL
        
    Returns:
        Database instance
    """
    global _db
    _db = Database(db_url)
    return _db


def get_db() -> Database:
    """Get the global database instance."""
    if _db is None:
        raise RuntimeError("Database not initialized. Call init_db() first.")
    return _db


# Helper functions for notifications

def save_notification(
    subscription_id: str,
    resource: str,
    payload: dict
) -> int:
    """
    Save a new notification to the database.
    
    Args:
        subscription_id: Graph subscription ID
        resource: Resource path from notification
        payload: Full notification payload
        
    Returns:
        Notification ID
    """
    db = get_db()
    with db.get_session() as session:
        notification = Notification(
            subscription_id=subscription_id,
            resource=resource,
            payload_json=json.dumps(payload),
            status="pending",
            attempts=0
        )
        session.add(notification)
        session.commit()
        session.refresh(notification)
        logger.info(f"Saved notification {notification.id} for resource {resource}")
        return notification.id


def get_pending_notifications(limit: int = 10) -> List[Notification]:
    """
    Get pending notifications to process.
    
    Args:
        limit: Maximum number of notifications to retrieve
        
    Returns:
        List of pending notifications
    """
    db = get_db()
    with db.get_session() as session:
        notifications = session.query(Notification).filter(
            Notification.status == "pending"
        ).limit(limit).all()
        
        # Detach from session to avoid lazy loading issues
        session.expunge_all()
        return notifications


def mark_notification_processing(notification_id: int) -> None:
    """
    Mark a notification as being processed.
    
    Args:
        notification_id: Notification ID
    """
    db = get_db()
    with db.get_session() as session:
        notification = session.query(Notification).filter(
            Notification.id == notification_id
        ).first()
        
        if notification:
            notification.status = "processing"
            notification.attempts += 1
            session.commit()
            logger.debug(f"Marked notification {notification_id} as processing")


def mark_notification_done(notification_id: int) -> None:
    """
    Mark a notification as successfully processed.
    
    Args:
        notification_id: Notification ID
    """
    db = get_db()
    with db.get_session() as session:
        notification = session.query(Notification).filter(
            Notification.id == notification_id
        ).first()
        
        if notification:
            notification.status = "done"
            session.commit()
            logger.info(f"Marked notification {notification_id} as done")


def mark_notification_failed(notification_id: int, error_message: str) -> None:
    """
    Mark a notification as failed.
    
    Args:
        notification_id: Notification ID
        error_message: Error description
    """
    db = get_db()
    with db.get_session() as session:
        notification = session.query(Notification).filter(
            Notification.id == notification_id
        ).first()
        
        if notification:
            # If too many attempts, mark as failed, otherwise back to pending
            if notification.attempts >= 5:
                notification.status = "failed"
            else:
                notification.status = "pending"
            notification.error_message = error_message
            session.commit()
            logger.warning(f"Notification {notification_id} failed: {error_message}")


# Helper functions for messages

def save_message(message_id: str, normalized_data: dict, raw_data: dict) -> int:
    """
    Save a normalized message to the database.
    
    Args:
        message_id: Teams message ID
        normalized_data: Normalized message data
        raw_data: Raw Graph API response
        
    Returns:
        Message ID
    """
    db = get_db()
    with db.get_session() as session:
        # Check if message already exists
        existing = session.query(Message).filter(
            Message.message_id == message_id
        ).first()
        
        if existing:
            logger.info(f"Message {message_id} already exists, skipping")
            return existing.id
        
        message = Message(
            message_id=message_id,
            normalized_json=json.dumps(normalized_data),
            raw_json=json.dumps(raw_data)
        )
        session.add(message)
        session.commit()
        session.refresh(message)
        logger.info(f"Saved message {message_id} with ID {message.id}")
        return message.id


def get_message_by_id(message_id: str) -> Optional[Message]:
    """
    Retrieve a message by its Teams message ID.
    
    Args:
        message_id: Teams message ID
        
    Returns:
        Message object or None
    """
    db = get_db()
    with db.get_session() as session:
        message = session.query(Message).filter(
            Message.message_id == message_id
        ).first()
        
        if message:
            session.expunge(message)
        return message
