from uuid import UUID

import httpx
from fastapi import HTTPException, status

from shared.config import get_settings
from shared.enums import PermissionCode
from shared.schemas import UserContext


class SessionClient:
    def __init__(self, base_url: str | None = None) -> None:
        settings = get_settings()
        self.base_url = (base_url or settings.session_service_url).rstrip("/")

    def validate(self, access_token: str) -> UserContext:
        try:
            with httpx.Client(timeout=10.0) as client:
                response = client.post(
                    f"{self.base_url}/validate",
                    json={"access_token": access_token},
                )
        except httpx.RequestError as exc:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail=f"SessionService unavailable: {exc}",
            ) from exc

        if response.status_code != 200:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail=response.json().get("detail", "Invalid session"),
            )
        return UserContext(**response.json())

    def check_permission(self, access_token: str, permission: PermissionCode) -> bool:
        try:
            with httpx.Client(timeout=10.0) as client:
                response = client.post(
                    f"{self.base_url}/check-permission",
                    json={"access_token": access_token, "permission": permission.value},
                )
        except httpx.RequestError:
            return False
        if response.status_code != 200:
            return False
        return response.json().get("allowed", False)


def require_auth(authorization: str | None) -> str:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing Bearer token")
    return authorization.removeprefix("Bearer ").strip()


def require_permission(ctx: UserContext, permission: PermissionCode) -> None:
    if permission.value not in ctx.permissions:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Permission required: {permission.value}",
        )


def notify_client_post(
    recipient_id: UUID,
    notify_type: str,
    message: str,
    ticket_id: UUID | None = None,
) -> None:
    settings = get_settings()
    payload = {
        "recipient_id": str(recipient_id),
        "type": notify_type,
        "message": message,
        "ticket_id": str(ticket_id) if ticket_id else None,
    }
    try:
        with httpx.Client(timeout=10.0) as client:
            client.post(f"{settings.notifications_service_url.rstrip('/')}/internal/notify", json=payload)
    except httpx.RequestError:
        pass
