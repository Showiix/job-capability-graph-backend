import argparse
import asyncio
import getpass
import sys
from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.models import User
from app.auth.service import normalize_username
from app.core.security import hash_password
from app.infrastructure.database import SessionFactory


class CLIUserError(Exception):
    exit_code = 2


async def create_cli_user(
    db: AsyncSession,
    *,
    username: str,
    display_name: str,
    role: str,
    password: str,
) -> User:
    username = username.strip()
    display_name = display_name.strip()
    normalized = normalize_username(username)
    if not 3 <= len(normalized) <= 64:
        raise CLIUserError("用户名长度必须为 3–64 个字符")
    if not 1 <= len(display_name) <= 100:
        raise CLIUserError("显示名称长度必须为 1–100 个字符")
    if role not in {"applicant", "hr", "admin"}:
        raise CLIUserError("角色必须为 applicant、hr 或 admin")
    if not 8 <= len(password) <= 128:
        raise CLIUserError("密码长度必须为 8–128 个字符")

    if await db.scalar(select(User.id).where(User.username_normalized == normalized)):
        raise CLIUserError("用户名已存在")
    user_count = await db.scalar(select(func.count(User.id)))
    if not user_count and role != "admin":
        raise CLIUserError("首个用户必须是 admin")

    user = User(
        username=username,
        username_normalized=normalized,
        password_hash=hash_password(password),
        display_name=display_name,
        role=role,
        password_changed_at=datetime.now(UTC),
        created_by_user_id=None,
    )
    db.add(user)
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise CLIUserError("用户名已存在") from None
    return user


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="创建内部系统账号")
    parser.add_argument("--username", required=True)
    parser.add_argument("--display-name", required=True)
    parser.add_argument(
        "--role",
        required=True,
        choices=("applicant", "hr", "admin"),
    )
    return parser


async def _run(args: argparse.Namespace, password: str) -> User:
    async with SessionFactory() as db:
        return await create_cli_user(
            db,
            username=args.username,
            display_name=args.display_name,
            role=args.role,
            password=password,
        )


def main() -> int:
    args = build_parser().parse_args()
    password = getpass.getpass("密码: ")
    confirmation = getpass.getpass("再次输入密码: ")
    if password != confirmation:
        print("两次输入的密码不一致", file=sys.stderr)
        return 2
    try:
        user = asyncio.run(_run(args, password))
    except CLIUserError as error:
        print(str(error), file=sys.stderr)
        return error.exit_code
    print(f"创建用户成功: {user.id}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
