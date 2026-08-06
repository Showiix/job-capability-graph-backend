from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import APIError
from app.graph.models import GraphVersion
from app.graph.schemas import GraphReadData, GraphVersionRead
from app.infrastructure.neo4j import neo4j_driver


async def _current_graph_version(db: AsyncSession) -> GraphVersion:
    version = await db.scalar(
        select(GraphVersion).where(
            GraphVersion.status == "published",
            GraphVersion.is_current.is_(True),
        )
    )
    if version is None:
        raise APIError(
            404,
            "GRAPH_VERSION_NOT_PUBLISHED",
            "当前尚无已发布图谱版本",
        )
    return version


def _version_data(version: GraphVersion) -> GraphVersionRead:
    if version.published_at is None:
        raise APIError(
            503,
            "GRAPH_PROJECTION_INCONSISTENT",
            "正式图谱投影不一致",
        )
    return GraphVersionRead(
        id=version.id,
        version_no=version.version_no,
        published_at=version.published_at,
    )


async def get_global_graph(
    db: AsyncSession,
    *,
    domain_id: UUID | None,
    max_job_roles: int,
    max_capabilities: int,
    driver=neo4j_driver,
) -> GraphReadData:
    version = await _current_graph_version(db)
    return GraphReadData(
        graph_version=_version_data(version),
        nodes=[],
        edges=[],
        truncated=False,
    )
