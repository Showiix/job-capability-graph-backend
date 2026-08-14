import json
from uuid import uuid4

import pytest
from pydantic import ValidationError
from sqlalchemy import func, select

from app.audit.models import AuditLog
from app.catalog.models import Capability, Domain
from app.reviews.algorithm_import import (
    AlgorithmJobDefinitionFile,
    _publishable_capabilities,
)
from app.reviews.models import GraphChangeCandidate


def test_algorithm_result_contract_accepts_teammate_shape() -> None:
    payload = AlgorithmJobDefinitionFile.model_validate(
        {
            "definitions": [
                {
                    "cluster_id": 1,
                    "岗位名称": "大模型应用工程师",
                    "核心职责": ["建设 RAG 应用"],
                    "必备技能": [{"skill": "Python", "support_pct": 0.8}],
                }
            ]
        }
    )
    assert payload.definitions[0].role_name == "大模型应用工程师"
    assert payload.definitions[0].required_skills[0].support == 0.8

    with pytest.raises(ValidationError):
        AlgorithmJobDefinitionFile.model_validate({"definitions": []})


def test_publishable_capabilities_keep_required_skills_in_one_domain() -> None:
    first_domain = uuid4()
    second_domain = uuid4()
    first = (uuid4(), first_domain, 0.8)
    second = (uuid4(), first_domain, 0.7)
    off_domain = (uuid4(), second_domain, 0.6)

    required, bonus = _publishable_capabilities(
        [first, second, off_domain],
        [first, off_domain],
    )

    assert required == [first, second]
    assert bonus == [off_domain]


async def test_admin_imports_algorithm_job_definitions_idempotently(
    db_session,
    client,
    make_user,
    login,
) -> None:
    admin, password = await make_user(role="admin", username="algorithm_import_admin")
    csrf = await login(admin.username, password)
    domain = Domain(
        id=uuid4(),
        code="algorithm-import",
        name="Algorithm Import",
        status="active",
        sort_order=0,
    )
    python = Capability(
        id=uuid4(),
        domain_id=domain.id,
        canonical_name="Python",
        status="active",
        skill_type="language",
        source_type="manual",
    )
    rag = Capability(
        id=uuid4(),
        domain_id=domain.id,
        canonical_name="RAG",
        status="active",
        skill_type="method",
        source_type="manual",
    )
    docker = Capability(
        id=uuid4(),
        domain_id=domain.id,
        canonical_name="Docker",
        status="active",
        skill_type="tool",
        source_type="manual",
    )
    db_session.add(domain)
    await db_session.flush()
    db_session.add_all([python, rag, docker])
    await db_session.flush()

    payload = {
        "generated_at": "2026-08-11T21:28:31",
        "source": "test-jd-batch",
        "definitions": [
            {
                "cluster_id": 1,
                "岗位名称": "大模型应用工程师",
                "核心职责": ["建设企业级 RAG 应用"],
                "必备技能": [
                    {"skill": "Python", "support_pct_corrected": 0.8},
                    {"skill": "RAG", "support_pct_corrected": 0.6},
                ],
                "加分技能": [
                    {"skill": "Docker", "support_pct_corrected": 0.4},
                    {"skill": "未入库技能", "support_pct_corrected": 0.2},
                ],
                "典型行业应用场景": [{"industry": "企业服务"}],
                "source_traceability": {
                    "total_jds": 20,
                    "effective_jds": 16,
                    "unique_companies": 12,
                },
                "人工优化": {
                    "status": "pending_review",
                    "audit_id": "newjob_001",
                },
                "_audit": [{"rule": "ALIAS-1", "level": "P1"}],
            }
        ],
    }
    content = json.dumps(payload, ensure_ascii=False).encode()
    url = "/api/v1/algorithm-results/job-definitions"
    headers = {"X-CSRF-Token": csrf}

    first = await client.post(
        url,
        headers=headers,
        files={"file": ("new_job_definitions.json", content, "application/json")},
    )
    assert first.status_code == 201
    assert first.json()["data"]["created_count"] == 1
    assert first.json()["data"]["reused_count"] == 0

    proposal = await db_session.scalar(select(GraphChangeCandidate))
    assert proposal is not None
    assert proposal.source_candidate_id is None
    assert proposal.review_status == "pending"
    assert proposal.proposed_payload["role_name"] == "大模型应用工程师"
    assert proposal.proposed_payload["required_capability_ids"] == [
        str(python.id),
        str(rag.id),
    ]
    assert proposal.proposed_payload["bonus_capability_ids"] == [str(docker.id)]
    assert proposal.source_snapshot["unmapped_bonus_skills"] == ["未入库技能"]
    assert proposal.evidence_summary["total_jds"] == 20

    second = await client.post(
        url,
        headers=headers,
        files={"file": ("new_job_definitions.json", content, "application/json")},
    )
    assert second.status_code == 201
    assert second.json()["data"]["created_count"] == 0
    assert second.json()["data"]["reused_count"] == 1
    assert (
        await db_session.scalar(select(func.count()).select_from(GraphChangeCandidate))
        == 1
    )
    assert (
        await db_session.scalar(
            select(func.count())
            .select_from(AuditLog)
            .where(AuditLog.action == "algorithm.job_definitions.import")
        )
        == 1
    )
