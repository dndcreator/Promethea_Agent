"""Inspect declared app semantics and apply only the existing scalar mutation DSL."""
from __future__ import annotations

import hashlib
import json
from html.parser import HTMLParser
from math import isfinite

from .canvas_components import CanvasDocument, CanvasButton, CanvasStack, CanvasInput, CanvasCheckbox, CanvasSelect, render_component_document


def read_document(source: str):
    class DocumentParser(HTMLParser):
        def __init__(self):
            super().__init__(convert_charrefs=False)
            self.active, self.parts, self.documents = False, [], []

        def handle_starttag(self, tag, attrs):
            if tag == "script" and dict(attrs).get("id") == "canvas_document":
                self.active, self.parts = True, []

        def handle_data(self, value):
            if self.active:
                self.parts.append(value)

        def handle_endtag(self, tag):
            if tag == "script" and self.active:
                self.documents.append("".join(self.parts))
                self.active = False
    parser = DocumentParser()
    parser.feed(source)
    if not parser.documents:
        return None
    if len(parser.documents) != 1:
        raise ValueError("app must expose exactly one semantic document")
    return CanvasDocument.model_validate(json.loads(parser.documents[0]))


def nodes(document):
    pending = [(document.root, None)]
    while pending:
        node, parent = pending.pop()
        yield node, parent
        if isinstance(node, CanvasStack):
            pending.extend((child, node.id) for child in reversed(node.children))


def validate_state(document, value):
    initial = document.initial_state
    if not isinstance(value, dict) or set(value) != set(initial):
        raise ValueError("app state must match declared fields")
    for key, expected in initial.items():
        actual = value[key]
        numeric = lambda item: type(item) in (int, float) and isfinite(item)
        if not (numeric(actual) and numeric(expected)) and type(actual) is not type(expected):
            raise ValueError(f"invalid declared state type: {key}")
        if isinstance(actual, float) and not isfinite(actual):
            raise ValueError("non-finite app state")
        if isinstance(actual, str) and len(actual) > 4000:
            raise ValueError("app text exceeds field limit")
    for node, _ in nodes(document):
        if isinstance(node, CanvasSelect) and value[node.bind] not in {option.value for option in node.options}:
            raise ValueError("state does not match declared options")


def snapshot(source: str, state: dict):
    document = read_document(source)
    if document is None:
        return {"status": "undeclared", "definition_revision": hashlib.sha256(source.encode()).hexdigest(), "components": []}
    value = {**document.initial_state, **state.get("value", {})}
    validate_state(document, value)
    components = []
    for node, parent in nodes(document):
        bind = getattr(node, "bind", None)
        operations = ["activate"] if isinstance(node, CanvasButton) else ["set"] if isinstance(node, (CanvasInput, CanvasCheckbox, CanvasSelect)) else []
        schema = None
        if operations == ["set"]:
            bound = document.initial_state[bind]
            schema = {"type": "boolean" if isinstance(bound, bool) else "number" if type(bound) in (int, float) else "string"}
            if schema["type"] == "string":
                schema["maxLength"] = 4000
            if isinstance(node, CanvasSelect):
                schema["enum"] = [option.value for option in node.options]
        components.append({"component_id": node.id, "parent_id": parent, "kind": node.type,
                           "label": getattr(node, "label", None) or getattr(node, "text", None) or node.id,
                           "description": node.description,
                           "object_ref": node.object_ref.model_dump() if node.object_ref else None,
                           "binding": bind, "value": value.get(bind) if bind else None,
                           "operations": operations,
                           "input_schema": schema,
                           "options": [option.model_dump() for option in node.options] if isinstance(node, CanvasSelect) else None})
    return {"status": "compiled" if source == render_component_document(document.model_dump()) else "declared",
            "title": document.title, "definition_revision": hashlib.sha256(source.encode()).hexdigest(),
            "revision": int(state.get("revision") or 0), "state_origin": "runtime_stored_app_data_not_external_business_facts",
            "components": components}


def interact(source, state, *, component_id, operation, value=None, definition_revision):
    if hashlib.sha256(source.encode()).hexdigest() != definition_revision:
        raise ValueError("app definition changed; inspect semantics before acting")
    document = read_document(source)
    if document is None:
        raise ValueError("app has no declared interaction contract")
    node = next((node for node, _ in nodes(document) if node.id == component_id), None)
    result = {**document.initial_state, **state.get("value", {})}
    validate_state(document, result)
    if operation == "set" and isinstance(node, (CanvasInput, CanvasCheckbox, CanvasSelect)):
        result[node.bind] = value
    elif operation == "activate" and isinstance(node, CanvasButton) and value is None:
        for action in node.actions:
            if action.op == "reset":
                result = dict(document.initial_state)
            elif action.op == "set":
                result[action.field] = action.value
            elif action.op == "toggle":
                result[action.field] = not result[action.field]
            elif action.op == "increment":
                result[action.field] += action.value
            else:
                values = [result[key] for key in action.inputs]
                if action.operation == "sum":
                    computed = sum(values)
                elif action.operation == "product":
                    computed = 1
                    for item in values:
                        computed *= item
                elif action.operation == "difference":
                    computed = values[0] - values[1]
                else:
                    if values[1] == 0:
                        raise ValueError("division by zero")
                    computed = values[0] / values[1]
                result[action.field] = computed
    else:
        raise ValueError("operation is not declared by this component")
    validate_state(document, result)
    return result
