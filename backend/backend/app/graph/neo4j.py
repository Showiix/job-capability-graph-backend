from dataclasses import dataclass
from hashlib import sha256

from app.infrastructure.neo4j import neo4j_driver

PUBLISH_JOB_ROLE_QUERY = """
MERGE (roleDomain:Domain {id: $role_domain.id})
SET roleDomain.code = $role_domain.code,
    roleDomain.name = $role_domain.name
MERGE (role:JobRole {id: $job_role.id})
SET role.canonical_name = $job_role.canonical_name,
    role.description = $job_role.description,
    role.status = $job_role.status,
    role.graph_version = $graph_version
MERGE (role)-[roleDomainRelation:BELONGS_TO {
    relation_key: $job_role.domain_relation_key
}]->(roleDomain)
SET roleDomainRelation.graph_version = $graph_version
WITH role
UNWIND $capabilities AS capability
MERGE (capabilityDomain:Domain {id: capability.domain.id})
SET capabilityDomain.code = capability.domain.code,
    capabilityDomain.name = capability.domain.name
MERGE (skill:Capability {id: capability.id})
SET skill.canonical_name = capability.canonical_name,
    skill.skill_type = capability.skill_type,
    skill.status = capability.status,
    skill.graph_version = $graph_version
MERGE (skill)-[skillDomainRelation:BELONGS_TO {
    relation_key: capability.domain_relation_key
}]->(capabilityDomain)
SET skillDomainRelation.graph_version = $graph_version
FOREACH (_ IN CASE WHEN capability.requirement_type = 'required' THEN [1] ELSE [] END |
    MERGE (role)-[requiredRelation:REQUIRES {
        relation_key: capability.role_relation_key
    }]->(skill)
    SET requiredRelation.importance = capability.importance,
        requiredRelation.graph_version = $graph_version
)
FOREACH (_ IN CASE WHEN capability.requirement_type = 'bonus' THEN [1] ELSE [] END |
    MERGE (role)-[bonusRelation:BONUS {
        relation_key: capability.role_relation_key
    }]->(skill)
    SET bonusRelation.importance = capability.importance,
        bonusRelation.graph_version = $graph_version
)
WITH DISTINCT role
OPTIONAL MATCH (role)-[relation]->(skill:Capability)
WHERE type(relation) IN ['REQUIRES', 'BONUS']
RETURN role.id AS job_role_id,
       count(DISTINCT skill) AS capability_count,
       count(DISTINCT relation) AS relation_count,
       count(DISTINCT CASE
           WHEN type(relation) = 'REQUIRES' THEN relation
       END) AS required_count,
       count(DISTINCT CASE
           WHEN type(relation) = 'BONUS' THEN relation
       END) AS bonus_count
"""


class GraphPublicationVerificationError(RuntimeError):
    pass


@dataclass(frozen=True)
class GraphPublishResult:
    job_role_id: str
    capability_count: int
    relation_count: int
    required_count: int
    bonus_count: int


def relation_key(relation_type: str, source_id: str, target_id: str) -> str:
    value = f"{relation_type}:{source_id}:{target_id}"
    return sha256(value.encode()).hexdigest()


async def publish_job_role_snapshot(
    snapshot: dict,
    version_no: int,
    *,
    driver=neo4j_driver,
) -> GraphPublishResult:
    parameters = _publish_parameters(snapshot, version_no)
    records, _, _ = await driver.execute_query(
        PUBLISH_JOB_ROLE_QUERY,
        parameters_=parameters,
    )
    if not records:
        raise GraphPublicationVerificationError("Neo4j did not return publish counts")

    record = records[0]
    result = GraphPublishResult(
        job_role_id=str(record["job_role_id"]),
        capability_count=int(record["capability_count"]),
        relation_count=int(record["relation_count"]),
        required_count=int(record["required_count"]),
        bonus_count=int(record["bonus_count"]),
    )
    _verify_result(parameters, result)
    return result


def _publish_parameters(snapshot: dict, version_no: int) -> dict:
    role_domain = dict(snapshot["domain"])
    job_role = dict(snapshot["job_role"])
    job_role["domain_relation_key"] = relation_key(
        "BELONGS_TO",
        job_role["id"],
        role_domain["id"],
    )

    capabilities = []
    for raw_capability in snapshot["capabilities"]:
        capability = dict(raw_capability)
        capability["domain"] = dict(raw_capability["domain"])
        requirement_type = capability["requirement_type"]
        if requirement_type not in {"required", "bonus"}:
            raise ValueError(f"Unsupported requirement type: {requirement_type}")
        capability["domain_relation_key"] = relation_key(
            "BELONGS_TO",
            capability["id"],
            capability["domain"]["id"],
        )
        capability["role_relation_key"] = relation_key(
            "REQUIRES" if requirement_type == "required" else "BONUS",
            job_role["id"],
            capability["id"],
        )
        capabilities.append(capability)

    return {
        "role_domain": role_domain,
        "job_role": job_role,
        "capabilities": capabilities,
        "graph_version": version_no,
    }


def _verify_result(parameters: dict, result: GraphPublishResult) -> None:
    capabilities = parameters["capabilities"]
    expected_required = sum(
        item["requirement_type"] == "required" for item in capabilities
    )
    expected_bonus = len(capabilities) - expected_required
    expected = (
        parameters["job_role"]["id"],
        len(capabilities),
        len(capabilities),
        expected_required,
        expected_bonus,
    )
    actual = (
        result.job_role_id,
        result.capability_count,
        result.relation_count,
        result.required_count,
        result.bonus_count,
    )
    if actual != expected:
        raise GraphPublicationVerificationError(
            f"Neo4j publish verification failed: expected {expected}, got {actual}"
        )
