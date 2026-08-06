from collections import defaultdict
from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.catalog.models import Capability, CapabilityAlias
from app.discovery.mining import normalize_skill_label
from app.resumes.parsing import skill_rank


@dataclass(frozen=True, slots=True)
class MappedResumeSkill:
    raw_name: str
    normalized_name: str
    capability_id: UUID | None
    proficiency: str | None
    explicit_experience_months: int | None
    evidence_strength: str
    evidence_quote: str
    evidence_start: int
    evidence_end: int
    mapping_method: str
    mapping_status: str
    confidence: float


@dataclass(frozen=True, slots=True)
class SkillMappingResult:
    skills: list[MappedResumeSkill]
    warnings: list[str]


async def map_resume_skills(
    db: AsyncSession,
    skills: list[dict],
) -> SkillMappingResult:
    warnings: list[str] = []
    by_name: dict[str, list[dict]] = defaultdict(list)
    for source in skills:
        normalized_name = normalize_skill_label(source["name"])
        if not normalized_name:
            warnings.append("SKILL_NAME_EMPTY")
            continue
        candidate = dict(source)
        candidate["normalized_name"] = normalized_name
        by_name[normalized_name].append(candidate)

    candidates = [
        max(values, key=skill_rank)
        for _name, values in sorted(by_name.items())
    ]

    # ponytail: full active-catalog scan is acceptable at ~30k rows;
    # add persisted normalized columns and indexes only after profiling shows
    # a bottleneck.
    capabilities = (
        await db.scalars(select(Capability).where(Capability.status == "active"))
    ).all()
    canonical: dict[str, list[Capability]] = defaultdict(list)
    for capability in capabilities:
        normalized = normalize_skill_label(capability.canonical_name)
        if normalized:
            canonical[normalized].append(capability)

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
        normalized = normalize_skill_label(alias.alias)
        if normalized:
            aliases[normalized][capability.id] = capability

    mapped_with_sources: list[tuple[MappedResumeSkill, dict]] = []
    for candidate in candidates:
        normalized_name = candidate["normalized_name"]
        capability = None
        mapping_method = "unmapped"
        canonical_matches = canonical.get(normalized_name, [])
        if len(canonical_matches) == 1:
            capability = canonical_matches[0]
            mapping_method = "canonical_exact"
        elif len(canonical_matches) > 1:
            warnings.append(f"AMBIGUOUS_CAPABILITY_NAME:{normalized_name}")
        else:
            alias_matches = list(aliases.get(normalized_name, {}).values())
            if len(alias_matches) == 1:
                capability = alias_matches[0]
                mapping_method = "alias_exact"
            elif len(alias_matches) > 1:
                warnings.append(f"AMBIGUOUS_CAPABILITY_ALIAS:{normalized_name}")

        mapped = MappedResumeSkill(
            raw_name=candidate["name"],
            normalized_name=normalized_name,
            capability_id=capability.id if capability is not None else None,
            proficiency=candidate["proficiency"],
            explicit_experience_months=candidate["explicit_experience_months"],
            evidence_strength=candidate["evidence_strength"],
            evidence_quote=candidate["evidence_quote"],
            evidence_start=candidate["evidence_start"],
            evidence_end=candidate["evidence_end"],
            mapping_method=mapping_method,
            mapping_status="mapped" if capability is not None else "unmapped",
            confidence=float(candidate["confidence"]),
        )
        mapped_with_sources.append((mapped, candidate))

    selected = [
        pair for pair in mapped_with_sources if pair[0].capability_id is None
    ]
    by_capability: dict[UUID, list[tuple[MappedResumeSkill, dict]]] = defaultdict(list)
    for pair in mapped_with_sources:
        if pair[0].capability_id is not None:
            by_capability[pair[0].capability_id].append(pair)
    selected.extend(
        max(values, key=lambda pair: skill_rank(pair[1]))
        for values in by_capability.values()
    )

    return SkillMappingResult(
        skills=sorted(
            (pair[0] for pair in selected),
            key=lambda item: item.normalized_name,
        ),
        warnings=warnings,
    )
