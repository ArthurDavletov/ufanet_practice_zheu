from datetime import datetime, timezone

from sqlalchemy.orm import Session

from shared.enums import PermissionCode, RoleName
from shared.models import Permission, Role, User, UserPermission


ROLE_PERMISSIONS: dict[RoleName, list[PermissionCode]] = {
    RoleName.MINIMAL: [PermissionCode.VIEW_NEWS],
    RoleName.RESIDENT: [
        PermissionCode.VIEW_NEWS,
        PermissionCode.CREATE_TICKET,
        PermissionCode.VIEW_OWN_TICKETS,
    ],
    RoleName.WORKER: [
        PermissionCode.VIEW_TICKETS_BY_ADDRESS,
        PermissionCode.CHANGE_TICKET_STATUS,
    ],
    RoleName.ADMIN: [
        PermissionCode.VIEW_NEWS,
        PermissionCode.CREATE_NEWS,
        PermissionCode.MANAGE_PERMISSIONS,
    ],
}


def collect_user_permissions(db: Session, user: User) -> list[str]:
    codes: set[str] = set()
    for role in user.roles:
        for perm in role.permissions:
            codes.add(perm.code.value)
    now = datetime.now(timezone.utc)
    for up in user.permissions:
        if up.expires_at is None or up.expires_at > now:
            codes.add(up.permission.code.value)
    return sorted(codes)


def collect_user_roles(user: User) -> list[str]:
    return [role.name.value for role in user.roles]


def user_has_permission(db: Session, user: User, permission: PermissionCode) -> bool:
    return permission.value in collect_user_permissions(db, user)


def ensure_roles_and_permissions(db: Session) -> None:
    perm_by_code: dict[PermissionCode, Permission] = {}
    for code in PermissionCode:
        perm = db.query(Permission).filter(Permission.code == code).one_or_none()
        if perm is None:
            perm = Permission(code=code, description=code.value)
            db.add(perm)
            db.flush()
        perm_by_code[code] = perm

    for role_name, perm_codes in ROLE_PERMISSIONS.items():
        role = db.query(Role).filter(Role.name == role_name).one_or_none()
        if role is None:
            role = Role(name=role_name, description=role_name.value)
            db.add(role)
            db.flush()
        role.permissions = [perm_by_code[c] for c in perm_codes]

    db.commit()
