"""
数据模型定义
"""
from enum import Enum
from typing import Optional, Dict, Any, List
from pydantic import BaseModel, Field
from datetime import datetime


class NodeType(str, Enum):
    """节点类型"""
    # 热层节点
    ENTITY = "Entity"           # 实体（主语/宾语）
    ACTION = "Action"           # 动作（谓语）
    TIME = "Time"               # 时间
    LOCATION = "Location"       # 地点
    MESSAGE = "Message"         # 原始消息
    
    # 温层节点
    CONCEPT = "Concept"         # 主题/概念聚类
    
    # 冷层节点
    SUMMARY = "Summary"         # 摘要节点
    SESSION = "Session"         # 会话节点


class RelationType(str, Enum):
    """关系类型"""
    # 热层关系
    SUBJECT_OF = "SUBJECT_OF"       # 主语关系
    ACTION_OF = "ACTION_OF"         # 动作关系
    OBJECT_OF = "OBJECT_OF"         # 宾语关系
    AT_TIME = "AT_TIME"             # 时间关系
    AT_LOCATION = "AT_LOCATION"     # 地点关系
    FROM_MESSAGE = "FROM_MESSAGE"   # 来源于消息
    
    # 温层关系
    BELONGS_TO = "BELONGS_TO"       # 属于某个概念
    SIMILAR_TO = "SIMILAR_TO"       # 相似关系
    
    # 冷层关系
    SUMMARIZES = "SUMMARIZES"       # 摘要关系
    PART_OF_SESSION = "PART_OF_SESSION"  # 属于会话


class FactTuple(BaseModel):
    """五元组模型"""
    subject: str                        # 主语
    predicate: str                      # 谓语
    object_: str = Field(alias="object")  # 宾语
    time: Optional[str] = None          # 时间
    location: Optional[str] = None      # 地点
    confidence: float = 1.0             # 置信度
    source_text: str = ""               # 原始文本
    
    class Config:
        populate_by_name = True


class Neo4jNode(BaseModel):
    """Neo4j 节点模型"""
    id: Optional[str] = None            # Neo4j 节点 ID（自动生成）
    type: NodeType                      # 节点类型
    content: str                        # 节点内容
    properties: Dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=datetime.now)
    layer: int = 0                      # 所在层级 (0=热层, 1=温层, 2=冷层)
    importance: float = 0.5             # 重要性评分
    access_count: int = 0               # 访问次数
    
    class Config:
        json_encoders = {
            datetime: lambda v: v.isoformat()
        }


class Neo4jRelation(BaseModel):
    """Neo4j 关系模型"""
    id: Optional[str] = None
    type: RelationType
    source_id: str                      # 源节点 ID
    target_id: str                      # 目标节点 ID
    properties: Dict[str, Any] = Field(default_factory=dict)
    weight: float = 1.0                 # 关系权重
    created_at: datetime = Field(default_factory=datetime.now)
    
    class Config:
        json_encoders = {
            datetime: lambda v: v.isoformat()
        }


class ExtractionResult(BaseModel):
    """提取结果"""
    tuples: List[FactTuple] = Field(default_factory=list)
    entities: List[str] = Field(default_factory=list)
    time_expressions: List[str] = Field(default_factory=list)
    locations: List[str] = Field(default_factory=list)
    metadata: Dict[str, Any] = Field(default_factory=dict)

