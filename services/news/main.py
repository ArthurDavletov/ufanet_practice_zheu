from uuid import UUID

from fastapi import Depends, FastAPI, Header, HTTPException, status
from sqlalchemy.orm import Session

from shared.cors import setup_cors
from shared.database import get_db
from shared.enums import NotificationType, PermissionCode
from shared.enums import RoleName
from shared.models import News, Role, User
from shared.schemas import NewsCreate, NewsResponse
from shared.session_client import SessionClient, notify_client_post, require_auth, require_permission

app = FastAPI(title="NewsService", version="1.0.0")
setup_cors(app)
session_client = SessionClient()


@app.get("/health")
def health() -> dict:
    return {"service": "news", "status": "ok"}


@app.get("/news", response_model=list[NewsResponse])
def list_news(db: Session = Depends(get_db)) -> list[NewsResponse]:
    items = db.query(News).order_by(News.published_at.desc()).all()
    return [NewsResponse.model_validate(n) for n in items]


@app.post("/news", response_model=NewsResponse, status_code=status.HTTP_201_CREATED)
def create_news(
    data: NewsCreate,
    db: Session = Depends(get_db),
    authorization: str | None = Header(default=None),
) -> NewsResponse:
    token = require_auth(authorization)
    ctx = session_client.validate(token)
    require_permission(ctx, PermissionCode.CREATE_NEWS)

    item = News(title=data.title, content=data.content, author_id=ctx.user_id)
    db.add(item)
    db.commit()
    db.refresh(item)

    residents = (
        db.query(User)
        .join(User.roles)
        .filter(Role.name == RoleName.RESIDENT, User.id != ctx.user_id)
        .all()
    )
    for user in residents:
        notify_client_post(
            user.id,
            NotificationType.NEWS_CREATED.value,
            f"Новая новость: {item.title}",
            None,
        )

    return NewsResponse.model_validate(item)
