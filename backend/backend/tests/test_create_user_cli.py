import pytest

from app.core.security import verify_password
from scripts.create_user import CLIUserError, create_cli_user


async def test_first_cli_user_must_be_admin(db_session) -> None:
    with pytest.raises(CLIUserError) as error:
        await create_cli_user(
            db_session,
            username="first_hr",
            display_name="首个 HR",
            role="hr",
            password="first-password",
        )

    assert error.value.exit_code == 2


async def test_cli_creates_admin_and_refuses_normalized_duplicate(db_session) -> None:
    user = await create_cli_user(
        db_session,
        username=" Admin ",
        display_name="系统管理员",
        role="admin",
        password="admin-password",
    )

    assert user.username == "Admin"
    assert user.username_normalized == "admin"
    assert user.created_by_user_id is None
    assert user.password_hash != "admin-password"
    assert verify_password("admin-password", user.password_hash)

    with pytest.raises(CLIUserError) as error:
        await create_cli_user(
            db_session,
            username="ADMIN",
            display_name="重复管理员",
            role="admin",
            password="replacement-password",
        )

    assert error.value.exit_code == 2
    assert verify_password("admin-password", user.password_hash)
