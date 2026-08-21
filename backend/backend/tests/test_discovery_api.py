from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import uuid4

import pytest_asyncio
from sqlalchemy import select

from app.auth.models import User
from app.catalog.models import Capability, Domain
from app.core.security import hash_password
from app.discovery.models import (
    CombinationEvidence,
    CombinationSkill,
    DiscoveryRun,
    SkillCombinationCandidate,
)
from app.files.models import StoredFile
from app.imports.models import (
    DataSource,
    ImportBatch,
    NormalizedJobPosting,
    RawJobPosting,
)
from app.processing.models import ProcessingRun

DISCLAIMER = "该结果是候选技能组合，不代表已经确认的长期市场趋势"


async def _user(db_session, role: str) -> User:
    username = f"discovery_api_{role}"
    user = User(
        id=uuid4(),
        username=username,
        username_normalized=username,
        password_hash=hash_password(f"{role}-password"),
        display_name=f"Discovery {role}",
        role=role,
        password_changed_at=datetime.now(UTC),
    )
    db_session.add(user)
    await db_session.flush()
    return user


@pytest_asyncio.fixture
async def discovery_api_users(db_session):
    return SimpleNamespace(
        admin=await _user(db_session, "admin"),
        hr=await _user(db_session, "hr"),
        applicant=await _user(db_session, "applicant"),
    )


async def _batch(db_session, admin, source, *, status: str) -> ImportBatch:
    file_id = uuid4()
    stored_file = StoredFile(
        id=file_id,
        uploaded_by_user_id=admin.id,
        original_name=f"{status}.tsv",
        storage_key=f"discovery-api/{file_id}.tsv",
        media_type="text/tab-separated-values",
        extension="tsv",
        size_bytes=10,
        sha256=uuid4().hex * 2,
        category="market_jd",
        scan_status="not_required",
        status="attached",
    )
    batch = ImportBatch(
        id=uuid4(),
        source_id=source.id,
        file_id=file_id,
        uploaded_by_user_id=admin.id,
        collected_at=datetime(2026, 8, 6, tzinfo=UTC),
        status=status,
        total_rows=1,
        accepted_rows=1 if status == "processed" else 0,
        batch_summary={},
    )
    db_session.add(stored_file)
    await db_session.flush()
    db_session.add(batch)
    await db_session.flush()
    return batch


@pytest_asyncio.fixture
async def discovery_api_context(db_session, discovery_api_users):
    source = await db_session.scalar(
        select(DataSource).where(DataSource.code == "standard")
    )
    ready_batch = await _batch(
        db_session,
        discovery_api_users.admin,
        source,
        status="processed",
    )
    unready_batch = await _batch(
        db_session,
        discovery_api_users.admin,
        source,
        status="uploaded",
    )
    raw = RawJobPosting(
        id=uuid4(),
        batch_id=ready_batch.id,
        row_number=1,
        source_code="standard",
        source_url="https://example.test/jobs/1",
        job_name="Test Engineer",
        company_name="Example",
        raw_text="secret raw body",
        source_tags=["Python", "自动化测试"],
        raw_payload={"secret": "payload"},
        parse_warnings=[],
    )
    normalized = NormalizedJobPosting(
        id=uuid4(),
        raw_job_id=raw.id,
        version_no=1,
        normalization_version="rules_v1",
        normalized_title="Test Engineer",
        company_name="Example",
        published_at=datetime(2026, 8, 5, tzinfo=UTC).date(),
        normalized_text="secret normalized body",
        quality_score=90,
        quality_flags=[],
        is_current=True,
    )
    db_session.add(raw)
    await db_session.flush()
    db_session.add(normalized)
    await db_session.flush()

    domain = Domain(
        id=uuid4(),
        code="discovery-api",
        name="Discovery API",
        status="active",
        sort_order=0,
    )
    python = Capability(
        id=uuid4(),
        domain_id=domain.id,
        canonical_name="Python",
        status="active",
        skill_type="language",
        source_type="manual",
    )
    testing = Capability(
        id=uuid4(),
        domain_id=domain.id,
        canonical_name="自动化测试",
        status="active",
        skill_type="method",
        source_type="manual",
    )
    db_session.add(domain)
    await db_session.flush()
    db_session.add_all([python, testing])
    await db_session.flush()

    discovery_id = uuid4()
    processing_run = ProcessingRun(
        id=uuid4(),
        run_type="discover_skill_combinations",
        subject_type="discovery_run",
        subject_id=discovery_id,
        created_by_user_id=discovery_api_users.admin.id,
        owner_scope_type="admin_global",
        status="completed",
        pipeline_version="cooccurrence_pairs_v1",
        input_snapshot={"batch_ids": [str(ready_batch.id)]},
        result_summary={"candidate_count": 1},
    )
    discovery_run = DiscoveryRun(
        id=discovery_id,
        processing_run_id=processing_run.id,
        input_batch_ids=[ready_batch.id],
        algorithm_version="cooccurrence_pairs_v1",
        extraction_version="source_tags_v1",
        parameters={},
        status="completed",
        summary={"candidate_count": 1},
        created_by_user_id=discovery_api_users.admin.id,
        completed_at=datetime.now(UTC),
    )
    db_session.add(processing_run)
    await db_session.flush()
    db_session.add(discovery_run)
    await db_session.flush()
    candidate = SkillCombinationCandidate(
        id=uuid4(),
        discovery_run_id=discovery_run.id,
        suggested_name="Python + 自动化测试",
        normalized_name="python + 自动化测试",
        definition_payload={
            "novelty_status": "not_evaluated",
            "disclaimer": DISCLAIMER,
        },
        support_job_count=3,
        source_count=2,
        company_count=3,
        support_score=0.75,
        diversity_score=0.8,
        coherence_score=0.7,
        novelty_score=0,
        evidence_score=0.9,
        overall_candidate_score=0.78,
        status="candidate",
    )
    db_session.add(candidate)
    await db_session.flush()
    db_session.add_all(
        [
            CombinationSkill(
                candidate_id=candidate.id,
                capability_id=capability.id,
                skill_role="core",
                weight=1,
                frequency=1,
            )
            for capability in (python, testing)
        ]
        + [
            CombinationEvidence(
                candidate_id=candidate.id,
                normalized_job_id=normalized.id,
                evidence_weight=0.9,
                representative=True,
            )
        ]
    )
    await db_session.flush()
    return SimpleNamespace(
        ready_batch=ready_batch,
        unready_batch=unready_batch,
        candidate=candidate,
        processing_run=processing_run,
        discovery_run=discovery_run,
    )


async def _login(client, role: str) -> str:
    response = await client.post(
        "/api/v1/auth/login",
        json={
            "username": f"discovery_api_{role}",
            "password": f"{role}-password",
        },
    )
    assert response.status_code == 200
    return response.json()["data"]["csrf_token"]


async def test_admin_creates_discovery_run_and_enqueues(
    client,
    db_session,
    discovery_api_users,
    discovery_api_context,
    monkeypatch,
) -> None:
    sent = []

    def send_task(name, args):
        sent.append((name, args))
        return SimpleNamespace(id="discovery-task-id")

    monkeypatch.setattr("app.worker.celery_app.send_task", send_task)
    csrf = await _login(client, "admin")

    response = await client.post(
        "/api/v1/discovery-runs",
        json={
            "batch_ids": [str(discovery_api_context.ready_batch.id)],
            "minimum_support_jobs": 2,
            "minimum_source_count": 1,
        },
        headers={"X-CSRF-Token": csrf},
    )

    assert response.status_code == 202
    data = response.json()["data"]
    discovery_run = await db_session.get(DiscoveryRun, data["resource_id"])
    processing_run = await db_session.get(ProcessingRun, data["run_id"])
    assert discovery_run is not None
    assert processing_run is not None
    assert processing_run.celery_task_id == "discovery-task-id"
    assert sent == [
        ("app.discover_skill_combinations", [str(processing_run.id)])
    ]


async def test_create_rejects_missing_or_unprocessed_batch(
    client,
    discovery_api_users,
    discovery_api_context,
) -> None:
    csrf = await _login(client, "admin")
    missing = await client.post(
        "/api/v1/discovery-runs",
        json={"batch_ids": [str(uuid4())]},
        headers={"X-CSRF-Token": csrf},
    )
    unready = await client.post(
        "/api/v1/discovery-runs",
        json={"batch_ids": [str(discovery_api_context.unready_batch.id)]},
        headers={"X-CSRF-Token": csrf},
    )

    assert missing.status_code == 404
    assert missing.json()["error"]["code"] == "DISCOVERY_BATCH_NOT_FOUND"
    assert unready.status_code == 409
    assert unready.json()["error"]["code"] == "DISCOVERY_BATCH_NOT_READY"


async def test_create_rejects_source_threshold_above_actual_sources(
    client,
    discovery_api_users,
    discovery_api_context,
) -> None:
    csrf = await _login(client, "admin")

    response = await client.post(
        "/api/v1/discovery-runs",
        json={
            "batch_ids": [str(discovery_api_context.ready_batch.id)],
            "minimum_source_count": 2,
        },
        headers={"X-CSRF-Token": csrf},
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == (
        "DISCOVERY_SOURCE_THRESHOLD_INVALID"
    )


async def test_hr_cannot_create_run(
    client,
    discovery_api_users,
    discovery_api_context,
) -> None:
    csrf = await _login(client, "hr")

    response = await client.post(
        "/api/v1/discovery-runs",
        json={"batch_ids": [str(discovery_api_context.ready_batch.id)]},
        headers={"X-CSRF-Token": csrf},
    )

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "ROLE_NOT_ALLOWED"


async def test_admin_and_hr_can_list_candidates(
    client,
    discovery_api_users,
    discovery_api_context,
) -> None:
    await _login(client, "admin")
    admin_response = await client.get("/api/v1/discovery-candidates")
    await _login(client, "hr")
    hr_response = await client.get("/api/v1/discovery-candidates")

    assert admin_response.status_code == hr_response.status_code == 200
    assert admin_response.json()["data"][0]["id"] == str(
        discovery_api_context.candidate.id
    )
    assert hr_response.json()["data"][0]["id"] == str(
        discovery_api_context.candidate.id
    )


async def test_applicant_cannot_view_candidates(
    client,
    discovery_api_users,
    discovery_api_context,
) -> None:
    await _login(client, "applicant")

    response = await client.get("/api/v1/discovery-candidates")

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "ROLE_NOT_ALLOWED"
    assert discovery_api_context.candidate.suggested_name not in response.text


async def test_candidate_detail_includes_disclaimer_and_skills(
    client,
    discovery_api_users,
    discovery_api_context,
) -> None:
    await _login(client, "hr")

    response = await client.get(
        f"/api/v1/discovery-candidates/{discovery_api_context.candidate.id}"
    )

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["label"] == "候选技能组合"
    assert data["disclaimer"] == DISCLAIMER
    assert data["novelty_status"] == "not_evaluated"
    assert len(data["skills"]) == 2
    assert {skill["canonical_name"] for skill in data["skills"]} == {
        "Python",
        "自动化测试",
    }
    assert data["scores"]["novelty"] == 0


async def test_evidence_hides_raw_payload_and_returns_traceable_fields(
    client,
    discovery_api_users,
    discovery_api_context,
) -> None:
    await _login(client, "hr")

    response = await client.get(
        f"/api/v1/discovery-candidates/{discovery_api_context.candidate.id}/evidence"
    )

    assert response.status_code == 200
    evidence = response.json()["data"][0]
    assert evidence["job_title"] == "Test Engineer"
    assert evidence["company_name"] == "Example"
    assert evidence["source_code"] == "standard"
    assert evidence["source_url"] == "https://example.test/jobs/1"
    assert evidence["published_at"] == "2026-08-05"
    assert evidence["collected_at"] is not None
    assert evidence["quality_score"] == 90
    assert "raw_payload" not in evidence
    assert "raw_text" not in evidence
    assert "normalized_text" not in evidence
