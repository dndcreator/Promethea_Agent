"""
"""
from enum import Enum
from typing import Optional, Dict, Any, List
from pydantic import BaseModel, Field
from datetime import datetime


class NodeType(str, Enum):
    """TODO: add docstring."""
    ENTITY = "Entity"
    ACTION = "Action"
    TIME = "Time"               # TODO: comment cleaned
    LOCATION = "Location"
    MESSAGE = "Message"         # Raw message node
    
    CONCEPT = "Concept"         # TODO: comment cleaned
    
    SUMMARY = "Summary"
    SESSION = "Session"
    USER = "User"


class RelationType(str, Enum):
    """TODO: add docstring."""
    SUBJECT_OF = "SUBJECT_OF"
    ACTION_OF = "ACTION_OF"         # TODO: comment cleaned
    OBJECT_OF = "OBJECT_OF"
    AT_TIME = "AT_TIME"             # TODO: comment cleaned
    AT_LOCATION = "AT_LOCATION"
    FROM_MESSAGE = "FROM_MESSAGE"   # Source message relation
    
    BELONGS_TO = "BELONGS_TO"
    SIMILAR_TO = "SIMILAR_TO"       # TODO: comment cleaned
    
    SUMMARIZES = "SUMMARIZES"       # TODO: comment cleaned
    PART_OF_SESSION = "PART_OF_SESSION"
    OWNED_BY = "OWNED_BY"


class FactTuple(BaseModel):
    """TODO: add docstring."""
    
    class Config:
        populate_by_name = True


class Neo4jNode(BaseModel):
    properties: Dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=datetime.now)
    
    class Config:
        json_encoders = {
            datetime: lambda v: v.isoformat()
        }


class Neo4jRelation(BaseModel):
    id: Optional[str] = None
    type: RelationType
    created_at: datetime = Field(default_factory=datetime.now)
    
    class Config:
        json_encoders = {
            datetime: lambda v: v.isoformat()
        }


class ExtractionResult(BaseModel):
    tuples: List[FactTuple] = Field(default_factory=list)
    entities: List[str] = Field(default_factory=list)
    time_expressions: List[str] = Field(default_factory=list)
    locations: List[str] = Field(default_factory=list)
    metadata: Dict[str, Any] = Field(default_factory=dict)
