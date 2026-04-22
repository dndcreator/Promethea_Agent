"""Memory graph data models."""

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


class NodeType(str, Enum):
    ENTITY = "Entity"
    ACTION = "Action"
    TIME = "Time"
    LOCATION = "Location"
    MESSAGE = "Message"
    CONCEPT = "Concept"
    SUMMARY = "Summary"
    SESSION = "Session"
    USER = "User"


class RelationType(str, Enum):
    SUBJECT_OF = "SUBJECT_OF"
    ACTION_OF = "ACTION_OF"
    OBJECT_OF = "OBJECT_OF"
    AT_TIME = "AT_TIME"
    AT_LOCATION = "AT_LOCATION"
    FROM_MESSAGE = "FROM_MESSAGE"
    BELONGS_TO = "BELONGS_TO"
    SIMILAR_TO = "SIMILAR_TO"
    SUMMARIZES = "SUMMARIZES"
    PART_OF_SESSION = "PART_OF_SESSION"
    OWNED_BY = "OWNED_BY"


class FactTuple(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    subject: str
    predicate: str
    object_: str = Field(default="", alias="object")
    time: Optional[str] = None
    location: Optional[str] = None
    confidence: float = 0.8
    source_text: Optional[str] = None


class Neo4jNode(BaseModel):
    model_config = ConfigDict()

    id: Optional[str] = None
    type: NodeType
    content: str
    layer: int = 0
    importance: float = 0.5
    access_count: int = 1
    properties: Dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=_utc_now)


class Neo4jRelation(BaseModel):
    model_config = ConfigDict()

    id: Optional[str] = None
    type: RelationType
    source_id: str
    target_id: str
    weight: float = 1.0
    edge_key: Optional[str] = None
    properties: Dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=_utc_now)


class ExtractionResult(BaseModel):
    tuples: List[FactTuple] = Field(default_factory=list)
    entities: List[str] = Field(default_factory=list)
    time_expressions: List[str] = Field(default_factory=list)
    locations: List[str] = Field(default_factory=list)
    metadata: Dict[str, Any] = Field(default_factory=dict)
