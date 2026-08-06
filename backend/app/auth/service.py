from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import func, or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit.service import record_audit
from app.auth.models import AuthSession, LoginAttempt, User
from app.auth.schemas import (
    PasswordResetRequest,
    UserCreateRequest,
    UserUpdateRequest,
)
from app.core.config import get_settings
from app.core.errors import APIError
from app.core.security import hash_password, new_token, token_digest, verify_password

LOGIN_WINDOW = timedelta(minutes=10)
LOGIN_FAILURE_LIMIT = 10
LAST_SEEN_INTERVAL = timedelta(minutes=5)


def normalize_username(username: str) -> str:
    return username.strip().lower()


async def login(
    db: AsyncSession,
    username: str,
    password: str,
    request_id: str,
    ip_address: str | None,
    user_agent: str | None,
) -> tuple[User, str, str]:
    now = datetime.now(UTC)
    normalized = normalize_username(username)
    user = await db.scalar(select(User).where(User.username_normalized == normalized))

    if user is not None and not user.is_active:
        _record_login_attempt(
            db,
            normalized,
            user,
            False,
            "inactive",
            ip_address,
            request_id,
        )
        record_audit(
            db,
            action="auth.login",
            resource_type="user",
            resource_id=user.id,
            actor_user_id=user.id,
            outcome="denied",
            request_id=request_id,
            ip_address=ip_address,
            metadata={"reason": "inactive"},
        )
        await db.commit()
        raise APIError(403, "ACCOUNT_INACTIVE", "账号已停用")

    valid_password = user is not None and verify_password(password, user.password_hash)
    if not valid_password:
        recent_failures = await _recent_failure_count(
            db,
            normalized,
            ip_address,
            now,
        )
        rate_limited = recent_failures >= LOGIN_FAILURE_LIMIT - 1
        failure_code = "rate_limited" if rate_limited else "invalid_credentials"
        _record_login_attempt(
            db,
            normalized,
            user,
            False,
            failure_code,
            ip_address,
            request_id,
        )
        record_audit(
            db,
            action="auth.login",
            resource_type="user",
            resource_id=user.id if user else None,
            actor_user_id=user.id if user else None,
            outcome="denied",
            request_id=request_id,
            ip_address=ip_address,
            metadata={"reason": failure_code},
        )
        await db.commit()
        if rate_limited:
            raise APIError(429, "LOGIN_RATE_LIMITED", "登录失败次数过多，请稍后再试")
        raise APIError(401, "INVALID_CREDENTIALS", "用户名或密码错误")

    settings = get_settings()
    session_token = new_token()
    csrf_token = new_token()
    auth_session = AuthSession(
        user_id=user.id,
        token_hash=token_digest(
            session_token,
            settings.session_secret.get_secret_value(),
        ),
        csrf_token_hash=token_digest(
            csrf_token,
            settings.session_secret.get_secret_value(),
        ),
        expires_at=now + timedelta(seconds=settings.session_ttl_seconds),
        last_seen_at=now,
        ip_address=ip_address,
        user_agent=user_agent[:500] if user_agent else None,
    )
    user.last_login_at = now
    db.add(auth_session)
    _record_login_attempt(
        db,
        normalized,
        user,
        True,
        None,
        ip_address,
        request_id,
    )
    record_audit(
        db,
        action="auth.login",
        resource_type="user",
        resource_id=user.id,
        actor_user_id=user.id,
        outcome="success",
        request_id=request_id,
        ip_address=ip_address,
    )
    await db.commit()
    return user, session_token, csrf_token


async def resolve_session(
    db: AsyncSession,
    token: str | None,
) -> tuple[User, AuthSession]:
    if not token:
        raise APIError(401, "AUTH_REQUIRED", "需要登录")

    settings = get_settings()
    digest = token_digest(token, settings.session_secret.get_secret_value())
    auth_session = await db.scalar(
        select(AuthSession).where(AuthSession.token_hash == digest)
    )
    now = datetime.now(UTC)
    if (
        auth_session is None
        or auth_session.revoked_at is not None
        or auth_session.expires_at <= now
    ):
        raise APIError(401, "SESSION_EXPIRED", "会话已过期")

    user = await db.get(User, auth_session.user_id)
    if user is None or not user.is_active:
        raise APIError(401, "SESSION_EXPIRED", "会话已过期")

    if auth_session.last_seen_at <= now - LAST_SEEN_INTERVAL:
        auth_session.last_seen_at = now
        await db.commit()
    return user, auth_session


async def revoke_session(
    db: AsyncSession,
    auth_session: AuthSession,
    *,
    request_id: str | None = None,
    ip_address: str | None = None,
) -> None:
    if auth_session.revoked_at is None:
        auth_session.revoked_at = datetime.now(UTC)
    record_audit(
        db,
        action="auth.logout",
        resource_type="auth_session",
        resource_id=auth_session.id,
        actor_user_id=auth_session.user_id,
        outcome="success",
        request_id=request_id,
        ip_address=ip_address,
    )
    await db.commit()


async def revoke_all_sessions(
    db: AsyncSession,
    user_id: UUID,
    *,
    request_id: str | None = None,
    ip_address: str | None = None,
) -> None:
    now = datetime.now(UTC)
    await _revoke_active_sessions(db, user_id, now)
    record_audit(
        db,
        action="auth.logout_all",
        resource_type="user",
        resource_id=user_id,
        actor_user_id=user_id,
        outcome="success",
        request_id=request_id,
        ip_address=ip_address,
    )
    await db.commit()


async def create_user(
    db: AsyncSession,
    actor: User,
    payload: UserCreateRequest,
    *,
    request_id: str | None = None,
    ip_address: str | None = None,
) -> User:
    username = payload.username.strip()
    normalized = normalize_username(payload.username)
    if await db.scalar(select(User.id).where(User.username_normalized == normalized)):
        await _record_admin_denial(
            db,
            actor,
            "admin.user.create",
            request_id,
            ip_address,
            "username_exists",
        )
        raise APIError(409, "USERNAME_ALREADY_EXISTS", "用户名已存在")

    now = datetime.now(UTC)
    user = User(
        username=username,
        username_normalized=normalized,
        password_hash=hash_password(payload.initial_password),
        display_name=payload.display_name.strip(),
        role=payload.role,
        password_changed_at=now,
        created_by_user_id=actor.id,
    )
    db.add(user)
    await db.flush()
    record_audit(
        db,
        action="admin.user.create",
        resource_type="user",
        resource_id=user.id,
        actor_user_id=actor.id,
        outcome="success",
        request_id=request_id,
        ip_address=ip_address,
    )
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise APIError(409, "USERNAME_ALREADY_EXISTS", "用户名已存在") from None
    return user


async def update_user(
    db: AsyncSession,
    actor: User,
    target: User,
    payload: UserUpdateRequest,
    *,
    request_id: str | None = None,
    ip_address: str | None = None,
) -> User:
    removes_active_admin = (
        target.role == "admin"
        and target.is_active
        and (payload.role not in (None, "admin") or payload.is_active is False)
    )
    if removes_active_admin:
        active_admin_ids = set(
            (
                await db.scalars(
                    select(User.id)
                    .where(User.role == "admin", User.is_active.is_(True))
                    .with_for_update()
                )
            ).all()
        )
        if not active_admin_ids - {target.id}:
            await _record_admin_denial(
                db,
                actor,
                "admin.user.update",
                request_id,
                ip_address,
                "last_admin",
                target.id,
            )
            raise APIError(409, "LAST_ADMIN_REQUIRED", "系统至少需要一个有效管理员")

    role_changed = payload.role is not None and payload.role != target.role
    deactivated = payload.is_active is False and target.is_active
    if payload.display_name is not None:
        target.display_name = payload.display_name.strip()
    if payload.role is not None:
        target.role = payload.role
    if payload.is_active is not None:
        target.is_active = payload.is_active
    if role_changed or deactivated:
        await _revoke_active_sessions(db, target.id, datetime.now(UTC))

    record_audit(
        db,
        action="admin.user.update",
        resource_type="user",
        resource_id=target.id,
        actor_user_id=actor.id,
        outcome="success",
        request_id=request_id,
        ip_address=ip_address,
        metadata={"fields": sorted(payload.model_fields_set)},
    )
    await db.commit()
    return target


async def reset_password(
    db: AsyncSession,
    actor: User,
    target: User,
    payload: PasswordResetRequest,
    *,
    request_id: str | None = None,
    ip_address: str | None = None,
) -> User:
    now = datetime.now(UTC)
    target.password_hash = hash_password(payload.new_password)
    target.password_changed_at = now
    await _revoke_active_sessions(db, target.id, now)
    record_audit(
        db,
        action="admin.user.reset_password",
        resource_type="user",
        resource_id=target.id,
        actor_user_id=actor.id,
        outcome="success",
        request_id=request_id,
        ip_address=ip_address,
    )
    await db.commit()
    return target


async def ensure_csrf(
    db: AsyncSession,
    auth_session: AuthSession,
    csrf_cookie: str | None,
) -> str:
    settings = get_settings()
    secret = settings.session_secret.get_secret_value()
    if (
        csrf_cookie
        and token_digest(csrf_cookie, secret) == auth_session.csrf_token_hash
    ):
        return csrf_cookie
    csrf_token = new_token()
    auth_session.csrf_token_hash = token_digest(csrf_token, secret)
    await db.commit()
    return csrf_token


async def _recent_failure_count(
    db: AsyncSession,
    username_normalized: str,
    ip_address: str | None,
    now: datetime,
) -> int:
    identity_match = LoginAttempt.username_normalized == username_normalized
    if ip_address:
        identity_match = or_(identity_match, LoginAttempt.ip_address == ip_address)
    count = await db.scalar(
        select(func.count(LoginAttempt.id)).where(
            LoginAttempt.success.is_(False),
            LoginAttempt.created_at >= now - LOGIN_WINDOW,
            identity_match,
        )
    )
    return int(count or 0)


def _record_login_attempt(
    db: AsyncSession,
    username_normalized: str,
    user: User | None,
    success: bool,
    failure_code: str | None,
    ip_address: str | None,
    request_id: str,
) -> None:
    db.add(
        LoginAttempt(
            username_normalized=username_normalized,
            user_id=user.id if user else None,
            success=success,
            failure_code=failure_code,
            ip_address=ip_address,
            request_id=request_id,
        )
    )


async def _revoke_active_sessions(
    db: AsyncSession,
    user_id: UUID,
    revoked_at: datetime,
) -> None:
    await db.execute(
        update(AuthSession)
        .where(AuthSession.user_id == user_id, AuthSession.revoked_at.is_(None))
        .values(revoked_at=revoked_at)
    )


async def _record_admin_denial(
    db: AsyncSession,
    actor: User,
    action: str,
    request_id: str | None,
    ip_address: str | None,
    reason: str,
    resource_id: UUID | None = None,
) -> None:
    record_audit(
        db,
        action=action,
        resource_type="user",
        resource_id=resource_id,
        actor_user_id=actor.id,
        outcome="denied",
        request_id=request_id,
        ip_address=ip_address,
        metadata={"reason": reason},
    )
    await db.commit()
