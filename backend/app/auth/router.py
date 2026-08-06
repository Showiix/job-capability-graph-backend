from fastapi import APIRouter, Request, Response

from app.api.dependencies import CSRF, DB, Identity
from app.auth.schemas import AuthUserResponse, LoginRequest
from app.auth.service import (
    ensure_csrf,
    login,
    revoke_all_sessions,
    revoke_session,
)
from app.core.config import get_settings

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/login")
async def login_route(
    payload: LoginRequest,
    request: Request,
    response: Response,
    db: DB,
) -> dict:
    user, session_token, csrf_token = await login(
        db,
        payload.username,
        payload.password,
        request.state.request_id,
        request.client.host if request.client else None,
        request.headers.get("User-Agent"),
    )
    _set_auth_cookies(response, session_token, csrf_token)
    return {"data": _auth_user(user, csrf_token)}


@router.get("/me")
async def me(
    request: Request,
    response: Response,
    db: DB,
    identity: Identity,
) -> dict:
    user, auth_session = identity
    csrf_token = await ensure_csrf(db, auth_session, request.cookies.get("csrf"))
    _set_csrf_cookie(response, csrf_token)
    return {"data": _auth_user(user, csrf_token)}


@router.post("/logout", status_code=204)
async def logout(
    request: Request,
    response: Response,
    db: DB,
    identity: Identity,
    _csrf: CSRF,
) -> None:
    _, auth_session = identity
    await revoke_session(
        db,
        auth_session,
        request_id=request.state.request_id,
        ip_address=request.client.host if request.client else None,
    )
    _clear_auth_cookies(response)


@router.post("/logout-all", status_code=204)
async def logout_all(
    request: Request,
    response: Response,
    db: DB,
    identity: Identity,
    _csrf: CSRF,
) -> None:
    user, _ = identity
    await revoke_all_sessions(
        db,
        user.id,
        request_id=request.state.request_id,
        ip_address=request.client.host if request.client else None,
    )
    _clear_auth_cookies(response)


def _auth_user(user, csrf_token: str) -> dict:
    return AuthUserResponse.model_validate(
        {
            "id": user.id,
            "username": user.username,
            "display_name": user.display_name,
            "role": user.role,
            "is_active": user.is_active,
            "last_login_at": user.last_login_at,
            "created_at": user.created_at,
            "csrf_token": csrf_token,
        }
    ).model_dump(mode="json")


def _set_auth_cookies(
    response: Response,
    session_token: str,
    csrf_token: str,
) -> None:
    settings = get_settings()
    response.set_cookie(
        "session",
        session_token,
        httponly=True,
        secure=settings.secure_cookie,
        samesite="lax",
        max_age=settings.session_ttl_seconds,
        path="/",
    )
    _set_csrf_cookie(response, csrf_token)


def _set_csrf_cookie(response: Response, csrf_token: str) -> None:
    settings = get_settings()
    response.set_cookie(
        "csrf",
        csrf_token,
        httponly=False,
        secure=settings.secure_cookie,
        samesite="lax",
        max_age=settings.session_ttl_seconds,
        path="/",
    )


def _clear_auth_cookies(response: Response) -> None:
    response.delete_cookie("session", path="/")
    response.delete_cookie("csrf", path="/")
