from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import uuid4

import pytest_asyncio
from sqlalchemy import select

from app.auth.models import User
from app.core.security import hash_password
from app.files.models import StoredFile
from app.imports.models import (
    DataSource,
    ImportBatch,
    NormalizedJobPosting,
    RawJobPosting,
)
from app.processing.models import ProcessingRun


@pytest_asyncio.fixture
async def api_admin(db_session) -> User:
    value = User(
        id=uuid4(),
        username="api_import_admin",
        username_normalized="api_import_admin",
        password_hash=hash_password("api-import-admin-password"),
        display_name="API Import Admin",
        role="admin",
        password_changed_at=datetime.now(UTC),
    )
    db_session.add(value)
    await db_session.flush()
    return value


@pytest_asyncio.fixture
async def api_hr(db_session) -> User:
    value = User(
        id=uuid4(),
        username="api_import_hr",
        username_normalized="api_import_hr",
        password_hash=hash_password("api-import-hr-password"),
        display_name="API Import HR",
        role="hr",
        password_changed_at=datetime.now(UTC),
    )
    db_session.add(value)
    await db_session.flush()
    return value


@pytest_asyncio.fixture
async def processed_import(db_session, api_admin) -> tuple[ImportBatch, ProcessingRun]:
    source = await db_session.scalar(
        select(DataSource).where(DataSource.code == "standard")
    )
    file = StoredFile(
        id=uuid4(),
        uploaded_by_user_id=api_admin.id,
        original_name="jobs.tsv",
        storage_key=f"market-jd/{uuid4()}.tsv",
        media_type="text/tab-separated-values",
        extension="tsv",
        size_bytes=10,
        sha256="e" * 64,
        category="market_jd",
        scan_status="not_required",
        status="attached",
    )
    batch = ImportBatch(
        id=uuid4(),
        source_id=source.id,
        file_id=file.id,
        uploaded_by_user_id=api_admin.id,
        detected_adapter_code="standard_v1",
        adapter_version="1",
        schema_version="standard_v1",
        collected_at=datetime(2026, 8, 6, tzinfo=UTC),
        status="processed",
        total_rows=1,
        accepted_rows=0,
        rejected_rows=0,
        warning_rows=1,
        batch_summary={"adapter_code": "standard_v1"},
    )
    run = ProcessingRun(
        id=uuid4(),
        run_type="import_market_jd",
        subject_type="import_batch",
        subject_id=batch.id,
        created_by_user_id=api_admin.id,
        owner_scope_type="admin_global",
        pipeline_version="standard_v1",
        status="completed",
        result_summary={"total_rows": 1, "warning_rows": 1},
    )
    raw = RawJobPosting(
        id=uuid4(),
        batch_id=batch.id,
        row_number=2,
        source_code="standard",
        job_name="AI Engineer",
        company_name="Example",
        raw_text="Python",
        source_tags=["Python"],
        raw_payload={"job_name": "AI Engineer", "source": "standard"},
        parse_warnings=["missing_issue_date"],
    )
    normalized = NormalizedJobPosting(
        id=uuid4(),
        raw_job_id=raw.id,
        version_no=1,
        normalization_version="jd_normalization_v1",
        normalized_title="AI Engineer",
        company_name="Example",
        city_name="广州",
        quality_score=95,
        quality_flags=["issue_date_missing"],
        is_current=True,
        created_by_run_id=run.id,
    )
    db_session.add_all([file, batch, run])
    await db_session.flush()
    db_session.add(raw)
    await db_session.flush()
    db_session.add(normalized)
    await db_session.flush()
    return batch, run


async def _login(client, username: str, password: str) -> str:
    response = await client.post(
        "/api/v1/auth/login",
        json={"username": username, "password": password},
    )
    assert response.status_code == 200
    return response.json()["data"]["csrf_token"]


async def test_admin_can_list_detail_rows_and_warnings(
    client,
    api_admin,
    processed_import,
) -> None:
    batch, _ = processed_import
    await _login(client, "api_import_admin", "api-import-admin-password")

    listing = await client.get("/api/v1/imports")
    detail = await client.get(f"/api/v1/imports/{batch.id}")
    rows = await client.get(f"/api/v1/imports/{batch.id}/rows")
    expanded = await client.get(
        f"/api/v1/imports/{batch.id}/rows?include=raw_payload,full_text"
    )
    warnings = await client.get(f"/api/v1/imports/{batch.id}/warnings")

    assert listing.status_code == 200
    assert listing.json()["data"][0]["id"] == str(batch.id)
    assert detail.status_code == 200
    assert detail.json()["data"]["warning_rows"] == 1
    assert rows.status_code == 200
    assert "raw_payload" not in rows.json()["data"][0]["raw"]
    assert expanded.json()["data"][0]["raw"]["raw_payload"]["job_name"] == (
        "AI Engineer"
    )
    assert warnings.status_code == 200
    assert warnings.json()["data"]["summary"]["issue_date_missing"] == 1


async def test_import_queries_require_admin(client, api_hr, processed_import) -> None:
    batch, _ = processed_import
    await _login(client, "api_import_hr", "api-import-hr-password")

    response = await client.get(f"/api/v1/imports/{batch.id}")

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "ROLE_NOT_ALLOWED"


async def test_reprocess_creates_new_run_and_enqueue(
    client,
    api_admin,
    processed_import,
    monkeypatch,
    db_session,
) -> None:
    batch, old_run = processed_import
    monkeypatch.setattr(
        "app.imports.service.celery_app.send_task",
        lambda *args, **kwargs: SimpleNamespace(id="reprocess-task"),
    )
    csrf = await _login(client, "api_import_admin", "api-import-admin-password")

    response = await client.post(
        f"/api/v1/imports/{batch.id}/reprocess",
        json={"pipeline_version": "jd_normalization_v2"},
        headers={"X-CSRF-Token": csrf},
    )

    assert response.status_code == 202
    new_run = await db_session.get(ProcessingRun, response.json()["data"]["run_id"])
    assert new_run is not None
    assert new_run.id != old_run.id
    assert new_run.retry_of_run_id == old_run.id
    assert new_run.pipeline_version == "jd_normalization_v2"


async def test_reprocess_rejects_when_run_is_active(
    client,
    api_admin,
    processed_import,
    db_session,
) -> None:
    batch, _ = processed_import
    active = ProcessingRun(
        id=uuid4(),
        run_type="import_market_jd",
        subject_type="import_batch",
        subject_id=batch.id,
        created_by_user_id=api_admin.id,
        owner_scope_type="admin_global",
        pipeline_version="standard_v1",
        status="running",
    )
    db_session.add(active)
    await db_session.flush()
    csrf = await _login(client, "api_import_admin", "api-import-admin-password")

    response = await client.post(
        f"/api/v1/imports/{batch.id}/reprocess",
        headers={"X-CSRF-Token": csrf},
    )

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "PROCESSING_ALREADY_RUNNING"


async def test_archive_is_idempotent(client, api_admin, processed_import) -> None:
    batch, _ = processed_import
    csrf = await _login(client, "api_import_admin", "api-import-admin-password")

    first = await client.post(
        f"/api/v1/imports/{batch.id}/archive",
        headers={"X-CSRF-Token": csrf},
    )
    second = await client.post(
        f"/api/v1/imports/{batch.id}/archive",
        headers={"X-CSRF-Token": csrf},
    )

    assert first.status_code == second.status_code == 200
    assert second.json()["data"]["status"] == "archived"
