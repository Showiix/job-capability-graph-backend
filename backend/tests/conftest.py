import os
from datetime import UTC, datetime
from uuid import uuid4

os.environ.setdefault("APP_ENV", "test")
os.environ.setdefault("APP_BASE_URL", "http://test")
os.environ.setdefault(
    "DATABASE_URL",
    "postgresql+asyncpg://job_graph:job_graph_dev@127.0.0.1:5432/job_graph_test",
)
os.environ.setdefault("REDIS_URL", "redis://redis:6379/0")
os.environ.setdefault("NEO4J_URI", "bolt://neo4j:7687")
os.environ.setdefault("NEO4J_USERNAME", "neo4j")
os.environ.setdefault("NEO4J_PASSWORD", "job_graph_dev")
os.environ.setdefault("FILE_STORAGE_ROOT", "/tmp/job-graph-tests")
os.environ.setdefault("SESSION_SECRET", "test-secret-at-least-32-characters")
os.environ.setdefault("CORS_ORIGINS", '["http://localhost:3000"]')
os.environ.setdefault("ALGORITHM_SERVICE_URL", "http://algorithm:8001")

import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from app.infrastructure.database import get_db
from app.main import app


@pytest_asyncio.fixture
async def db_session():
    engine = create_async_engine(os.environ["DATABASE_URL"])
    async with engine.connect() as connection:
        transaction = await connection.begin()
        session = AsyncSession(
            bind=connection,
            expire_on_commit=False,
            join_transaction_mode="create_savepoint",
        )
        yield session
        await session.close()
        await transaction.rollback()
    await engine.dispose()


@pytest_asyncio.fixture
async def user(db_session):
    from app.auth.models import User

    value = User(
        id=uuid4(),
        username="fixture",
        username_normalized="fixture",
        password_hash="hash",
        display_name="Fixture",
        role="applicant",
        password_changed_at=datetime.now(UTC),
    )
    db_session.add(value)
    await db_session.flush()
    return value


@pytest_asyncio.fixture
async def client(db_session):
    async def override_db():
        yield db_session

    app.dependency_overrides[get_db] = override_db
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as http:
        yield http
    app.dependency_overrides.clear()
