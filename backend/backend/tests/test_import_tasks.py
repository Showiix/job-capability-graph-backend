from datetime import UTC, datetime
from hashlib import sha256
from uuid import uuid4

import pytest_asyncio
from sqlalchemy import func, select

from app.auth.models import User
from app.core.security import hash_password
from app.files.models import StoredFile
from app.imports.models import DataSource, ImportBatch, RawJobPosting
from app.infrastructure.file_storage import FileStorage
from app.processing.models import ProcessingError, ProcessingRun


@pytest_asyncio.fixture
async def task_admin(db_session) -> User:
    value = User(
        id=uuid4(),
        username="task_admin",
        username_normalized="task_admin",
        password_hash=hash_password("task-admin-password"),
        display_name="Task Admin",
        role="admin",
        password_changed_at=datetime.now(UTC),
    )
    db_session.add(value)
    await db_session.flush()
    return value


@pytest_asyncio.fixture
async def task_context(db_session, task_admin, tmp_path, monkeypatch):
    from app.imports.tasks import process_market_import

    source = await db_session.scalar(
        select(DataSource).where(DataSource.code == "standard")
    )
    storage = FileStorage(tmp_path / "files")
    content = (
        "job_name\tcompany_name\tsalary\twork_area\tcity\teducation\twork_year\t"
        "issue_date\tsource\tskill_requirements\ttech_tags\tjob_url\n"
        "AI Engineer\tExample\t8-16k\t广州天河\t广州\t本科\t1-3年\t"
        "今日更新\tstandard\tPython\tPython\thttps://example.test/1\n"
        "Data Engineer\tExample\t1.5-3万\t深圳南山\t深圳\t硕士\t3年以上\t"
        "今日更新\tstandard\tSQL\tSQL\thttps://example.test/2\n"
        "ML Engineer\tExample\t25-40k\t杭州\t杭州\t本科\t1-3年\t"
        "今日更新\tstandard\tPyTorch\tPyTorch\thttps://example.test/3\n"
    ).encode()
    file_id = uuid4()
    batch_id = uuid4()
    run_id = uuid4()
    storage_key = f"market-jd/{file_id}.tsv"
    path = storage.resolve(storage_key)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    stored_file = StoredFile(
        id=file_id,
        uploaded_by_user_id=task_admin.id,
        original_name="jobs.tsv",
        storage_key=storage_key,
        media_type="text/tab-separated-values",
        extension="tsv",
        size_bytes=len(content),
        sha256=sha256(content).hexdigest(),
        category="market_jd",
        scan_status="not_required",
        status="attached",
    )
    batch = ImportBatch(
        id=batch_id,
        source_id=source.id,
        file_id=file_id,
        uploaded_by_user_id=task_admin.id,
        collected_at=datetime(2026, 8, 6, tzinfo=UTC),
        status="uploaded",
        batch_summary={},
    )
    run = ProcessingRun(
        id=run_id,
        run_type="import_market_jd",
        subject_type="import_batch",
        subject_id=batch_id,
        created_by_user_id=task_admin.id,
        owner_scope_type="admin_global",
        pipeline_version="standard_v1",
        input_snapshot={"source_code": "standard", "collected_at": "2026-08-06"},
        result_summary={},
    )
    db_session.add_all([stored_file, batch, run])
    await db_session.flush()
    monkeypatch.setattr("app.imports.tasks.storage", storage)
    return process_market_import, run, batch, storage, content


async def test_import_worker_processes_rows_and_is_idempotent(task_context, db_session):
    process_market_import, run, batch, _, _ = task_context

    first = await process_market_import(db_session, run.id)
    second = await process_market_import(db_session, run.id)

    assert first["total_rows"] == second["total_rows"] == 3
    assert batch.status == "processed"
    assert batch.accepted_rows == 3
    assert batch.rejected_rows == 0
    assert await db_session.scalar(
        select(func.count()).select_from(RawJobPosting).where(
            RawJobPosting.batch_id == batch.id
        )
    ) == 3


async def test_missing_job_name_creates_partial_batch_and_error(
    task_context,
    db_session,
):
    process_market_import, run, batch, storage, content = task_context
    broken = content.replace(b"Data Engineer", b"", 1)
    path = storage.resolve(f"market-jd/{batch.file_id}.tsv")
    path.write_bytes(broken)

    await process_market_import(db_session, run.id)

    error = await db_session.scalar(
        select(ProcessingError).where(ProcessingError.run_id == run.id)
    )
    assert batch.status == "partial"
    assert batch.rejected_rows == 1
    assert error is not None
    assert error.error_code == "ROW_MISSING_JOB_NAME"


async def test_cancel_requested_stops_import(task_context, db_session):
    process_market_import, run, batch, _, _ = task_context
    run.cancel_requested = True
    await db_session.flush()

    await process_market_import(db_session, run.id)

    assert run.status == "cancelled"
    assert batch.status == "partial"
    assert batch.total_rows == 3


async def test_row_limit_fails_import(task_context, db_session, monkeypatch):
    process_market_import, run, batch, _, _ = task_context
    monkeypatch.setattr("app.imports.tasks.MAX_IMPORT_ROWS", 2)

    await process_market_import(db_session, run.id)

    error = await db_session.scalar(
        select(ProcessingError).where(ProcessingError.run_id == run.id)
    )
    assert batch.status == "failed"
    assert run.status == "failed"
    assert run.error_code == "IMPORT_ROW_LIMIT_EXCEEDED"
    assert error is not None
    assert error.error_code == "IMPORT_ROW_LIMIT_EXCEEDED"
