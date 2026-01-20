"""
基于 LLM 的热层信息提取器
从用户和助手的对话中提取结构化信息
"""
import json
import logging
from typing import List, Dict, Any, Optional
from openai import OpenAI
from .models import FactTuple, ExtractionResult

logger = logging.getLogger(__name__)


class LLMExtractor:
    """使用 LLM 提取对话中的结构化信息"""
    
    # 提取 Prompt
    EXTRACTION_PROMPT = """你是一个专业的信息提取助手。请从给定的对话消息中提取结构化信息。

提取规则：
1. 提取所有有意义的事实三元组（主语-谓语-宾语）
2. 识别时间表达（如"今天"、"明天"、"2024年1月"等）
3. 识别地点信息（如"北京"、"公司"、"家里"等）
4. 分析发言者的情绪状态（如：开心、焦虑、平静、困惑等）
5. 识别对话意图（如：询问、陈述、请求、抱怨等）
6. 提取关键实体（人名、组织、产品等）

请以 JSON 格式返回，格式如下：
{
    "facts": [
        {
            "subject": "主语",
            "predicate": "谓语/动作",
            "object": "宾语",
            "time": "时间表达（如有）",
            "location": "地点（如有）",
            "confidence": 0.9
        }
    ],
    "emotion": {
        "primary": "主要情绪",
        "intensity": 0.8,
        "description": "情绪描述"
    },
    "intent": "对话意图",
    "entities": ["实体1", "实体2"],
    "time_expressions": ["今天", "明天"],
    "locations": ["北京", "公司"],
    "keywords": ["关键词1", "关键词2"]
}

消息内容：
角色：{role}
内容：{content}

请直接返回 JSON，不要包含其他说明文字。"""

    def __init__(self, api_key: str, base_url: str, model: str, temperature: float = 0.3):
        """
        初始化提取器
        
        Args:
            api_key: OpenRouter API Key
            base_url: API 基础 URL
            model: 模型名称
            temperature: 温度参数（提取任务建议较低）
        """
        self.client = OpenAI(
            api_key=api_key,
            base_url=base_url
        )
        self.model = model
        self.temperature = temperature
        logger.info(f"LLM 提取器初始化完成，模型: {model}")
    
    def extract(self, role: str, content: str, context: Optional[List[Dict]] = None) -> ExtractionResult:
        """
        从消息中提取结构化信息
        
        Args:
            role: 角色（user/assistant）
            content: 消息内容
            context: 可选的上下文消息列表
            
        Returns:
            ExtractionResult: 提取结果
        """
        try:
            # 构建提取请求
            prompt = self.EXTRACTION_PROMPT.format(role=role, content=content)
            system_prompt = "你是一个专业的信息提取助手，擅长从对话中提取结构化信息。输出必须是严格 JSON。"
            messages = [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": prompt}
            ]
            
            # 如果有上下文，添加到 prompt 中
            if context and len(context) > 0:
                context_str = "\n".join([
                    f"{msg.get('role', 'unknown')}: {msg.get('content', '')}"
                    for msg in context[-3:]  # 只取最近3条
                ])
                messages[1]["content"] = f"对话上下文：\n{context_str}\n\n{prompt}"
            
            def _call(temperature: float, force_json: bool = False):
                params: Dict[str, Any] = {
                    "model": self.model,
                    "messages": messages,
                    "temperature": temperature,
                    "max_tokens": 1000
                }
                # 某些模型/网关支持 response_format 强制 JSON；不支持时会被忽略或报错（会被外层捕获）
                if force_json:
                    params["response_format"] = {"type": "json_object"}
                return self.client.chat.completions.create(**params)
            
            # 第一次尝试
            response = _call(self.temperature, force_json=False)
            result_text = (response.choices[0].message.content or "").strip()
            extracted_data = self._parse_json_response(result_text)
            
            # 如果解析出来几乎为空，做一次强制 JSON 的重试（更低温度）
            is_empty = (
                not extracted_data
                or (not extracted_data.get("facts") and not extracted_data.get("entities")
                    and not extracted_data.get("time_expressions") and not extracted_data.get("locations"))
            )
            if is_empty:
                try:
                    response2 = _call(0.0, force_json=True)
                    result_text2 = (response2.choices[0].message.content or "").strip()
                    extracted_data2 = self._parse_json_response(result_text2)
                    # 只有在第二次更好时才替换
                    if extracted_data2 and (
                        extracted_data2.get("facts") or extracted_data2.get("entities")
                        or extracted_data2.get("time_expressions") or extracted_data2.get("locations")
                    ):
                        extracted_data = extracted_data2
                except Exception as e:
                    logger.warning(f"JSON 强制重试失败（忽略并继续使用第一次结果）: {e}")
            
            result = self._convert_to_extraction_result(extracted_data, content)
            logger.info(f"成功提取 {len(result.tuples)} 个事实，{len(result.entities)} 个实体")
            return result
        
        except Exception as e:
            logger.error(f"LLM 提取失败: {e}")
            return ExtractionResult(metadata={"error": str(e), "source_text": content})
    
    def _parse_json_response(self, response: str) -> Dict[str, Any]:
        """解析 LLM 返回的 JSON"""
        try:
            # 尝试提取 JSON 部分（处理可能的markdown包裹）
            if "```json" in response:
                json_str = response.split("```json")[1].split("```")[0].strip()
            elif "```" in response:
                json_str = response.split("```")[1].split("```")[0].strip()
            else:
                json_str = response.strip()
            
            # 尝试查找 JSON 对象的开始和结束
            if "{" in json_str and "}" in json_str:
                start = json_str.find("{")
                end = json_str.rfind("}") + 1
                json_str = json_str[start:end]
            
            return json.loads(json_str)
        except json.JSONDecodeError as e:
            logger.warning(f"JSON 解析失败: {e}，原始响应: {response[:200]}")
            # 返回默认结构，避免后续处理失败
            return {
                "facts": [],
                "emotion": {"primary": "neutral", "intensity": 0.5},
                "intent": "unknown",
                "entities": [],
                "time_expressions": [],
                "locations": [],
                "keywords": []
            }
    
    def _convert_to_extraction_result(self, data: Dict[str, Any], source_text: str) -> ExtractionResult:
        """将 LLM 返回的数据转换为 ExtractionResult"""
        
        # 转换 facts 为 FactTuple
        tuples = []
        for fact in data.get("facts", []):
            try:
                tuple_obj = FactTuple(
                    subject=fact.get("subject", ""),
                    predicate=fact.get("predicate", ""),
                    object=fact.get("object", ""),
                    time=fact.get("time"),
                    location=fact.get("location"),
                    confidence=fact.get("confidence", 0.8),
                    source_text=source_text
                )
                tuples.append(tuple_obj)
            except Exception as e:
                logger.warning(f"转换事实元组失败: {e}, fact={fact}")
        
        # 构建 metadata
        metadata = {
            "emotion": data.get("emotion", {}),
            "intent": data.get("intent", "unknown"),
            "keywords": data.get("keywords", []),
            "source_text": source_text
        }
        
        return ExtractionResult(
            tuples=tuples,
            entities=data.get("entities", []),
            time_expressions=data.get("time_expressions", []),
            locations=data.get("locations", []),
            metadata=metadata
        )
    
    def batch_extract(self, messages: List[Dict[str, str]]) -> List[ExtractionResult]:
        """
        批量提取多条消息
        
        Args:
            messages: 消息列表 [{"role": "user", "content": "..."}]
            
        Returns:
            提取结果列表
        """
        results = []
        for i, msg in enumerate(messages):
            # 提供前面的消息作为上下文
            context = messages[:i] if i > 0 else None
            result = self.extract(
                role=msg.get("role", "user"),
                content=msg.get("content", ""),
                context=context
            )
            results.append(result)
        
        return results


def create_extractor_from_config(config) -> LLMExtractor:
    """
    从项目配置创建提取器
    
    Args:
        config: PrometheaConfig 实例
        
    Returns:
        LLMExtractor 实例
    """
    return LLMExtractor(
        api_key=config.api.api_key,
        base_url=config.api.base_url,
        model=config.api.model,
        temperature=0.3  # 提取任务使用较低温度
    )


