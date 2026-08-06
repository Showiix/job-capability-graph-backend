from copy import deepcopy
from uuid import uuid4

import pytest

from app.graph.neo4j import (
    GraphPublicationVerificationError,
    publish_job_role_snapshot,
    relation_key,
)


class FakeAsyncDriver:
    def __init__(self, *, result_override: dict | None = None) -> None:
        self.calls: list[tuple[str, dict]] = []
        self.nodes: set[tuple[str, str]] = set()
        self.relationships: set[tuple[str, str]] = set()
        self.result_override = result_override or {}

    async def execute_query(self, query: str, *, parameters_: dict):
        parameters = deepcopy(parameters_)
        self.calls.append((query, parameters))

        role = parameters["job_role"]
        domain = parameters["role_domain"]
        capabilities = parameters["capabilities"]
        self.nodes.add(("JobRole", role["id"]))
        self.nodes.add(("Domain", domain["id"]))
        self.relationships.add(("BELONGS_TO", role["domain_relation_key"]))

        for capability in capabilities:
            self.nodes.add(("Capability", capability["id"]))
            self.nodes.add(("Domain", capability["domain"]["id"]))
            self.relationships.add(("BELONGS_TO", capability["domain_relation_key"]))
            relation_type = capability["requirement_type"].upper()
            self.relationships.add((relation_type, capability["role_relation_key"]))

        record = {
            "job_role_id": role["id"],
            "capability_count": len({item["id"] for item in capabilities}),
            "relation_count": len(capabilities),
            "required_count": sum(
                item["requirement_type"] == "required" for item in capabilities
            ),
            "bonus_count": sum(
                item["requirement_type"] == "bonus" for item in capabilities
            ),
        }
        record.update(self.result_override)
        return [record], None, tuple(record)


@pytest.fixture
def snapshot() -> dict:
    role_domain_id = str(uuid4())
    bonus_domain_id = str(uuid4())
    return {
        "domain": {
            "id": role_domain_id,
            "code": "ai",
            "name": "人工智能",
        },
        "job_role": {
            "id": str(uuid4()),
            "canonical_name": "AI 自动化测试工程师",
            "description": "建设 AI 产品自动化测试体系",
            "status": "active",
        },
        "capabilities": [
            {
                "id": str(uuid4()),
                "canonical_name": "Python",
                "skill_type": "language",
                "status": "active",
                "requirement_type": "required",
                "importance": 1.0,
                "domain": {
                    "id": role_domain_id,
                    "code": "ai",
                    "name": "人工智能",
                },
            },
            {
                "id": str(uuid4()),
                "canonical_name": "自动化测试",
                "skill_type": "method",
                "status": "active",
                "requirement_type": "required",
                "importance": 1.0,
                "domain": {
                    "id": role_domain_id,
                    "code": "ai",
                    "name": "人工智能",
                },
            },
            {
                "id": str(uuid4()),
                "canonical_name": "CI/CD",
                "skill_type": "tool",
                "status": "active",
                "requirement_type": "bonus",
                "importance": 0.5,
                "domain": {
                    "id": bonus_domain_id,
                    "code": "software-engineering",
                    "name": "软件工程",
                },
            },
        ],
    }


def test_relation_key_is_stable() -> None:
    source_id = str(uuid4())
    target_id = str(uuid4())

    first = relation_key("REQUIRES", source_id, target_id)
    second = relation_key("REQUIRES", source_id, target_id)

    assert first == second
    assert len(first) == 64
    assert first != relation_key("BONUS", source_id, target_id)


async def test_publish_snapshot_merges_and_verifies_counts(snapshot) -> None:
    driver = FakeAsyncDriver()

    result = await publish_job_role_snapshot(snapshot, 3, driver=driver)

    assert result.job_role_id == snapshot["job_role"]["id"]
    assert result.capability_count == 3
    assert result.relation_count == 3
    assert result.required_count == 2
    assert result.bonus_count == 1
    query, parameters = driver.calls[0]
    assert "MERGE (role:JobRole" in query
    assert "MERGE (skill:Capability" in query
    assert ":REQUIRES" in query
    assert ":BONUS" in query
    assert parameters["graph_version"] == 3


async def test_publish_snapshot_is_idempotent(snapshot) -> None:
    driver = FakeAsyncDriver()

    first = await publish_job_role_snapshot(snapshot, 3, driver=driver)
    state_after_first = (driver.nodes.copy(), driver.relationships.copy())
    second = await publish_job_role_snapshot(snapshot, 3, driver=driver)

    assert second == first
    assert (driver.nodes, driver.relationships) == state_after_first
    assert len(driver.calls) == 2


async def test_publish_snapshot_rejects_read_back_mismatch(snapshot) -> None:
    driver = FakeAsyncDriver(result_override={"relation_count": 2})

    with pytest.raises(GraphPublicationVerificationError):
        await publish_job_role_snapshot(snapshot, 3, driver=driver)
