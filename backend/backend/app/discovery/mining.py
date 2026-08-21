import unicodedata
from collections import Counter, defaultdict
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal
from itertools import combinations
from uuid import UUID

FOUR_PLACES = Decimal("0.0001")
ONE = Decimal(1)
HUNDRED = Decimal(100)


@dataclass(frozen=True, slots=True)
class CatalogEntry:
    capability_id: UUID
    canonical_name: str
    aliases: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class CatalogIndex:
    canonical: dict[str, UUID]
    aliases: dict[str, UUID]


@dataclass(frozen=True, slots=True)
class SkillMapping:
    raw_name: str
    normalized_name: str
    capability_id: UUID | None
    mapping_method: str
    mapping_status: str


@dataclass(frozen=True, slots=True)
class JobSkillSet:
    normalized_job_id: UUID
    source_code: str
    company_name: str | None
    quality_score: Decimal
    capability_ids: tuple[UUID, ...]


@dataclass(frozen=True, slots=True)
class PairCandidate:
    capability_ids: tuple[UUID, UUID]
    support_job_ids: tuple[UUID, ...]
    support_job_count: int
    source_count: int
    company_count: int
    support_score: Decimal
    diversity_score: Decimal
    coherence_score: Decimal
    novelty_score: Decimal
    evidence_score: Decimal
    overall_candidate_score: Decimal
    novelty_status: str = "not_evaluated"


def normalize_skill_label(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value).strip().casefold()
    return " ".join(normalized.split())


def build_catalog_index(entries: list[CatalogEntry]) -> CatalogIndex:
    canonical: dict[str, UUID] = {}
    aliases: dict[str, UUID] = {}
    ordered_entries = sorted(entries, key=lambda entry: str(entry.capability_id))

    for entry in ordered_entries:
        normalized = normalize_skill_label(entry.canonical_name)
        if normalized:
            canonical.setdefault(normalized, entry.capability_id)

    for entry in ordered_entries:
        for alias in entry.aliases:
            normalized = normalize_skill_label(alias)
            if normalized and normalized not in canonical:
                aliases.setdefault(normalized, entry.capability_id)

    return CatalogIndex(canonical=canonical, aliases=aliases)


def map_skill_labels(
    labels: list[str],
    catalog: CatalogIndex,
) -> tuple[SkillMapping, ...]:
    mappings: list[SkillMapping] = []
    seen_capabilities: set[UUID] = set()
    seen_unmapped: set[str] = set()

    for raw_name in labels:
        normalized_name = normalize_skill_label(raw_name)
        if not normalized_name:
            continue

        capability_id = catalog.canonical.get(normalized_name)
        mapping_method = "canonical_exact"
        if capability_id is None:
            capability_id = catalog.aliases.get(normalized_name)
            mapping_method = "alias_exact"

        if capability_id is not None:
            if capability_id in seen_capabilities:
                continue
            seen_capabilities.add(capability_id)
            mapping_status = "mapped"
        else:
            if normalized_name in seen_unmapped:
                continue
            seen_unmapped.add(normalized_name)
            mapping_method = "unmapped"
            mapping_status = "unmapped"

        mappings.append(
            SkillMapping(
                raw_name=raw_name,
                normalized_name=normalized_name,
                capability_id=capability_id,
                mapping_method=mapping_method,
                mapping_status=mapping_status,
            )
        )

    return tuple(mappings)


def _rounded(value: Decimal) -> Decimal:
    return min(max(value, Decimal(0)), ONE).quantize(
        FOUR_PLACES,
        rounding=ROUND_HALF_UP,
    )


def mine_skill_pairs(
    jobs: list[JobSkillSet],
    *,
    minimum_support_jobs: int,
    minimum_source_count: int,
    maximum_candidates: int,
) -> tuple[PairCandidate, ...]:
    eligible_jobs = tuple(
        job for job in jobs if len(set(job.capability_ids)) >= 2
    )
    if not eligible_jobs or maximum_candidates < 1:
        return ()

    skill_job_counts: Counter[UUID] = Counter()
    pair_jobs: dict[tuple[UUID, UUID], list[JobSkillSet]] = defaultdict(list)
    for job in sorted(eligible_jobs, key=lambda item: str(item.normalized_job_id)):
        capability_ids = tuple(sorted(set(job.capability_ids), key=str))
        skill_job_counts.update(capability_ids)
        for pair in combinations(capability_ids, 2):
            pair_jobs[pair].append(job)

    eligible_job_count = Decimal(len(eligible_jobs))
    eligible_source_count = Decimal(len({job.source_code for job in eligible_jobs}))
    candidates: list[PairCandidate] = []

    for pair, supporting_jobs in pair_jobs.items():
        support_job_count = len(supporting_jobs)
        sources = {job.source_code for job in supporting_jobs}
        if (
            support_job_count < minimum_support_jobs
            or len(sources) < minimum_source_count
        ):
            continue

        companies = {
            job.company_name for job in supporting_jobs if job.company_name is not None
        }
        support_count = Decimal(support_job_count)
        support_score = _rounded(support_count / eligible_job_count)
        source_diversity = (
            Decimal(len(sources)) / eligible_source_count
            if eligible_source_count
            else Decimal(0)
        )
        company_diversity = Decimal(len(companies)) / support_count
        diversity_score = _rounded(
            (source_diversity + company_diversity) / Decimal(2)
        )
        union_count = (
            skill_job_counts[pair[0]]
            + skill_job_counts[pair[1]]
            - support_job_count
        )
        coherence_score = _rounded(support_count / Decimal(union_count))
        evidence_score = _rounded(
            sum((job.quality_score for job in supporting_jobs), Decimal(0))
            / support_count
            / HUNDRED
        )
        novelty_score = Decimal("0.0000")
        overall_candidate_score = _rounded(
            support_score * Decimal("0.35")
            + diversity_score * Decimal("0.20")
            + coherence_score * Decimal("0.25")
            + evidence_score * Decimal("0.20")
        )
        candidates.append(
            PairCandidate(
                capability_ids=pair,
                support_job_ids=tuple(
                    sorted(
                        (job.normalized_job_id for job in supporting_jobs),
                        key=str,
                    )
                ),
                support_job_count=support_job_count,
                source_count=len(sources),
                company_count=len(companies),
                support_score=support_score,
                diversity_score=diversity_score,
                coherence_score=coherence_score,
                novelty_score=novelty_score,
                evidence_score=evidence_score,
                overall_candidate_score=overall_candidate_score,
            )
        )

    candidates.sort(
        key=lambda candidate: (
            -candidate.overall_candidate_score,
            -candidate.support_job_count,
            tuple(str(value) for value in candidate.capability_ids),
        )
    )
    return tuple(candidates[:maximum_candidates])
