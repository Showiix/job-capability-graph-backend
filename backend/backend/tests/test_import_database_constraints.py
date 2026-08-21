from datetime import UTC, datetime
from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.files.models import StoredFile
from app.imports.models import (
    DataSource,
    ImportBatch,
    NormalizedJobPosting,
    RawJobPosting,
)


async def test_initial_data_sources_are_seeded(db_session) -> None:
    codes = set((await db_session.scalars(select(DataSource.code))).all())

    assert {"standard", "liepin", "zhilian", "zhilian_direct"} <= codes


async def _source_and_file(db_session, user) -> tuple[DataSource, StoredFile]:
    value = uuid4().hex
    source = DataSource(
        code=f"source-{value}",
        display_name="Test Source",
        adapter_code="standard_v1",
        adapter_version="1",
        source_type="file_import",
        config={},
    )
    stored_file = StoredFile(
        uploaded_by_user_id=user.id,
        original_name="jobs.tsv",
        storage_key=f"imports/{value}.tsv",
        media_type="text/tab-separated-values",
        extension="tsv",
        size_bytes=10,
        sha256=value * 2,
        category="market_jd",
        scan_status="not_required",
        status="attached",
    )
    db_session.add_all([source, stored_file])
    await db_session.flush()
    return source, stored_file


async def _batch(db_session, user) -> ImportBatch:
    source, stored_file = await _source_and_file(db_session, user)
    batch = ImportBatch(
        source_id=source.id,
        file_id=stored_file.id,
        uploaded_by_user_id=user.id,
        collected_at=datetime.now(UTC),
        status="uploaded",
        batch_summary={},
    )
    db_session.add(batch)
    await db_session.flush()
    return batch


async def _raw_job(db_session, user) -> RawJobPosting:
    batch = await _batch(db_session, user)
    raw = RawJobPosting(
        batch_id=batch.id,
        row_number=1,
        source_code="standard",
        job_name="AI Engineer",
        source_tags=[],
        raw_payload={"job_name": "AI Engineer"},
        parse_warnings=[],
    )
    db_session.add(raw)
    await db_session.flush()
    return raw


async def test_import_batch_counts_must_fit_total(db_session, user) -> None:
    source, stored_file = await _source_and_file(db_session, user)
    db_session.add(
        ImportBatch(
            source_id=source.id,
            file_id=stored_file.id,
            uploaded_by_user_id=user.id,
            collected_at=datetime.now(UTC),
            status="processed",
            total_rows=1,
            accepted_rows=1,
            rejected_rows=1,
            batch_summary={},
        )
    )

    with pytest.raises(IntegrityError):
        await db_session.flush()


async def test_raw_row_number_is_unique_within_batch(db_session, user) -> None:
    batch = await _batch(db_session, user)
    rows = [
        RawJobPosting(
            batch_id=batch.id,
            row_number=1,
            source_code="standard",
            job_name=title,
            source_tags=[],
            raw_payload={"job_name": title},
            parse_warnings=[],
        )
        for title in ("AI Engineer", "Data Engineer")
    ]
    db_session.add_all(rows)

    with pytest.raises(IntegrityError):
        await db_session.flush()


async def test_normalized_version_is_unique_per_raw_job(db_session, user) -> None:
    raw = await _raw_job(db_session, user)
    db_session.add_all(
        [
            NormalizedJobPosting(
                raw_job_id=raw.id,
                version_no=1,
                normalization_version="rules_v1",
                normalized_title=title,
                quality_score=90,
                quality_flags=[],
                is_current=is_current,
            )
            for title, is_current in (
                ("AI Engineer", True),
                ("Data Engineer", False),
            )
        ]
    )

    with pytest.raises(IntegrityError):
        await db_session.flush()


async def test_normalized_quality_score_stays_in_range(db_session, user) -> None:
    raw = await _raw_job(db_session, user)
    db_session.add(
        NormalizedJobPosting(
            raw_job_id=raw.id,
            version_no=1,
            normalization_version="rules_v1",
            normalized_title="AI Engineer",
            quality_score=101,
            quality_flags=[],
            is_current=True,
        )
    )

    with pytest.raises(IntegrityError):
        await db_session.flush()
