from sqlalchemy import Column, String, Boolean, DateTime, JSON, ForeignKey, Enum
from db.database import Base
import uuid
from datetime import datetime, timezone
import enum


class NotificationType(str, enum.Enum):
    POLICY_ACTIVATED = "POLICY_ACTIVATED"
    SIGNAL_ALERT = "SIGNAL_ALERT"
    CLAIM_CREATED = "CLAIM_CREATED"
    PAYOUT_SENT = "PAYOUT_SENT"


class Notification(Base):
    __tablename__ = "notifications"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    rider_id = Column(String, ForeignKey("riders.id"), nullable=False)
    type = Column(Enum(NotificationType), nullable=False)
    title = Column(String, nullable=False)
    message = Column(String, nullable=False)
    data = Column(JSON, default={})  # Additional notification metadata
    is_read = Column(Boolean, default=False)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))


async def create_notification(db, rider_id: str, type: NotificationType, title: str, message: str, metadata: dict = None):
    """Helper function to create a notification.
    
    Args:
        db: AsyncSession instance
        rider_id: ID of the rider to notify
        type: NotificationType enum value
        title: Notification title
        message: Notification message body
        metadata: Optional dict with additional data
        
    Returns:
        Created Notification instance
    """
    notification = Notification(
        rider_id=rider_id,
        type=type,
        title=title,
        message=message,
        data=metadata or {},
    )
    db.add(notification)
    await db.flush()
    return notification
