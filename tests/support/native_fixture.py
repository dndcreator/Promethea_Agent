"""Inert community tool, installed only into disposable acceptance deployments."""
import json
from pathlib import Path


class PublishFixture:
    tool_id = name = "fixture.publish"
    description = "Acceptance fixture: record text locally after approval. No external delivery exists."
    input_schema = {"type": "object", "properties": {"text": {"type": "string"}}, "required": ["text"]}
    side_effect_level = "external_write"

    async def invoke(self, args, ctx=None):
        with Path("fixture-receipts.jsonl").open("a", encoding="utf-8") as stream:
            stream.write(json.dumps({"text": args["text"]}) + "\n")
        return {"recorded": True, "fixture_only": True}


def create_tools(runtime):
    return [PublishFixture()]
