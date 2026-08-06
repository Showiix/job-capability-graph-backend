from uuid import uuid4

from sqlalchemy import func, select

from app.catalog.models import Capability, CapabilityAlias, Domain
from app.resumes.service import map_resume_skills


async def add_capability(
    db_session,
    *,
    domain_name: str,
    canonical_name: str,
    status: str = "active",
    alias: str | None = None,
    alias_status: str = "active",
) -> Capability:
    domain = Domain(
        id=uuid4(),
        code=f"domain-{uuid4().hex}",
        name=domain_name,
        status="active",
        sort_order=0,
    )
    capability = Capability(
        id=uuid4(),
        domain_id=domain.id,
        canonical_name=canonical_name,
        skill_type="technical",
        status=status,
        source_type="manual",
    )
    db_session.add(domain)
    await db_session.flush()
    db_session.add(capability)
    await db_session.flush()
    if alias is not None:
        db_session.add(
            CapabilityAlias(
                id=uuid4(),
                capability_id=capability.id,
                alias=alias,
                status=alias_status,
            )
        )
        await db_session.flush()
    return capability


def skill(
    name: str,
    *,
    strength: str = "mention",
    confidence: float = 0.8,
    start: int = 0,
) -> dict:
    return {
        "name": name,
        "proficiency": None,
        "explicit_experience_months": None,
        "evidence_strength": strength,
        "evidence_quote": name,
        "evidence_start": start,
        "evidence_end": start + len(name),
        "confidence": confidence,
    }


async def capability_count(db_session) -> int:
    value = await db_session.scalar(select(func.count()).select_from(Capability))
    return int(value or 0)


async def test_canonical_exact_maps_only_one_active_capability(db_session) -> None:
    capability = await add_capability(
        db_session,
        domain_name="Languages",
        canonical_name="Python",
    )
    before = await capability_count(db_session)

    result = await map_resume_skills(db_session, [skill("Python")])

    assert result.skills[0].capability_id == capability.id
    assert result.skills[0].mapping_method == "canonical_exact"
    assert result.skills[0].mapping_status == "mapped"
    assert await capability_count(db_session) == before


async def test_same_canonical_name_across_domains_stays_unmapped(db_session) -> None:
    await add_capability(
        db_session,
        domain_name="Languages",
        canonical_name="Python",
    )
    await add_capability(
        db_session,
        domain_name="Data Tools",
        canonical_name="Python",
    )
    before = await capability_count(db_session)

    result = await map_resume_skills(db_session, [skill("Python")])

    assert result.skills[0].capability_id is None
    assert result.skills[0].mapping_status == "unmapped"
    assert result.warnings == ["AMBIGUOUS_CAPABILITY_NAME:python"]
    assert await capability_count(db_session) == before


async def test_alias_exact_requires_active_alias_and_active_target(db_session) -> None:
    active = await add_capability(
        db_session,
        domain_name="Active",
        canonical_name="Python Language",
        alias="Py",
    )
    await add_capability(
        db_session,
        domain_name="Deprecated Alias",
        canonical_name="Old Python",
        alias="OldPy",
        alias_status="deprecated",
    )
    await add_capability(
        db_session,
        domain_name="Deprecated Target",
        canonical_name="Legacy Python",
        status="deprecated",
        alias="LegacyPy",
    )
    before = await capability_count(db_session)

    result = await map_resume_skills(
        db_session,
        [skill("Py"), skill("OldPy", start=10), skill("LegacyPy", start=20)],
    )
    by_name = {item.raw_name: item for item in result.skills}

    assert by_name["Py"].capability_id == active.id
    assert by_name["Py"].mapping_method == "alias_exact"
    assert by_name["OldPy"].mapping_status == "unmapped"
    assert by_name["LegacyPy"].mapping_status == "unmapped"
    assert await capability_count(db_session) == before


async def test_unmatched_skill_stays_unmapped(db_session) -> None:
    before = await capability_count(db_session)

    result = await map_resume_skills(db_session, [skill("Rust")])

    assert result.skills[0].raw_name == "Rust"
    assert result.skills[0].capability_id is None
    assert result.skills[0].mapping_method == "unmapped"
    assert await capability_count(db_session) == before


async def test_duplicate_normalized_name_prefers_strength_confidence_position(
    db_session,
) -> None:
    before = await capability_count(db_session)
    values = [
        skill("Python", strength="mention", confidence=0.99, start=0),
        skill(" python ", strength="work", confidence=0.5, start=20),
        skill("ＰＹＴＨＯＮ", strength="work", confidence=0.9, start=30),
        skill("Python", strength="work", confidence=0.9, start=10),
    ]

    result = await map_resume_skills(db_session, values)

    assert len(result.skills) == 1
    assert result.skills[0].evidence_strength == "work"
    assert result.skills[0].confidence == 0.9
    assert result.skills[0].evidence_start == 10
    assert await capability_count(db_session) == before


async def test_different_names_same_capability_keep_one_best_skill(db_session) -> None:
    capability = await add_capability(
        db_session,
        domain_name="Languages",
        canonical_name="Python",
        alias="Py",
    )
    before = await capability_count(db_session)

    result = await map_resume_skills(
        db_session,
        [
            skill("Python", strength="mention", confidence=0.99),
            skill("Py", strength="work", confidence=0.8, start=20),
        ],
    )

    assert len(result.skills) == 1
    assert result.skills[0].raw_name == "Py"
    assert result.skills[0].capability_id == capability.id
    assert result.skills[0].mapping_method == "alias_exact"
    assert await capability_count(db_session) == before
