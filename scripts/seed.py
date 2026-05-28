import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from shared.database import SessionLocal
from shared.enums import RoleName
from shared.models import Address, News, Role, User
from shared.permissions import ensure_roles_and_permissions
from shared.security import hash_password


def main() -> None:
    db = SessionLocal()
    try:
        ensure_roles_and_permissions(db)

        admin_role = db.query(Role).filter(Role.name == RoleName.ADMIN).one()
        worker_role = db.query(Role).filter(Role.name == RoleName.WORKER).one()
        resident_role = db.query(Role).filter(Role.name == RoleName.RESIDENT).one()
        minimal_role = db.query(Role).filter(Role.name == RoleName.MINIMAL).one()

        def upsert_user(login: str, email: str, full_name: str, password: str, roles: list[Role]) -> User:
            user = db.query(User).filter(User.login == login).first()
            if user:
                user.roles = roles
                return user
            user = User(
                full_name=full_name,
                login=login,
                email=email,
                password_hash=hash_password(password),
                roles=roles,
            )
            db.add(user)
            db.flush()
            return user

        admin = upsert_user(
            "admin",
            "admin@zheu.local",
            "Администратор УК",
            "admin123",
            [minimal_role, admin_role],
        )
        worker = upsert_user(
            "worker",
            "worker@zheu.local",
            "Сантехник Иванов",
            "worker123",
            [minimal_role, worker_role],
        )
        resident = upsert_user(
            "resident",
            "resident@zheu.local",
            "Житель Петров",
            "resident123",
            [minimal_role, resident_role],
        )

        address = db.query(Address).filter(Address.building == "12", Address.apartment == "45").first()
        if not address:
            address = Address(building="12", entrance="2", floor=5, apartment="45", room="кухня")
            db.add(address)
            db.flush()

        if address not in resident.addresses:
            resident.addresses.append(address)

        if not db.query(News).first():
            db.add(
                News(
                    title="Плановое отключение воды",
                    content="25 мая с 10:00 до 14:00 — профилактика. Приносим извинения.",
                    author_id=admin.id,
                )
            )

        db.commit()
    finally:
        db.close()


if __name__ == "__main__":
    main()
