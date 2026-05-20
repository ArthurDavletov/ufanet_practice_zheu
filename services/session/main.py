from uuid import UUID

from fastapi import Depends, FastAPI, HTTPException, status
from sqlalchemy.orm import Session, joinedload

from shared.database import get_db
from shared.enums import PermissionCode
from shared.models import Role, User, UserPermission
from shared.permissions import collect_user_permissions, collect_user_roles
from shared.schemas import CheckPermissionRequest, UserContext, ValidateSessionRequest
from shared.security import decode_access_token

app = FastAPI(title="SessionService", version="1.0.0")


@app.get("/health")
def health() -> dict:
    return {"service": "session", "status": "ok"}


def _load_user(db: Session, user_id: UUID) -> User | None:
    return (
        db.query(User)
        .options(joinedload(User.roles).joinedload(Role.permissions))
        .options(joinedload(User.permissions).joinedload(UserPermission.permission))
        .filter(User.id == user_id)
        .first()
    )


@app.post("/validate", response_model=UserContext)
def validate_session(data: ValidateSessionRequest, db: Session = Depends(get_db)) -> UserContext:
    payload = decode_access_token(data.access_token)
    if payload is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired token")

    user = _load_user(db, UUID(payload["sub"]))
    if user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found")

    return UserContext(
        user_id=user.id,
        login=user.login,
        roles=collect_user_roles(user),
        permissions=collect_user_permissions(db, user),
    )


@app.post("/check-permission")
def check_permission(data: CheckPermissionRequest, db: Session = Depends(get_db)) -> dict:
    payload = decode_access_token(data.access_token)
    if payload is None:
        return {"allowed": False}

    user = _load_user(db, UUID(payload["sub"]))
    if user is None:
        return {"allowed": False}

    permissions = collect_user_permissions(db, user)
    try:
        code = PermissionCode(data.permission)
    except ValueError:
        return {"allowed": False}
    return {"allowed": code.value in permissions}
