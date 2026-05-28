from uuid import UUID

from fastapi import Depends, FastAPI, Header, HTTPException, status
from sqlalchemy.orm import Session

from shared.cors import setup_cors
from shared.database import get_db
from shared.enums import NotificationType
from shared.models import Notification
from shared.schemas import InternalNotifyRequest, MessageResponse, NotificationResponse
from shared.session_client import SessionClient, require_auth

app = FastAPI(title="NotificationService", version="1.0.0")
setup_cors(app)
session_client = SessionClient()


@app.get("/health")
def health() -> dict:
    return {"service": "notifications", "status": "ok"}


@app.post("/internal/notify", response_model=NotificationResponse)
def internal_notify(data: InternalNotifyRequest, db: Session = Depends(get_db)) -> NotificationResponse:
    try:
        ntype = NotificationType(data.type)
    except ValueError:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid notification type")

    notification = Notification(
        recipient_id=data.recipient_id,
        type=ntype,
        message=data.message,
        ticket_id=data.ticket_id,
    )
    db.add(notification)
    db.commit()
    db.refresh(notification)
    return NotificationResponse.model_validate(notification)


@app.get("/notifications/me", response_model=list[NotificationResponse])
def my_notifications(
    db: Session = Depends(get_db),
    authorization: str | None = Header(default=None),
    unread_only: bool = False,
) -> list[NotificationResponse]:
    token = require_auth(authorization)
    ctx = session_client.validate(token)

    query = db.query(Notification).filter(Notification.recipient_id == ctx.user_id)
    if unread_only:
        query = query.filter(Notification.is_read.is_(False))
    items = query.order_by(Notification.created_at.desc()).all()
    return [NotificationResponse.model_validate(n) for n in items]


@app.patch("/notifications/{notification_id}/read", response_model=NotificationResponse)
def mark_read(
    notification_id: UUID,
    db: Session = Depends(get_db),
    authorization: str | None = Header(default=None),
) -> NotificationResponse:
    token = require_auth(authorization)
    ctx = session_client.validate(token)

    notification = (
        db.query(Notification)
        .filter(
            Notification.id == notification_id,
            Notification.recipient_id == ctx.user_id,
        )
        .first()
    )
    if notification is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Notification not found")

    notification.is_read = True
    db.commit()
    db.refresh(notification)
    return NotificationResponse.model_validate(notification)


@app.patch("/notifications/read-all", response_model=MessageResponse)
def mark_all_read(
    db: Session = Depends(get_db),
    authorization: str | None = Header(default=None),
) -> MessageResponse:
    token = require_auth(authorization)
    ctx = session_client.validate(token)

    db.query(Notification).filter(
        Notification.recipient_id == ctx.user_id,
        Notification.is_read.is_(False),
    ).update({"is_read": True})
    db.commit()
    return MessageResponse(message="ok")
