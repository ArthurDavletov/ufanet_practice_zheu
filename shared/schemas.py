from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, EmailStr, Field

from shared.enums import NotificationType, PermissionCode, RoleName, TicketStatus, UserStatus


class UserContext(BaseModel):
    user_id: UUID
    login: str
    roles: list[str]
    permissions: list[str]


class TokenPair(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"


class RegisterRequest(BaseModel):
    full_name: str = Field(min_length=2, max_length=255)
    login: str = Field(min_length=3, max_length=64)
    email: EmailStr
    password: str = Field(min_length=6, max_length=128)


class LoginRequest(BaseModel):
    login: str
    password: str


class RefreshRequest(BaseModel):
    refresh_token: str


class AssignRoleRequest(BaseModel):
    user_id: UUID
    role_name: RoleName


class GrantPermissionRequest(BaseModel):
    user_id: UUID
    permission_code: PermissionCode
    address_id: UUID | None = None


class UserResponse(BaseModel):
    id: UUID
    full_name: str
    login: str
    email: str
    status: UserStatus
    roles: list[str]
    permissions: list[str]


class ValidateSessionRequest(BaseModel):
    access_token: str


class CheckPermissionRequest(BaseModel):
    access_token: str
    permission: PermissionCode


class AddressCreate(BaseModel):
    building: str
    entrance: str | None = None
    floor: int | None = None
    apartment: str
    room: str | None = None


class AddressResponse(AddressCreate):
    id: UUID

    model_config = {"from_attributes": True}


class TicketCreate(BaseModel):
    title: str = Field(min_length=3, max_length=255)
    description: str = Field(min_length=5)
    category: str = Field(default="plumber", pattern="^(plumber|electrician)$")
    address_id: UUID


class TicketStatusUpdate(BaseModel):
    status: TicketStatus
    worker_id: UUID | None = None


class TicketRatingCreate(BaseModel):
    value: int = Field(ge=1, le=5)
    comment: str | None = None


class TicketResponse(BaseModel):
    id: UUID
    title: str
    description: str
    category: str
    status: TicketStatus
    resident_id: UUID
    worker_id: UUID | None
    address_id: UUID
    created_at: datetime
    updated_at: datetime
    completed_at: datetime | None
    rating_value: int | None = None

    model_config = {"from_attributes": True}


class NewsCreate(BaseModel):
    title: str = Field(min_length=3, max_length=255)
    content: str = Field(min_length=5)


class NewsResponse(BaseModel):
    id: UUID
    title: str
    content: str
    author_id: UUID
    created_at: datetime
    published_at: datetime

    model_config = {"from_attributes": True}


class NotificationResponse(BaseModel):
    id: UUID
    type: NotificationType
    message: str
    is_read: bool
    ticket_id: UUID | None
    created_at: datetime

    model_config = {"from_attributes": True}


class InternalNotifyRequest(BaseModel):
    recipient_id: UUID
    type: NotificationType
    message: str
    ticket_id: UUID | None = None


class MessageResponse(BaseModel):
    message: str
