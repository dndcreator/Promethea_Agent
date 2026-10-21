from __future__ import annotations

from typing import Any, Dict, Iterable, Mapping, Optional

from pydantic import BaseModel, Field


MAX_TITLE_LENGTH = 160
MAX_SUMMARY_LENGTH = 600
MAX_REFERENCES = 24


class ToolPresentationReference(BaseModel):
    model_config = {"extra": "forbid"}

    kind: str = Field(default="reference", min_length=1, max_length=48)
    arg: Optional[str] = Field(default=None, min_length=1, max_length=120)
    target: Optional[str] = Field(default=None, min_length=1, max_length=2000)
    label: Optional[str] = Field(default=None, max_length=MAX_TITLE_LENGTH)
    label_arg: Optional[str] = Field(default=None, min_length=1, max_length=120)
    metadata: Dict[str, Any] = Field(default_factory=dict)


class ToolPresentationSpec(BaseModel):
    """Declarative Workbench card contract shared by every tool source."""

    model_config = {"extra": "forbid"}

    kind: str = Field(default="tool", min_length=1, max_length=48)
    title: Optional[str] = Field(default=None, min_length=1, max_length=MAX_TITLE_LENGTH)
    title_i18n: Dict[str, str] = Field(default_factory=dict)
    subject_arg: Optional[str] = Field(default=None, min_length=1, max_length=120)
    summary: Optional[str] = Field(default=None, max_length=MAX_SUMMARY_LENGTH)
    summary_i18n: Dict[str, str] = Field(default_factory=dict)
    references: list[ToolPresentationReference] = Field(default_factory=list, max_length=MAX_REFERENCES)


def validate_presentation_declaration(value: Any) -> Dict[str, Any]:
    if value in (None, {}):
        return {}
    if not isinstance(value, Mapping):
        raise ValueError("tool presentation must be an object")
    spec = ToolPresentationSpec.model_validate(value)
    for reference in spec.references:
        if not reference.arg and not reference.target:
            raise ValueError("tool presentation reference requires arg or target")
    for field_name, localized in (
        ("title_i18n", spec.title_i18n),
        ("summary_i18n", spec.summary_i18n),
    ):
        limit = MAX_SUMMARY_LENGTH if field_name == "summary_i18n" else MAX_TITLE_LENGTH
        if any(not str(language).strip() or not str(text).strip() or len(str(text)) > limit for language, text in localized.items()):
            raise ValueError(f"invalid localized text in {field_name}")
    return spec.model_dump(mode="json", exclude_none=True)


def project_tool_call(tool: Any, args: Mapping[str, Any]) -> Dict[str, Any]:
    """Build a bounded, transport-neutral presentation from a tool declaration."""
    declared = getattr(tool, "presentation", None)
    presentation = _from_declaration(declared, args=args)
    presenter = getattr(tool, "present_call", None)
    if callable(presenter):
        presentation.update(_normalize(presenter(dict(args or {}))))
    if not presentation.get("title"):
        presentation["title"] = _fallback_title(tool)
    if not presentation.get("title_i18n"):
        identity = str(getattr(tool, "full_name", "") or getattr(tool, "tool_id", "") or getattr(tool, "name", "") or "")
        presentation["title_i18n"] = {"zh": f"调用工具 · {identity}", "en": presentation["title"]}
    return _normalize(presentation)


def project_tool_result(
    tool: Any,
    args: Mapping[str, Any],
    result: Any,
    *,
    call_presentation: Mapping[str, Any] | None = None,
) -> Dict[str, Any]:
    presentation = dict(call_presentation or project_tool_call(tool, args))
    presenter = getattr(tool, "present_result", None)
    if callable(presenter):
        presentation.update(_normalize(presenter(dict(args or {}), result)))
    return _normalize(presentation)


def _from_declaration(declared: Any, *, args: Mapping[str, Any]) -> Dict[str, Any]:
    if not isinstance(declared, Mapping):
        return {}
    output = {
        key: declared[key]
        for key in ("kind", "title", "title_i18n", "summary", "summary_i18n")
        if declared.get(key) not in (None, "")
    }
    subject_arg = str(declared.get("subject_arg") or "").strip()
    subject = args.get(subject_arg) if subject_arg else None
    if subject not in (None, ""):
        output["subject"] = _scalar(subject)
    references = []
    for item in declared.get("references") or []:
        if not isinstance(item, Mapping):
            continue
        argument = str(item.get("arg") or "").strip()
        target = args.get(argument) if argument else item.get("target")
        if target in (None, ""):
            continue
        references.append({
            "kind": str(item.get("kind") or "reference"),
            "target": _scalar(target),
            "label": _scalar(args.get(str(item.get("label_arg") or "")) or item.get("label") or target),
            "metadata": dict(item.get("metadata") or {}),
        })
    if references:
        output["references"] = references
    return output


def _fallback_title(tool: Any) -> str:
    description = " ".join(str(getattr(tool, "description", "") or "").split())
    if description:
        return description.split(".", 1)[0][:MAX_TITLE_LENGTH]
    full_name = str(getattr(tool, "full_name", "") or getattr(tool, "tool_id", "") or getattr(tool, "name", "") or "Tool")
    return " ".join(part for part in full_name.replace(".", " ").replace("_", " ").split() if part).strip().capitalize()[:MAX_TITLE_LENGTH]


def _normalize(value: Any) -> Dict[str, Any]:
    if not isinstance(value, Mapping):
        return {}
    output: Dict[str, Any] = {}
    for key in ("kind", "title", "subject", "summary"):
        item = value.get(key)
        if item not in (None, ""):
            limit = MAX_SUMMARY_LENGTH if key == "summary" else MAX_TITLE_LENGTH
            output[key] = _scalar(item)[:limit]
    for key in ("title_i18n", "summary_i18n"):
        item = value.get(key)
        if isinstance(item, Mapping):
            limit = MAX_SUMMARY_LENGTH if key == "summary_i18n" else MAX_TITLE_LENGTH
            normalized = {
                str(language): _scalar(text)[:limit]
                for language, text in item.items()
                if text not in (None, "")
            }
            if normalized:
                output[key] = normalized
    references = []
    for item in _iter_mappings(value.get("references")):
        target = _scalar(item.get("target"))
        if not target:
            continue
        references.append({
            "kind": _scalar(item.get("kind") or "reference"),
            "target": target,
            "label": _scalar(item.get("label") or target)[:MAX_TITLE_LENGTH],
            "metadata": dict(item.get("metadata") or {}),
        })
        if len(references) >= MAX_REFERENCES:
            break
    if references:
        output["references"] = references
    return output


def _iter_mappings(value: Any) -> Iterable[Mapping[str, Any]]:
    if not isinstance(value, (list, tuple)):
        return ()
    return (item for item in value if isinstance(item, Mapping))


def _scalar(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, (str, int, float, bool)):
        return " ".join(str(value).split())
    return ""
