from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field


class GraphVersionCreate(BaseModel):
    proposal_id: UUID


class GraphVersionRead(BaseModel):
    id: UUID
    version_no: int
    published_at: datetime


class GraphNode(BaseModel):
    id: UUID
    type: Literal["domain", "job_role", "capability"]
    name: str
    properties: dict[str, Any] = Field(default_factory=dict)


class GraphEdge(BaseModel):
    id: str
    type: Literal["belongs_to", "requires", "bonus"]
    source: UUID
    target: UUID
    properties: dict[str, Any] = Field(default_factory=dict)


class GraphReadData(BaseModel):
    graph_version: GraphVersionRead
    nodes: list[GraphNode]
    edges: list[GraphEdge]
    truncated: bool
