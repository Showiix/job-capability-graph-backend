from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.growth.models import GrowthPath
from tests.matching_fixtures import (
    make_match_dependencies,
    make_match_result,
    make_match_run,
)


def build_growth_path(run, job_role_id, **overrides) -> GrowthPath:
    values = {
        "id": uuid4(),
        "match_run_id": run.id,
        "job_role_id": job_role_id,
        "prompt_version": "growth_path_v1",
        "source_snapshot": {"match_run": {}, "match_result": {}},
        "path_payload": {"schema_version": "growth_path_v1"},
        "generation_metadata": {"provider_attempts": 1},
    }
    values.update(overrides)
    return GrowthPath(**values)


async def make_persisted_match_result(db_session):
    context = await make_match_dependencies(db_session)
    run = make_match_run(context)
    db_session.add(run)
    await db_session.flush()
    db_session.add(make_match_result(run, context.job_role))
    await db_session.flush()
    return context, run


async def test_valid_growth_path_flushes(db_session) -> None:
    context, run = await make_persisted_match_result(db_session)
    db_session.add(build_growth_path(run, context.job_role.id))

    await db_session.flush()


async def test_growth_path_natural_key_is_unique(db_session) -> None:
    context, run = await make_persisted_match_result(db_session)
    db_session.add(build_growth_path(run, context.job_role.id))
    await db_session.flush()
    db_session.add(build_growth_path(run, context.job_role.id))

    with pytest.raises(IntegrityError):
        await db_session.flush()


async def test_growth_path_requires_composite_match_result(db_session) -> None:
    context = await make_match_dependencies(db_session)
    run = make_match_run(context)
    db_session.add(run)
    await db_session.flush()
    db_session.add(build_growth_path(run, context.job_role.id))

    with pytest.raises(IntegrityError):
        await db_session.flush()


@pytest.mark.parametrize(
    "field",
    ["source_snapshot", "path_payload", "generation_metadata"],
)
async def test_growth_path_json_values_must_be_objects(db_session, field) -> None:
    context, run = await make_persisted_match_result(db_session)
    db_session.add(build_growth_path(run, context.job_role.id, **{field: []}))

    with pytest.raises(IntegrityError):
        await db_session.flush()


async def test_growth_path_cascades_with_match_run(db_session) -> None:
    context, run = await make_persisted_match_result(db_session)
    growth_path = build_growth_path(run, context.job_role.id)
    db_session.add(growth_path)
    await db_session.flush()

    await db_session.delete(run)
    await db_session.flush()

    assert await db_session.scalar(
        select(GrowthPath).where(GrowthPath.id == growth_path.id)
    ) is None
