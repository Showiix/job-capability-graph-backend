from decimal import Decimal

import pytest
from sqlalchemy.exc import IntegrityError

from tests.matching_fixtures import (
    make_match_dependencies,
    make_match_result,
    make_match_run,
    make_second_job_role,
)


async def test_valid_match_run_and_result_flush(db_session) -> None:
    context = await make_match_dependencies(db_session)
    run = make_match_run(context)
    db_session.add(run)
    await db_session.flush()
    result = make_match_result(run, context.job_role)
    db_session.add(result)

    await db_session.flush()


async def test_match_run_natural_key_is_unique(db_session) -> None:
    context = await make_match_dependencies(db_session)
    db_session.add(make_match_run(context))
    await db_session.flush()
    db_session.add(make_match_run(context))

    with pytest.raises(IntegrityError):
        await db_session.flush()


@pytest.mark.parametrize(
    "counts",
    [
        {"result_count": -1, "high_count": -1},
        {"medium_count": -1},
        {"low_count": -1},
        {"result_count": 2, "high_count": 1, "medium_count": 0, "low_count": 0},
    ],
)
async def test_match_run_counts_are_consistent(db_session, counts) -> None:
    context = await make_match_dependencies(db_session)
    db_session.add(make_match_run(context, **counts))

    with pytest.raises(IntegrityError):
        await db_session.flush()


async def test_match_run_weight_snapshot_must_be_object(db_session) -> None:
    context = await make_match_dependencies(db_session)
    db_session.add(make_match_run(context, weight_snapshot=[]))

    with pytest.raises(IntegrityError):
        await db_session.flush()


async def test_match_result_job_role_is_unique_per_run(db_session) -> None:
    context = await make_match_dependencies(db_session)
    run = make_match_run(context, result_count=2, high_count=2)
    db_session.add(run)
    await db_session.flush()
    db_session.add(make_match_result(run, context.job_role))
    await db_session.flush()
    db_session.add(make_match_result(run, context.job_role, rank=2))

    with pytest.raises(IntegrityError):
        await db_session.flush()


async def test_match_result_rank_is_unique_per_run(db_session) -> None:
    context = await make_match_dependencies(db_session)
    second_role = await make_second_job_role(db_session, context)
    run = make_match_run(context, result_count=2, high_count=2)
    db_session.add(run)
    await db_session.flush()
    db_session.add(make_match_result(run, context.job_role))
    await db_session.flush()
    db_session.add(make_match_result(run, second_role))

    with pytest.raises(IntegrityError):
        await db_session.flush()


async def test_match_result_rank_must_be_positive(db_session) -> None:
    context = await make_match_dependencies(db_session)
    run = make_match_run(context)
    db_session.add(run)
    await db_session.flush()
    db_session.add(make_match_result(run, context.job_role, rank=0))

    with pytest.raises(IntegrityError):
        await db_session.flush()


@pytest.mark.parametrize("score", [Decimal("-0.01"), Decimal("100.01")])
async def test_match_result_score_must_be_bounded(db_session, score) -> None:
    context = await make_match_dependencies(db_session)
    run = make_match_run(context)
    db_session.add(run)
    await db_session.flush()
    db_session.add(make_match_result(run, context.job_role, total_score=score))

    with pytest.raises(IntegrityError):
        await db_session.flush()


async def test_match_result_level_must_be_known(db_session) -> None:
    context = await make_match_dependencies(db_session)
    run = make_match_run(context)
    db_session.add(run)
    await db_session.flush()
    db_session.add(make_match_result(run, context.job_role, match_level="unknown"))

    with pytest.raises(IntegrityError):
        await db_session.flush()


@pytest.mark.parametrize(
    ("field", "invalid_value"),
    [
        ("dimension_scores", []),
        ("matched_capabilities", {}),
        ("missing_capabilities", {}),
        ("gap_summary", []),
        ("job_role_snapshot", []),
    ],
)
async def test_match_result_json_shapes_are_enforced(
    db_session,
    field,
    invalid_value,
) -> None:
    context = await make_match_dependencies(db_session)
    run = make_match_run(context)
    db_session.add(run)
    await db_session.flush()
    db_session.add(make_match_result(run, context.job_role, **{field: invalid_value}))

    with pytest.raises(IntegrityError):
        await db_session.flush()
