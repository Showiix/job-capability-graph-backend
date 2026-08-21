from collections import defaultdict
from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.catalog.models import Capability, CapabilityAlias
from app.discovery.mining import normalize_skill_label


@dataclass(frozen=True, slots=True)
class CapabilityResolution:
    raw_label: str
    normalized_label: str
    capability_id: UUID | None
    canonical_name: str | None
    mapping_method: str


@dataclass(frozen=True, slots=True)
class CapabilityResolutionResult:
    resolutions: tuple[CapabilityResolution, ...]
    warnings: tuple[str, ...]

    @property
    def mapped(self) -> tuple[CapabilityResolution, ...]:
        return tuple(
            item for item in self.resolutions if item.capability_id is not None
        )

    @property
    def unmapped(self) -> tuple[CapabilityResolution, ...]:
        return tuple(item for item in self.resolutions if item.capability_id is None)


async def resolve_capability_labels(
    db: AsyncSession,
    labels: list[str],
) -> CapabilityResolutionResult:
    normalized_labels: dict[str, str] = {}
    warnings: list[str] = []
    for raw_label in labels:
        normalized_label = normalize_skill_label(raw_label)
        if not normalized_label:
            warnings.append("CAPABILITY_LABEL_EMPTY")
            continue
        normalized_labels.setdefault(normalized_label, raw_label)

    if not normalized_labels:
        return CapabilityResolutionResult((), tuple(warnings))

    # ponytail: scanning the active catalog is acceptable at the current ~30k
    # rows; add persisted normalized columns only after profiling requires it.
    capabilities = (
        await db.scalars(select(Capability).where(Capability.status == "active"))
    ).all()
    canonical: dict[str, list[Capability]] = defaultdict(list)
    for capability in capabilities:
        normalized_name = normalize_skill_label(capability.canonical_name)
        if normalized_name:
            canonical[normalized_name].append(capability)

    alias_rows = (
        await db.execute(
            select(CapabilityAlias, Capability)
            .join(Capability, Capability.id == CapabilityAlias.capability_id)
            .where(
                CapabilityAlias.status == "active",
                Capability.status == "active",
            )
        )
    ).all()
    aliases: dict[str, dict[UUID, Capability]] = defaultdict(dict)
    for alias, capability in alias_rows:
        normalized_alias = normalize_skill_label(alias.alias)
        if normalized_alias:
            aliases[normalized_alias][capability.id] = capability

    resolutions: list[CapabilityResolution] = []
    for normalized_label, raw_label in normalized_labels.items():
        capability = None
        mapping_method = "unmapped"
        canonical_matches = canonical.get(normalized_label, [])
        if len(canonical_matches) == 1:
            capability = canonical_matches[0]
            mapping_method = "canonical_exact"
        elif len(canonical_matches) > 1:
            warnings.append(f"AMBIGUOUS_CAPABILITY_NAME:{normalized_label}")
        else:
            alias_matches = list(aliases.get(normalized_label, {}).values())
            if len(alias_matches) == 1:
                capability = alias_matches[0]
                mapping_method = "alias_exact"
            elif len(alias_matches) > 1:
                warnings.append(f"AMBIGUOUS_CAPABILITY_ALIAS:{normalized_label}")

        resolutions.append(
            CapabilityResolution(
                raw_label=raw_label,
                normalized_label=normalized_label,
                capability_id=capability.id if capability is not None else None,
                canonical_name=(
                    capability.canonical_name if capability is not None else None
                ),
                mapping_method=mapping_method,
            )
        )

    return CapabilityResolutionResult(tuple(resolutions), tuple(warnings))
