from uuid import UUID

import pytest

from scripts.import_capability_updates import ImportInputError, candidate_rows

ACTOR_ID = UUID("11111111-1111-4111-8111-111111111111")


def test_candidate_rows_normalize_change_and_keep_evidence() -> None:
    rows = candidate_rows(
        {
            "engine": "rule+llm",
            "generated_at": "2026-08-10",
            "jobs": [
                {
                    "job_name": "算法工程师",
                    "change_summary": {"weight_up_count": 1},
                    "changes": [
                        {
                            "skill": "Python",
                            "change_type": "技能权重上升",
                            "effect_size": 0.8,
                            "confidence": "高",
                            "action": "update_edge",
                            "controls": {"noise": {"passed": True}},
                            "evidence": {"jd_count": 3, "samples": []},
                        }
                    ],
                }
            ],
        },
        ACTOR_ID,
    )

    assert len(rows) == 1
    assert rows[0]["change_type"] == "weight_increased"
    assert rows[0]["evidence_summary"] == {"jd_count": 3, "samples": []}
    assert rows[0]["review_status"] == "pending"
    assert (
        rows[0]["id"]
        == candidate_rows(
            {
                "engine": "rule+llm",
                "generated_at": "2026-08-10",
                "jobs": [
                    {
                        "job_name": "算法工程师",
                        "changes": [
                            {
                                "skill": "Python",
                                "change_type": "技能权重上升",
                                "confidence": "高",
                            }
                        ],
                    }
                ],
            },
            ACTOR_ID,
        )[0]["id"]
    )


def test_candidate_rows_reject_unknown_change_type() -> None:
    with pytest.raises(ImportInputError):
        candidate_rows(
            {
                "jobs": [
                    {
                        "job_name": "算法工程师",
                        "changes": [
                            {
                                "skill": "Python",
                                "change_type": "未知",
                                "confidence": "高",
                            }
                        ],
                    }
                ]
            },
            ACTOR_ID,
        )
