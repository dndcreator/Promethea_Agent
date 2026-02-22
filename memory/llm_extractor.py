"""LLM-based extractor for hot-layer structured facts."""

from __future__ import annotations

import json
import logging
from typing import Any, Dict, List, Optional

from openai import OpenAI

from .api_settings import resolve_memory_api
from .models import ExtractionResult, FactTuple

logger = logging.getLogger(__name__)


class LLMExtractor:
    """Extracts structured information from dialog content via LLM."""

    EXTRACTION_PROMPT = """
You are an information extraction assistant.
Extract structured information from a single chat message.

Rules:
1. Extract meaningful fact triples (subject, predicate, object).
2. Detect time expressions when present.
3. Detect location expressions when present.
4. Infer primary emotion and intent.
5. Extract key entities and keywords.

Return strict JSON only:
{{
  "facts": [
    {{
      "subject": "...",
      "predicate": "...",
      "object": "...",
      "time": "...",
      "location": "...",
      "confidence": 0.9
    }}
  ],
  "emotion": {{"primary": "neutral", "intensity": 0.5, "description": "..."}},
  "intent": "...",
  "entities": ["..."],
  "time_expressions": ["..."],
  "locations": ["..."],
  "keywords": ["..."]
}}

Role: {role}
Content: {content}
"""

    def __init__(self, api_key: str, base_url: str, model: str, temperature: float = 0.3):
        self.client = OpenAI(api_key=api_key, base_url=base_url)
        self.model = model
        self.temperature = temperature
        logger.info("LLMExtractor initialized with model: %s", model)

    def extract(self, role: str, content: str, context: Optional[List[Dict]] = None) -> ExtractionResult:
        """Extract structured information from one message."""
        try:
            prompt = self.EXTRACTION_PROMPT.format(role=role, content=content)
            system_prompt = "Return strict JSON only. Do not output markdown."
            messages = [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": prompt},
            ]

            if context:
                context_str = "\n".join(
                    f"{msg.get('role', 'unknown')}: {msg.get('content', '')}"
                    for msg in context[-3:]
                )
                messages[1]["content"] = f"Context:\n{context_str}\n\n{prompt}"

            def _call(temperature: float, force_json: bool = False):
                params: Dict[str, Any] = {
                    "model": self.model,
                    "messages": messages,
                    "temperature": temperature,
                    "max_tokens": 1000,
                }
                if force_json:
                    params["response_format"] = {"type": "json_object"}
                return self.client.chat.completions.create(**params)

            response = _call(self.temperature, force_json=False)
            result_text = (response.choices[0].message.content or "").strip()
            extracted_data = self._parse_json_response(result_text)

            is_empty = (
                not extracted_data
                or (
                    not extracted_data.get("facts")
                    and not extracted_data.get("entities")
                    and not extracted_data.get("time_expressions")
                    and not extracted_data.get("locations")
                )
            )
            if is_empty:
                try:
                    response2 = _call(0.0, force_json=True)
                    result_text2 = (response2.choices[0].message.content or "").strip()
                    extracted_data2 = self._parse_json_response(result_text2)
                    if extracted_data2 and (
                        extracted_data2.get("facts")
                        or extracted_data2.get("entities")
                        or extracted_data2.get("time_expressions")
                        or extracted_data2.get("locations")
                    ):
                        extracted_data = extracted_data2
                except Exception as e:
                    logger.warning("JSON retry failed, keep first response: %s", e)

            result = self._convert_to_extraction_result(extracted_data, content)
            logger.info(
                "Extracted %d facts and %d entities",
                len(result.tuples),
                len(result.entities),
            )
            return result

        except Exception as e:
            logger.error("LLM extraction failed: %s", e)
            return ExtractionResult(metadata={"error": str(e), "source_text": content})

    def _parse_json_response(self, response: str) -> Dict[str, Any]:
        """Parse JSON from model response with tolerant fallback."""
        try:
            if "```json" in response:
                json_str = response.split("```json", 1)[1].split("```", 1)[0].strip()
            elif "```" in response:
                json_str = response.split("```", 1)[1].split("```", 1)[0].strip()
            else:
                json_str = response.strip()

            if "{" in json_str and "}" in json_str:
                start = json_str.find("{")
                end = json_str.rfind("}") + 1
                json_str = json_str[start:end]

            return json.loads(json_str)
        except json.JSONDecodeError as e:
            logger.warning("JSON parse failed: %s", e)
            return {
                "facts": [],
                "emotion": {"primary": "neutral", "intensity": 0.5},
                "intent": "unknown",
                "entities": [],
                "time_expressions": [],
                "locations": [],
                "keywords": [],
            }

    def _convert_to_extraction_result(self, data: Dict[str, Any], source_text: str) -> ExtractionResult:
        """Convert raw JSON object into ExtractionResult."""
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
                    source_text=source_text,
                )
                tuples.append(tuple_obj)
            except Exception as e:
                logger.warning("Fact conversion failed: %s, fact=%s", e, fact)

        metadata = {
            "emotion": data.get("emotion", {}),
            "intent": data.get("intent", "unknown"),
            "keywords": data.get("keywords", []),
            "source_text": source_text,
        }

        return ExtractionResult(
            tuples=tuples,
            entities=data.get("entities", []),
            time_expressions=data.get("time_expressions", []),
            locations=data.get("locations", []),
            metadata=metadata,
        )

    def batch_extract(self, messages: List[Dict[str, str]]) -> List[ExtractionResult]:
        """Extract structured information for a list of messages."""
        results = []
        for i, msg in enumerate(messages):
            context = messages[:i] if i > 0 else None
            result = self.extract(
                role=msg.get("role", "user"),
                content=msg.get("content", ""),
                context=context,
            )
            results.append(result)
        return results


def create_extractor_from_config(config) -> LLMExtractor:
    """Factory: create LLMExtractor from project config."""
    memory_api = resolve_memory_api(config)
    return LLMExtractor(
        api_key=memory_api["api_key"],
        base_url=memory_api["base_url"],
        model=memory_api["model"],
        temperature=0.3,
    )
