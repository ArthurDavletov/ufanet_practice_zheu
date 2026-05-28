from datetime import datetime, timedelta, timezone
from uuid import UUID

from fastapi import Depends, FastAPI, HTTPException, Header, status
from sqlalchemy.orm import Session, joinedload

from shared.database import get_db
from shared.cors import setup_cors
from shared.enums import PermissionCode, RoleName, UserStatus
from shared.models import Address, Permission, Role, User, UserPermission
from shared.permissions import (
    collect_user_permissions,
    collect_user_roles,
    ensure_roles_and_permissions,
    user_has_permission,
)
from shared.schemas import (
    AddressCreate,
    AddressResponse,
    AssignRoleRequest,
    GrantPermissionRequest,
    LoginRequest,
    MessageResponse,
    RefreshRequest,
    RegisterRequest,
    TokenPair,
    UserResponse,
)
from shared.security import (
    create_access_token,
    create_refresh_token,
    decode_access_token,
    hash_password,
    hash_refresh_token,
    verify_password,
)
from shared.models import Session as UserSession
from shared.config import get_settings

app = FastAPI(title="AuthService", version="1.0.0")
setup_cors(app)


BUSINESS_ROLES = {RoleName.RESIDENT, RoleName.WORKER, RoleName.ADMIN}


@app.on_event("startup")
def startup() -> None:
    db = next(get_db())
    try:
        ensure_roles_and_permissions(db)
    finally:
        db.close()


@app.get("/health")
def health() -> dict:
    return {"service": "auth", "status": "ok"}


@app.post("/register", response_model=MessageResponse)
def register(data: RegisterRequest, db: Session = Depends(get_db)) -> MessageResponse:
    if db.query(User).filter((User.login == data.login) | (User.email == data.email)).first():
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Login or email already exists")

    minimal_role = db.query(Role).filter(Role.name == RoleName.MINIMAL).one()
    resident_role = db.query(Role).filter(Role.name == RoleName.RESIDENT).one()
    user = User(
        full_name=data.full_name,
        login=data.login,
        email=data.email,
        password_hash=hash_password(data.password),
        status=UserStatus.ACTIVE,
        roles=[minimal_role, resident_role],
    )
    db.add(user)
    db.commit()
    return MessageResponse(message="ok")


@app.get("/users", response_model=list[UserResponse])
def list_users(
    db: Session = Depends(get_db),
    authorization: str | None = Header(default=None),
) -> list[UserResponse]:
    _admin_from_token(authorization, db)
    users = (
        db.query(User)
        .options(joinedload(User.roles).joinedload(Role.permissions))
        .options(joinedload(User.permissions).joinedload(UserPermission.permission))
        .order_by(User.login)
        .all()
    )
    return [
        UserResponse(
            id=user.id,
            full_name=user.full_name,
            login=user.login,
            email=user.email,
            status=user.status,
            roles=collect_user_roles(user),
            permissions=collect_user_permissions(db, user),
        )
        for user in users
    ]


@app.post("/login", response_model=TokenPair)
def login(data: LoginRequest, db: Session = Depends(get_db)) -> TokenPair:
    user = (
        db.query(User)
        .options(joinedload(User.roles).joinedload(Role.permissions))
        .options(joinedload(User.permissions).joinedload(UserPermission.permission))
        .filter(User.login == data.login)
        .first()
    )
    if user is None or not verify_password(data.password, user.password_hash):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")
    if user.status == UserStatus.BLOCKED:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="User is blocked")

    roles = collect_user_roles(user)
    permissions = collect_user_permissions(db, user)
    access = create_access_token(user.id, user.login, roles, permissions)

    refresh = create_refresh_token()
    settings = get_settings()
    session = UserSession(
        user_id=user.id,
        refresh_token_hash=hash_refresh_token(refresh),
        expires_at=datetime.now(timezone.utc) + timedelta(days=settings.refresh_token_expire_days),
    )
    db.add(session)
    db.commit()
    return TokenPair(access_token=access, refresh_token=refresh)


@app.post("/refresh", response_model=TokenPair)
def refresh(data: RefreshRequest, db: Session = Depends(get_db)) -> TokenPair:
    token_hash = hash_refresh_token(data.refresh_token)
    session = (
        db.query(UserSession)
        .filter(
            UserSession.refresh_token_hash == token_hash,
            UserSession.revoked_at.is_(None),
        )
        .first()
    )
    if session is None or session.expires_at < datetime.now(timezone.utc):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid refresh token")

    user = (
        db.query(User)
        .options(joinedload(User.roles).joinedload(Role.permissions))
        .options(joinedload(User.permissions).joinedload(UserPermission.permission))
        .filter(User.id == session.user_id)
        .first()
    )
    if user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found")

    session.revoked_at = datetime.now(timezone.utc)
    roles = collect_user_roles(user)
    permissions = collect_user_permissions(db, user)
    access = create_access_token(user.id, user.login, roles, permissions)
    new_refresh = create_refresh_token()
    settings = get_settings()
    new_session = UserSession(
        user_id=user.id,
        refresh_token_hash=hash_refresh_token(new_refresh),
        expires_at=datetime.now(timezone.utc) + timedelta(days=settings.refresh_token_expire_days),
    )
    db.add(new_session)
    db.commit()
    return TokenPair(access_token=access, refresh_token=new_refresh)


def _admin_from_token(authorization: str | None, db: Session) -> User:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing token")
    token = authorization.removeprefix("Bearer ").strip()
    payload = decode_access_token(token)
    if payload is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")

    user = (
        db.query(User)
        .options(joinedload(User.roles).joinedload(Role.permissions))
        .options(joinedload(User.permissions).joinedload(UserPermission.permission))
        .filter(User.id == UUID(payload["sub"]))
        .first()
    )
    if user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found")
    if not user_has_permission(db, user, PermissionCode.MANAGE_PERMISSIONS):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin permission required")
    return user


@app.post("/assign-role", response_model=MessageResponse)
def assign_role(
    data: AssignRoleRequest,
    db: Session = Depends(get_db),
    authorization: str | None = Header(default=None),
) -> MessageResponse:
    _admin_from_token(authorization, db)
    user = db.query(User).options(joinedload(User.roles)).filter(User.id == data.user_id).first()
    role = db.query(Role).filter(Role.name == data.role_name).first()
    minimal_role = db.query(Role).filter(Role.name == RoleName.MINIMAL).first()
    if user is None or role is None or minimal_role is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User or role not found")

    if data.role_name == RoleName.MINIMAL:
        user.roles = [minimal_role]
    elif data.role_name in BUSINESS_ROLES:
        user.roles = [minimal_role, role]
    else:
        user.roles = [r for r in user.roles if r.name not in BUSINESS_ROLES]
        if minimal_role not in user.roles:
            user.roles.append(minimal_role)
        if role not in user.roles:
            user.roles.append(role)

    db.commit()
    return MessageResponse(message="ok")


@app.get("/addresses", response_model=list[AddressResponse])
def list_addresses(db: Session = Depends(get_db)) -> list[AddressResponse]:
    items = db.query(Address).order_by(Address.building, Address.apartment).all()
    return [AddressResponse.model_validate(a) for a in items]


@app.post("/addresses", response_model=AddressResponse, status_code=status.HTTP_201_CREATED)
def create_address(
    data: AddressCreate,
    db: Session = Depends(get_db),
    authorization: str | None = Header(default=None),
) -> AddressResponse:
    _admin_from_token(authorization, db)
    address = Address(**data.model_dump())
    db.add(address)
    db.commit()
    db.refresh(address)
    return AddressResponse.model_validate(address)


@app.post("/grant-permission", response_model=MessageResponse)
def grant_permission(
    data: GrantPermissionRequest,
    db: Session = Depends(get_db),
    authorization: str | None = Header(default=None),
) -> MessageResponse:
    _admin_from_token(authorization, db)
    user = db.query(User).filter(User.id == data.user_id).first()
    perm = db.query(Permission).filter(Permission.code == data.permission_code).first()
    if user is None or perm is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User or permission not found")

    db.add(
        UserPermission(
            user_id=user.id,
            permission_id=perm.id,
            address_id=data.address_id,
        )
    )
    db.commit()
    return MessageResponse(message="ok")
