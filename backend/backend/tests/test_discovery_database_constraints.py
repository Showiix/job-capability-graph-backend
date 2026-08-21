from datetime import UTC, datetime
from uuid import uuid4

import pytest
from sqlalchemy.exc import IntegrityError

from app.catalog.models import Capability, Domain
from app.discovery.models import (
    CombinationEvidence,
    CombinationSkill,
    DiscoveryRun,
    JobAnalysisProfile,
    JobSkillCandidate,
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


async def _context(db_session, user):
    value = uuid4().hex
    source = DataSource(
        id=uuid4(),
        code=f"source-{value}",
        display_name="Discovery source",
        adapter_code="standard_v1",
        adapter_version="1",
        source_type="file_import",
        config={},
    )
    stored_file = StoredFile(
        id=uuid4(),
        uploaded_by_user_id=user.id,
        original_name="jobs.tsv",
        storage_key=f"discovery/{value}.tsv",
        media_type="text/tab-separated-values",
        extension="tsv",
        size_bytes=10,
        sha256=value * 2,
        category="market_jd",
        scan_status="not_required",
        status="attached",
    )
    batch = ImportBatch(
        id=uuid4(),
        source_id=source.id,
        file_id=stored_file.id,
        uploaded_by_user_id=user.id,
        collected_at=datetime.now(UTC),
        status="processed",
        total_rows=1,
        accepted_rows=1,
        batch_summary={},
    )
    raw_job = RawJobPosting(
        id=uuid4(),
        batch_id=batch.id,
        row_number=1,
        source_code="standard",
        job_name="AI Engineer",
        source_tags=["Python"],
        raw_payload={"job_name": "AI Engineer"},
        parse_warnings=[],
    )
    normalized_job = NormalizedJobPosting(
        id=uuid4(),
        raw_job_id=raw_job.id,
        version_no=1,
        normalization_version="rules_v1",
        normalized_title="AI Engineer",
        quality_score=90,
        quality_flags=[],
        is_current=True,
    )
    processing_run = ProcessingRun(
        id=uuid4(),
        run_type="discovery",
        subject_type="discovery_run",
        subject_id=uuid4(),
        created_by_user_id=user.id,
        owner_scope_type="admin_global",
        pipeline_version="discovery_v1",
        input_snapshot={},
        result_summary={},
    )
    domain = Domain(
        id=uuid4(),
        code=f"domain-{value}",
        name="AI",
        status="active",
        sort_order=0,
    )
    capability = Capability(
        id=uuid4(),
        domain_id=domain.id,
        canonical_name="Python",
        status="active",
        skill_type="language",
        source_type="manual",
    )
    db_session.add(domain)
    await db_session.flush()
    db_session.add(capability)
    await db_session.flush()
    db_session.add_all([source, stored_file, processing_run])
    await db_session.flush()
    db_session.add(batch)
    await db_session.flush()
    db_session.add(raw_job)
    await db_session.flush()
    db_session.add(normalized_job)
    await db_session.flush()
    return {
        "batch": batch,
        "job": normalized_job,
        "run": processing_run,
        "capability": capability,
    }


def _profile(context) -> JobAnalysisProfile:
    return JobAnalysisProfile(
        normalized_job_id=context["job"].id,
        extraction_version="source_tags_v1",
        status="candidate",
        structured_payload={},
        validation_errors=[],
        created_by_run_id=context["run"].id,
    )


def _discovery_run(context, user) -> DiscoveryRun:
    return DiscoveryRun(
        processing_run_id=context["run"].id,
        input_batch_ids=[context["batch"].id],
        algorithm_version="cooccurrence_pairs_v1",
        extraction_version="source_tags_v1",
        parameters={},
        status="running",
        created_by_user_id=user.id,
    )


def _candidate(discovery_run_id) -> SkillCombinationCandidate:
    return SkillCombinationCandidate(
        discovery_run_id=discovery_run_id,
        suggested_name="Python + Testing",
        normalized_name="python + testing",
        definition_payload={},
        support_job_count=2,
        source_count=1,
        company_count=1,
        support_score=0.5,
        diversity_score=0.5,
        coherence_score=0.5,
        novelty_score=0,
        evidence_score=0.5,
        overall_candidate_score=0.5,
        status="candidate",
    )


async def test_profile_version_is_unique_per_job(db_session, user) -> None:
    context = await _context(db_session, user)
    db_session.add(_profile(context))
    await db_session.flush()

    db_session.add(_profile(context))
    with pytest.raises(IntegrityError):
        await db_session.flush()


async def test_mapped_skill_requires_capability(db_session, user) -> None:
    context = await _context(db_session, user)
    profile = _profile(context)
    db_session.add(profile)
    await db_session.flush()

    invalid_mappings = (("mapped", None), ("unmapped", context["capability"].id))
    for mapping_status, capability_id in invalid_mappings:
        with pytest.raises(IntegrityError):
            async with db_session.begin_nested():
                db_session.add(
                    JobSkillCandidate(
                        analysis_profile_id=profile.id,
                        capability_id=capability_id,
                        raw_name="Python",
                        normalized_name=f"python-{mapping_status}",
                        requirement_type="required",
                        importance=1,
                        mapping_method="canonical_exact",
                        mapping_status=mapping_status,
                        extraction_source="algorithm",
                        confidence=1,
                    )
                )
                await db_session.flush()


async def test_candidate_scores_stay_between_zero_and_one(db_session, user) -> None:
    context = await _context(db_session, user)
    discovery_run = _discovery_run(context, user)
    db_session.add(discovery_run)
    await db_session.flush()

    candidate = _candidate(discovery_run.id)
    candidate.overall_candidate_score = 1.1
    db_session.add(candidate)
    with pytest.raises(IntegrityError):
        await db_session.flush()


async def test_candidate_name_is_unique_per_run(db_session, user) -> None:
    context = await _context(db_session, user)
    discovery_run = _discovery_run(context, user)
    db_session.add(discovery_run)
    await db_session.flush()
    db_session.add_all([_candidate(discovery_run.id), _candidate(discovery_run.id)])

    with pytest.raises(IntegrityError):
        await db_session.flush()


async def test_combination_skill_weight_is_bounded(db_session, user) -> None:
    context = await _context(db_session, user)
    discovery_run = _discovery_run(context, user)
    db_session.add(discovery_run)
    await db_session.flush()
    candidate = _candidate(discovery_run.id)
    db_session.add(candidate)
    await db_session.flush()

    db_session.add(
        CombinationSkill(
            candidate_id=candidate.id,
            capability_id=context["capability"].id,
            skill_role="core",
            weight=1.1,
            frequency=0.5,
        )
    )
    with pytest.raises(IntegrityError):
        await db_session.flush()


async def test_evidence_weight_is_bounded(db_session, user) -> None:
    context = await _context(db_session, user)
    discovery_run = _discovery_run(context, user)
    db_session.add(discovery_run)
    await db_session.flush()
    candidate = _candidate(discovery_run.id)
    db_session.add(candidate)
    await db_session.flush()

    db_session.add(
        CombinationEvidence(
            candidate_id=candidate.id,
            normalized_job_id=context["job"].id,
            evidence_weight=1.1,
            representative=True,
        )
    )
    with pytest.raises(IntegrityError):
        await db_session.flush()
