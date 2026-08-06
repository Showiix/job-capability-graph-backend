from typing import Annotated

from fastapi import Cookie, Depends, Header
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.models import AuthSession, User
from app.auth.service import resolve_session
from app.core.config import get_settings
from app.core.errors import APIError
from app.core.security import constant_time_equal, token_digest
from app.infrastructure.database import get_db

DB = Annotated[AsyncSession, Depends(get_db)]


async def current_identity(
    db: DB,
    session: Annotated[str | None, Cookie()] = None,
) -> tuple[User, AuthSession]:
    return await resolve_session(db, session)


Identity = Annotated[tuple[User, AuthSession], Depends(current_identity)]


async def require_admin(identity: Identity) -> User:
    user, _ = identity
    if user.role != "admin":
        raise APIError(403, "ROLE_NOT_ALLOWED", "当前角色不能执行此操作")
    return user


Admin = Annotated[User, Depends(require_admin)]


async def require_csrf(
    identity: Identity,
    csrf_header: Annotated[str | None, Header(alias="X-CSRF-Token")] = None,
) -> None:
    _, auth_session = identity
    if not csrf_header:
        raise APIError(403, "CSRF_VALIDATION_FAILED", "CSRF 校验失败")
    digest = token_digest(
        csrf_header,
        get_settings().session_secret.get_secret_value(),
    )
    if not constant_time_equal(digest, auth_session.csrf_token_hash):
        raise APIError(403, "CSRF_VALIDATION_FAILED", "CSRF 校验失败")


CSRF = Annotated[None, Depends(require_csrf)]
