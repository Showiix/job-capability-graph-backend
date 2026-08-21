from uuid import uuid4

from app.catalog.mapping import resolve_capability_labels
from app.catalog.models import Capability, CapabilityAlias, Domain


async def add_capability(
    db_session,
    *,
    canonical_name: str,
    status: str = "active",
    alias: str | None = None,
    alias_status: str = "active",
) -> Capability:
    domain = Domain(
        id=uuid4(),
        code=f"domain-{uuid4().hex}",
        name=f"Domain {uuid4().hex}",
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


async def test_resolve_capability_labels_maps_canonical_alias_and_unknown(
    db_session,
) -> None:
    python = await add_capability(db_session, canonical_name="Python")
    pytorch = await add_capability(
        db_session,
        canonical_name="PyTorch",
        alias="Torch",
    )

    result = await resolve_capability_labels(
        db_session,
        [" Python ", "Torch", "新技能"],
    )

    assert [item.capability_id for item in result.mapped] == [python.id, pytorch.id]
    assert [item.mapping_method for item in result.mapped] == [
        "canonical_exact",
        "alias_exact",
    ]
    assert [item.raw_label for item in result.unmapped] == ["新技能"]
    assert result.warnings == ()


async def test_resolve_capability_labels_ignores_inactive_catalog_entries(
    db_session,
) -> None:
    active = await add_capability(db_session, canonical_name="Python")
    await add_capability(db_session, canonical_name="Rust", status="deprecated")
    await add_capability(
        db_session,
        canonical_name="Legacy Python",
        status="deprecated",
        alias="LegacyPy",
    )
    await add_capability(
        db_session,
        canonical_name="Old Python",
        alias="OldPy",
        alias_status="deprecated",
    )

    result = await resolve_capability_labels(
        db_session,
        ["Python", "Rust", "LegacyPy", "OldPy"],
    )

    assert [item.capability_id for item in result.mapped] == [active.id]
    assert [item.raw_label for item in result.unmapped] == [
        "Rust",
        "LegacyPy",
        "OldPy",
    ]


async def test_resolve_capability_labels_deduplicates_normalized_inputs(
    db_session,
) -> None:
    python = await add_capability(db_session, canonical_name="Python")

    result = await resolve_capability_labels(
        db_session,
        [" Python ", "ＰＹＴＨＯＮ", "Unknown", " unknown "],
    )

    assert [item.capability_id for item in result.mapped] == [python.id]
    assert [item.raw_label for item in result.unmapped] == ["Unknown"]


async def test_resolve_capability_labels_keeps_ambiguous_names_unmapped(
    db_session,
) -> None:
    await add_capability(db_session, canonical_name="Python")
    await add_capability(db_session, canonical_name="PYTHON")
    await add_capability(db_session, canonical_name="First", alias="Torch")
    await add_capability(db_session, canonical_name="Second", alias="Ｔｏｒｃｈ")

    result = await resolve_capability_labels(db_session, ["Python", "Torch"])

    assert [item.raw_label for item in result.unmapped] == ["Python", "Torch"]
    assert result.warnings == (
        "AMBIGUOUS_CAPABILITY_NAME:python",
        "AMBIGUOUS_CAPABILITY_ALIAS:torch",
    )
