from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy.exc import IntegrityError

from app.recruitment.models import RecruitmentCandidate
from tests.recruitment_fixtures import (
    make_candidate_skill,
    make_recruitment_dependencies,
    make_recruitment_match_result,
    make_recruitment_match_run,
)


async def test_valid_recruitment_graph_flushes(db_session) -> None:
    context = await make_recruitment_dependencies(db_session)
    skill = make_candidate_skill(context)
    run = make_recruitment_match_run(context)
    db_session.add_all([skill, run])
    await db_session.flush()
    db_session.add(make_recruitment_match_result(context, run))

    await db_session.flush()


@pytest.mark.parametrize(
    "overrides",
    [
        {"requirements_revision": -1},
        {
            "requirements_revision": 0,
            "confirmed_requirement_sha256": "a" * 64,
        },
        {
            "requirements_revision": 1,
            "confirmed_requirement_sha256": None,
        },
        {
            "requirements_revision": 1,
            "confirmed_requirement_snapshot": {},
        },
    ],
)
async def test_project_confirmation_fields_are_consistent(
    db_session,
    overrides,
) -> None:
    context = await make_recruitment_dependencies(db_session)
    for field, value in overrides.items():
        setattr(context.project, field, value)

    with pytest.raises(IntegrityError):
        await db_session.flush()


@pytest.mark.parametrize(
    "overrides",
    [
        {"jd_source_type": "unknown"},
        {"jd_source_type": None, "jd_file_id": uuid4()},
        {"jd_source_type": "text", "jd_file_id": uuid4()},
        {"jd_source_type": "file", "jd_file_id": None},
        {"jd_parse_status": "unknown"},
        {"jd_draft_payload": []},
    ],
)
async def test_project_jd_fields_are_constrained(db_session, overrides) -> None:
    context = await make_recruitment_dependencies(db_session)
    for field, value in overrides.items():
        setattr(context.project, field, value)

    with pytest.raises(IntegrityError):
        await db_session.flush()


async def test_candidate_file_is_unique_per_candidate(db_session) -> None:
    context = await make_recruitment_dependencies(db_session)
    db_session.add(
        RecruitmentCandidate(
            id=uuid4(),
            project_id=context.project.id,
            file_id=context.candidate.file_id,
            display_name="李四",
            parse_status="uploaded",
            created_by_user_id=context.hr.id,
        )
    )

    with pytest.raises(IntegrityError):
        await db_session.flush()


@pytest.mark.parametrize(
    "overrides",
    [
        {"mapping_status": "mapped", "capability_id": None},
        {"mapping_status": "unmapped", "mapping_method": "canonical_exact"},
        {"evidence_strength": "unknown"},
        {"confidence": Decimal("1.0001")},
        {"evidence_start": 4, "evidence_end": 4},
    ],
)
async def test_candidate_skill_mapping_and_evidence_are_consistent(
    db_session,
    overrides,
) -> None:
    context = await make_recruitment_dependencies(db_session)
    db_session.add(make_candidate_skill(context, **overrides))

    with pytest.raises(IntegrityError):
        await db_session.flush()


async def test_candidate_skill_capability_is_unique_per_profile(db_session) -> None:
    context = await make_recruitment_dependencies(db_session)
    db_session.add(make_candidate_skill(context))
    await db_session.flush()
    db_session.add(
        make_candidate_skill(
            context,
            raw_name="Py",
            normalized_name="py",
            mapping_method="alias_exact",
        )
    )

    with pytest.raises(IntegrityError):
        await db_session.flush()


async def test_match_run_natural_key_is_unique(db_session) -> None:
    context = await make_recruitment_dependencies(db_session)
    db_session.add(make_recruitment_match_run(context))
    await db_session.flush()
    db_session.add(make_recruitment_match_run(context))

    with pytest.raises(IntegrityError):
        await db_session.flush()


@pytest.mark.parametrize(
    "overrides",
    [
        {"requirements_revision": 0},
        {"result_count": 0, "high_count": 0},
        {"result_count": 2, "high_count": 1},
        {"skipped_count": 1, "skipped_candidates": []},
        {"weight_snapshot": []},
        {"requirements_snapshot": []},
        {"skipped_candidates": {}},
    ],
)
async def test_match_run_counts_and_snapshots_are_consistent(
    db_session,
    overrides,
) -> None:
    context = await make_recruitment_dependencies(db_session)
    db_session.add(make_recruitment_match_run(context, **overrides))

    with pytest.raises(IntegrityError):
        await db_session.flush()


@pytest.mark.parametrize(
    "overrides",
    [
        {"rank": 0},
        {"total_score": Decimal("100.01")},
        {"match_level": "unknown"},
        {"dimension_scores": []},
        {"matched_capabilities": {}},
        {"missing_capabilities": {}},
        {"gap_summary": []},
        {"candidate_snapshot": []},
    ],
)
async def test_match_result_fields_are_constrained(db_session, overrides) -> None:
    context = await make_recruitment_dependencies(db_session)
    run = make_recruitment_match_run(context)
    db_session.add(run)
    await db_session.flush()
    db_session.add(make_recruitment_match_result(context, run, **overrides))

    with pytest.raises(IntegrityError):
        await db_session.flush()
