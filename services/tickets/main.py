from datetime import datetime, timezone
from uuid import UUID

from fastapi import Depends, FastAPI, Header, HTTPException, status
from sqlalchemy.orm import Session, joinedload

from shared.database import get_db
from shared.enums import NotificationType, PermissionCode, TicketStatus
from shared.models import Address, Ticket, TicketRating, User
from shared.schemas import TicketCreate, TicketRatingCreate, TicketResponse, TicketStatusUpdate
from shared.session_client import SessionClient, notify_client_post, require_auth, require_permission

app = FastAPI(title="TicketsService", version="1.0.0")
session_client = SessionClient()


def _ticket_to_response(ticket: Ticket) -> TicketResponse:
    return TicketResponse(
        id=ticket.id,
        title=ticket.title,
        description=ticket.description,
        category=ticket.category,
        status=ticket.status,
        resident_id=ticket.resident_id,
        worker_id=ticket.worker_id,
        address_id=ticket.address_id,
        created_at=ticket.created_at,
        updated_at=ticket.updated_at,
        completed_at=ticket.completed_at,
        rating_value=ticket.rating.value if ticket.rating else None,
    )


@app.get("/health")
def health() -> dict:
    return {"service": "tickets", "status": "ok"}


@app.post("/tickets", response_model=TicketResponse, status_code=status.HTTP_201_CREATED)
def create_ticket(
    data: TicketCreate,
    db: Session = Depends(get_db),
    authorization: str | None = Header(default=None),
) -> TicketResponse:
    token = require_auth(authorization)
    ctx = session_client.validate(token)
    require_permission(ctx, PermissionCode.CREATE_TICKET)

    address = db.query(Address).filter(Address.id == data.address_id).first()
    if address is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Address not found")

    ticket = Ticket(
        title=data.title,
        description=data.description,
        category=data.category,
        status=TicketStatus.CREATED,
        resident_id=ctx.user_id,
        address_id=data.address_id,
    )
    db.add(ticket)
    db.commit()
    db.refresh(ticket)

    notify_client_post(
        ctx.user_id,
        NotificationType.TICKET_CREATED.value,
        f"Заявка создана: {ticket.title}",
        ticket.id,
    )
    return _ticket_to_response(ticket)


@app.get("/tickets/me", response_model=list[TicketResponse])
def my_tickets(
    db: Session = Depends(get_db),
    authorization: str | None = Header(default=None),
) -> list[TicketResponse]:
    token = require_auth(authorization)
    ctx = session_client.validate(token)
    require_permission(ctx, PermissionCode.VIEW_OWN_TICKETS)

    tickets = (
        db.query(Ticket)
        .options(joinedload(Ticket.rating))
        .filter(Ticket.resident_id == ctx.user_id)
        .order_by(Ticket.created_at.desc())
        .all()
    )
    return [_ticket_to_response(t) for t in tickets]


@app.get("/tickets/worker", response_model=list[TicketResponse])
def worker_tickets(
    db: Session = Depends(get_db),
    authorization: str | None = Header(default=None),
) -> list[TicketResponse]:
    token = require_auth(authorization)
    ctx = session_client.validate(token)
    require_permission(ctx, PermissionCode.VIEW_TICKETS_BY_ADDRESS)

    tickets = (
        db.query(Ticket)
        .options(joinedload(Ticket.rating))
        .order_by(Ticket.created_at.desc())
        .all()
    )
    return [_ticket_to_response(t) for t in tickets]


@app.patch("/tickets/{ticket_id}/status", response_model=TicketResponse)
def change_status(
    ticket_id: UUID,
    data: TicketStatusUpdate,
    db: Session = Depends(get_db),
    authorization: str | None = Header(default=None),
) -> TicketResponse:
    token = require_auth(authorization)
    ctx = session_client.validate(token)
    require_permission(ctx, PermissionCode.CHANGE_TICKET_STATUS)

    ticket = (
        db.query(Ticket)
        .options(joinedload(Ticket.rating))
        .filter(Ticket.id == ticket_id)
        .first()
    )
    if ticket is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Ticket not found")

    ticket.status = data.status
    if data.worker_id:
        ticket.worker_id = data.worker_id
    elif ticket.worker_id is None:
        ticket.worker_id = ctx.user_id

    if data.status == TicketStatus.DONE:
        ticket.completed_at = datetime.now(timezone.utc)
    if data.status == TicketStatus.CANCELLED:
        ticket.completed_at = None

    db.commit()
    db.refresh(ticket)

    notify_client_post(
        ticket.resident_id,
        NotificationType.TICKET_STATUS_CHANGED.value,
        f"Статус заявки «{ticket.title}»: {ticket.status.value}",
        ticket.id,
    )
    return _ticket_to_response(ticket)


@app.post("/tickets/{ticket_id}/rate", response_model=TicketResponse)
def rate_ticket(
    ticket_id: UUID,
    data: TicketRatingCreate,
    db: Session = Depends(get_db),
    authorization: str | None = Header(default=None),
) -> TicketResponse:
    token = require_auth(authorization)
    ctx = session_client.validate(token)

    ticket = (
        db.query(Ticket)
        .options(joinedload(Ticket.rating))
        .filter(Ticket.id == ticket_id, Ticket.resident_id == ctx.user_id)
        .first()
    )
    if ticket is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Ticket not found")
    if ticket.status != TicketStatus.DONE:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Rating allowed only for DONE tickets",
        )
    if ticket.rating is not None:
        ticket.rating.value = data.value
        ticket.rating.comment = data.comment
    else:
        db.add(
            TicketRating(
                ticket_id=ticket.id,
                user_id=ctx.user_id,
                value=data.value,
                comment=data.comment,
            )
        )
    db.commit()
    db.refresh(ticket)
    ticket = (
        db.query(Ticket)
        .options(joinedload(Ticket.rating))
        .filter(Ticket.id == ticket_id)
        .first()
    )
    return _ticket_to_response(ticket)
