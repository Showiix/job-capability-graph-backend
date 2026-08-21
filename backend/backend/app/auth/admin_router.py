from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Query, Request
from sqlalchemy import asc, desc, func, or_, select

from app.api.dependencies import CSRF, DB, Admin
from app.auth.models import User
from app.auth.schemas import (
    PasswordResetRequest,
    UserCreateRequest,
    UserResponse,
    UserUpdateRequest,
)
from app.auth.service import create_user, reset_password, update_user
from app.core.errors import APIError

router = APIRouter(prefix="/admin/users", tags=["admin-users"])


@router.post("", status_code=201)
async def create(
    payload: UserCreateRequest,
    request: Request,
    db: DB,
    admin: Admin,
    _csrf: CSRF,
) -> dict:
    user = await create_user(
        db,
        admin,
        payload,
        request_id=request.state.request_id,
        ip_address=_client_ip(request),
    )
    return {"data": _user_data(user)}


@router.get("")
async def list_users(
    db: DB,
    _admin: Admin,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    role: Literal["applicant", "hr", "admin"] | None = None,
    is_active: bool | None = None,
    q: str | None = Query(default=None, max_length=100),
    sort: Literal["created_at", "username", "last_login_at"] = "created_at",
    order: Literal["asc", "desc"] = "desc",
) -> dict:
    filters = []
    if role is not None:
        filters.append(User.role == role)
    if is_active is not None:
        filters.append(User.is_active == is_active)
    if q:
        pattern = f"%{q.strip()}%"
        filters.append(
            or_(User.username.ilike(pattern), User.display_name.ilike(pattern))
        )

    total = await db.scalar(select(func.count(User.id)).where(*filters))
    sort_column = {
        "created_at": User.created_at,
        "username": User.username,
        "last_login_at": User.last_login_at,
    }[sort]
    ordering = asc(sort_column) if order == "asc" else desc(sort_column)
    users = (
        await db.scalars(
            select(User)
            .where(*filters)
            .order_by(ordering, User.id)
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
    ).all()
    return {
        "data": {
            "items": [_user_data(user) for user in users],
            "total": int(total or 0),
            "page": page,
            "page_size": page_size,
        }
    }


@router.get("/{user_id}")
async def get_user(user_id: UUID, db: DB, _admin: Admin) -> dict:
    return {"data": _user_data(await _target_user(db, user_id))}


@router.patch("/{user_id}")
async def patch_user(
    user_id: UUID,
    payload: UserUpdateRequest,
    request: Request,
    db: DB,
    admin: Admin,
    _csrf: CSRF,
) -> dict:
    target = await _target_user(db, user_id)
    user = await update_user(
        db,
        admin,
        target,
        payload,
        request_id=request.state.request_id,
        ip_address=_client_ip(request),
    )
    return {"data": _user_data(user)}


@router.post("/{user_id}/reset-password")
async def reset_user_password(
    user_id: UUID,
    payload: PasswordResetRequest,
    request: Request,
    db: DB,
    admin: Admin,
    _csrf: CSRF,
) -> dict:
    target = await _target_user(db, user_id)
    user = await reset_password(
        db,
        admin,
        target,
        payload,
        request_id=request.state.request_id,
        ip_address=_client_ip(request),
    )
    return {"data": _user_data(user)}


async def _target_user(db: DB, user_id: UUID) -> User:
    user = await db.get(User, user_id)
    if user is None:
        raise APIError(404, "USER_NOT_FOUND", "用户不存在")
    return user


def _user_data(user: User) -> dict:
    return UserResponse.model_validate(user).model_dump(mode="json")


def _client_ip(request: Request) -> str | None:
    return request.client.host if request.client else None
