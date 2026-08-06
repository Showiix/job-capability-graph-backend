from decimal import Decimal
from uuid import UUID

from app.discovery.mining import (
    CatalogEntry,
    JobSkillSet,
    build_catalog_index,
    map_skill_labels,
    mine_skill_pairs,
    normalize_skill_label,
)

PYTHON_ID = UUID("00000000-0000-0000-0000-000000000001")
TESTING_ID = UUID("00000000-0000-0000-0000-000000000002")
SQL_ID = UUID("00000000-0000-0000-0000-000000000003")


def _catalog():
    return build_catalog_index(
        [
            CatalogEntry(PYTHON_ID, "Python", ("Py",)),
            CatalogEntry(TESTING_ID, "自动化测试", ("测试自动化",)),
            CatalogEntry(SQL_ID, "SQL", ()),
        ]
    )


def _job(
    number: int,
    source: str,
    company: str | None,
    quality: str,
    *capability_ids: UUID,
) -> JobSkillSet:
    return JobSkillSet(
        normalized_job_id=UUID(f"00000000-0000-0000-0001-{number:012d}"),
        source_code=source,
        company_name=company,
        quality_score=Decimal(quality),
        capability_ids=tuple(capability_ids),
    )


def test_normalize_skill_label_uses_nfkc_casefold_and_whitespace() -> None:
    assert normalize_skill_label("  ＰＹＴＨＯＮ  SDK ") == "python sdk"


def test_canonical_name_wins_before_alias() -> None:
    alias_owner = CatalogEntry(PYTHON_ID, "Python", ("Py",))
    canonical_owner = CatalogEntry(TESTING_ID, "Py", ())

    mapping = map_skill_labels(
        ["Py"],
        build_catalog_index([alias_owner, canonical_owner]),
    )

    assert mapping[0].capability_id == TESTING_ID
    assert mapping[0].mapping_method == "canonical_exact"


def test_only_active_alias_is_mapped() -> None:
    # CatalogEntry receives the active-alias snapshot produced by the DB query.
    mapping = map_skill_labels(["Py", "Python 2"], _catalog())

    assert mapping[0].mapping_status == "mapped"
    assert mapping[0].mapping_method == "alias_exact"
    assert mapping[1].mapping_status == "unmapped"


def test_unmapped_label_is_preserved() -> None:
    mapping = map_skill_labels(["  Agentic ＡＩ  "], _catalog())

    assert mapping[0].raw_name == "  Agentic ＡＩ  "
    assert mapping[0].normalized_name == "agentic ai"
    assert mapping[0].capability_id is None
    assert mapping[0].mapping_method == "unmapped"
    assert mapping[0].mapping_status == "unmapped"


def test_duplicate_tags_map_to_one_capability_per_job() -> None:
    mapping = map_skill_labels(["Python", " python ", "ＰＹＴＨＯＮ"], _catalog())

    assert len(mapping) == 1
    assert mapping[0].capability_id == PYTHON_ID


def test_pair_mining_filters_support_and_source_thresholds() -> None:
    jobs = [
        _job(1, "zhilian", "A", "80", PYTHON_ID, TESTING_ID, SQL_ID),
        _job(2, "zhilian", "B", "90", PYTHON_ID, TESTING_ID),
        _job(3, "liepin", "C", "100", PYTHON_ID, TESTING_ID),
    ]

    candidates = mine_skill_pairs(
        jobs,
        minimum_support_jobs=2,
        minimum_source_count=2,
        maximum_candidates=50,
    )

    assert [candidate.capability_ids for candidate in candidates] == [
        (PYTHON_ID, TESTING_ID)
    ]


def test_pair_scores_match_documented_formula() -> None:
    jobs = [
        _job(1, "zhilian", "A", "80", PYTHON_ID, TESTING_ID),
        _job(2, "zhilian", "B", "100", PYTHON_ID, TESTING_ID),
        _job(3, "liepin", "A", "90", PYTHON_ID, TESTING_ID, SQL_ID),
        _job(4, "liepin", "C", "70", PYTHON_ID, SQL_ID),
    ]

    candidate = mine_skill_pairs(
        jobs,
        minimum_support_jobs=3,
        minimum_source_count=2,
        maximum_candidates=50,
    )[0]

    assert candidate.capability_ids == (PYTHON_ID, TESTING_ID)
    assert candidate.support_job_count == 3
    assert candidate.source_count == 2
    assert candidate.company_count == 2
    assert candidate.support_score == Decimal("0.7500")
    assert candidate.diversity_score == Decimal("0.8333")
    assert candidate.coherence_score == Decimal("0.7500")
    assert candidate.evidence_score == Decimal("0.9000")
    assert candidate.novelty_score == Decimal("0.0000")
    assert candidate.overall_candidate_score == Decimal("0.7967")


def test_pair_sort_is_deterministic_and_respects_maximum() -> None:
    jobs = [
        _job(1, "zhilian", "A", "80", PYTHON_ID, TESTING_ID, SQL_ID),
        _job(2, "liepin", "B", "90", PYTHON_ID, TESTING_ID, SQL_ID),
    ]

    first = mine_skill_pairs(
        jobs,
        minimum_support_jobs=2,
        minimum_source_count=1,
        maximum_candidates=1,
    )
    second = mine_skill_pairs(
        list(reversed(jobs)),
        minimum_support_jobs=2,
        minimum_source_count=1,
        maximum_candidates=1,
    )

    assert first == second
    assert len(first) == 1
