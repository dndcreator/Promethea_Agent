"""Versioned, declarative Canvas documents; no model-authored executable code."""
from __future__ import annotations

import json
from html import escape
from pathlib import Path
from typing import Annotated, Literal, Union

from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictFloat, StrictInt, StrictStr, model_validator

Scalar = Union[StrictBool, StrictInt, StrictFloat, StrictStr]
Key = Annotated[str, Field(pattern=r"^[a-zA-Z][a-zA-Z0-9_]{0,63}$")]


class ComponentContract(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class CanvasMutation(ComponentContract):
    op: Literal["set", "increment", "toggle", "reset", "calculate"]
    field: Key | None = None
    value: Scalar | None = None
    inputs: list[Key] = Field(default_factory=list, max_length=16)
    operation: Literal["sum", "difference", "product", "ratio"] | None = None

    @model_validator(mode="after")
    def check_shape(self):
        if self.op == "reset":
            valid = self.field is None and self.value is None and not self.inputs and self.operation is None
        else:
            valid = self.field is not None
            if self.op == "calculate":
                valid = valid and self.value is None and bool(self.inputs) and self.operation is not None
                if self.operation in {"difference", "ratio"}:
                    valid = valid and len(self.inputs) == 2
            else:
                valid = valid and not self.inputs and self.operation is None
                valid = valid and (self.value is None if self.op == "toggle" else self.value is not None)
        if not valid:
            raise ValueError("invalid Canvas mutation arguments")
        return self


class CanvasText(ComponentContract):
    type: Literal["text"]
    id: Key
    text: str | None = Field(default=None, max_length=4000)
    bind: Key | None = None
    emphasis: Literal["heading", "body", "caption"] = "body"

    @model_validator(mode="after")
    def check_source(self):
        if (self.text is None) == (self.bind is None):
            raise ValueError("text requires exactly one of text or bind")
        return self


class CanvasInput(ComponentContract):
    type: Literal["input"]
    id: Key
    label: str = Field(min_length=1, max_length=200)
    bind: Key
    input_type: Literal["text", "number"] = "text"


class CanvasCheckbox(ComponentContract):
    type: Literal["checkbox"]
    id: Key
    label: str = Field(min_length=1, max_length=200)
    bind: Key


class CanvasOption(ComponentContract):
    label: str = Field(min_length=1, max_length=200)
    value: str = Field(max_length=500)


class CanvasSelect(ComponentContract):
    type: Literal["select"]
    id: Key
    label: str = Field(min_length=1, max_length=200)
    bind: Key
    options: list[CanvasOption] = Field(min_length=1, max_length=64)


class CanvasButton(ComponentContract):
    type: Literal["button"]
    id: Key
    label: str = Field(min_length=1, max_length=200)
    actions: list[CanvasMutation] = Field(min_length=1, max_length=16)
    variant: Literal["primary", "secondary"] = "primary"


class CanvasTable(ComponentContract):
    type: Literal["table"]
    id: Key
    columns: list[Annotated[str, Field(max_length=200)]] = Field(min_length=1, max_length=16)
    rows: list[list[Scalar]] = Field(default_factory=list, max_length=100)

    @model_validator(mode="after")
    def check_rows(self):
        if any(len(row) != len(self.columns) for row in self.rows):
            raise ValueError("table rows must match its columns")
        return self


class CanvasStack(ComponentContract):
    type: Literal["stack"]
    id: Key
    direction: Literal["row", "column"] = "column"
    children: list["CanvasNode"] = Field(min_length=1, max_length=64)


CanvasNode = Annotated[Union[CanvasText, CanvasInput, CanvasCheckbox, CanvasSelect, CanvasButton, CanvasTable, CanvasStack], Field(discriminator="type")]
CanvasStack.model_rebuild()


class CanvasDocument(ComponentContract):
    version: Literal["canvas.ui.v1"] = "canvas.ui.v1"
    title: str = Field(min_length=1, max_length=200)
    language: str = Field(default="en", pattern=r"^[a-zA-Z]{2,8}(?:-[a-zA-Z0-9]{1,8})*$")
    initial_state: dict[Key, Scalar] = Field(default_factory=dict, max_length=64)
    root: CanvasNode

    @model_validator(mode="before")
    @classmethod
    def bound_document(cls, value):
        pending = [(value, 0)]
        while pending:
            item, depth = pending.pop()
            if depth > 24:
                raise ValueError("Canvas document nesting exceeds limit")
            if isinstance(item, dict):
                if any(key in {"__proto__", "prototype", "constructor"} for key in item):
                    raise ValueError("reserved Canvas object key")
                pending.extend((child, depth + 1) for child in item.values())
            elif isinstance(item, list):
                pending.extend((child, depth + 1) for child in item)
        raw = json.dumps(value, ensure_ascii=False, allow_nan=False)
        if len(raw.encode("utf-8")) > 64_000:
            raise ValueError("Canvas document exceeds 64 KB")
        return value

    @model_validator(mode="after")
    def validate_bindings(self):
        pending = [(self.root, 0)]
        ids = set()
        selections = {}
        assignments = []
        while pending:
            node, depth = pending.pop()
            if depth > 8 or len(ids) >= 128 or node.id in ids or node.id in {"canvas_root", "canvas_status", "canvas_document"}:
                raise ValueError("duplicate/reserved component id or component limits exceeded")
            ids.add(node.id)
            if isinstance(node, CanvasStack):
                pending.extend((child, depth + 1) for child in node.children)
            if isinstance(node, (CanvasInput, CanvasCheckbox, CanvasSelect, CanvasText)) and node.bind is not None:
                if node.bind not in self.initial_state:
                    raise ValueError(f"undeclared state binding: {node.bind}")
                value = self.initial_state[node.bind]
                expected = bool if isinstance(node, CanvasCheckbox) else str if isinstance(node, CanvasSelect) else None
                if isinstance(node, CanvasInput):
                    expected = str if node.input_type == "text" else (int, float)
                if expected is not None and (not isinstance(value, expected) or isinstance(value, bool) and expected is not bool):
                    raise ValueError(f"wrong state type for {node.id}")
                if isinstance(node, CanvasSelect) and (value not in [option.value for option in node.options] or len({option.value for option in node.options}) != len(node.options)):
                    raise ValueError("select requires unique options and a matching initial value")
                if isinstance(node, CanvasSelect):
                    values = {option.value for option in node.options}
                    selections[node.bind] = selections.get(node.bind, values) & values
            if isinstance(node, CanvasButton):
                for action in node.actions:
                    if action.op == "reset":
                        continue
                    if action.field not in self.initial_state or any(key not in self.initial_state for key in action.inputs):
                        raise ValueError("action references undeclared state")
                    target = self.initial_state[action.field]
                    numeric = lambda item: type(item) in (int, float)
                    if action.op == "set" and (isinstance(target, bool) != isinstance(action.value, bool) or numeric(target) != numeric(action.value) or isinstance(target, str) != isinstance(action.value, str)):
                        raise ValueError("set must preserve the declared state type")
                    if action.op == "set":
                        assignments.append(action)
                    if action.op == "toggle" and type(target) is not bool:
                        raise ValueError("toggle requires boolean state")
                    if action.op in {"increment", "calculate"} and not numeric(target):
                        raise ValueError("numeric action requires numeric state")
                    if action.op == "increment" and not numeric(action.value):
                        raise ValueError("increment requires a numeric value")
                    if action.op == "calculate" and any(not numeric(self.initial_state[key]) for key in action.inputs):
                        raise ValueError("calculation inputs must be numeric")
        if any(action.field in selections and action.value not in selections[action.field] for action in assignments):
            raise ValueError("set must select a declared option")
        return self


def render_component_document(document: dict) -> str:
    definition = CanvasDocument.model_validate(document)
    payload = json.dumps(definition.model_dump(), ensure_ascii=False, allow_nan=False).replace("&", "\\u0026").replace("<", "\\u003c").replace(">", "\\u003e").replace("\u2028", "\\u2028").replace("\u2029", "\\u2029")
    renderer = Path(__file__).with_name("canvas_components.js").read_text(encoding="utf-8")
    return (f'<!doctype html><html lang="{escape(definition.language, quote=True)}"><head>'
            '<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
            f'<title>{escape(definition.title)}</title></head><body>'
            '<main id="canvas_root"></main><p id="canvas_status" role="status" aria-live="polite"></p>'
            f'<script id="canvas_document" type="application/json">{payload}</script><script>{renderer}</script></body></html>')
