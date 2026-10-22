"""Ambient actions use the same manifest factory and policy as other tools."""
from pydantic import BaseModel, ConfigDict, Field
from gateway.ambient_state import current_ambient


class Reflection(BaseModel):
    model_config = ConfigDict(extra="forbid")
    attention: list[str] = Field(max_length=6)
    questions: list[str] = Field(max_length=8)
    interpretation: str = Field(max_length=4000)


class Annotation(BaseModel):
    model_config = ConfigDict(extra="forbid")
    message_id: str = Field(min_length=1, max_length=200)
    session_id: str | None = Field(default=None, max_length=200)
    selected_text: str = Field(min_length=1, max_length=2000)
    start_offset: int = Field(ge=0)
    end_offset: int = Field(ge=1)
    title: str = Field(min_length=1, max_length=120)
    content: str = Field(min_length=1, max_length=4000)


class Speech(BaseModel):
    model_config = ConfigDict(extra="forbid")
    content: str = Field(min_length=1, max_length=8000)
    session_id: str | None = Field(default=None, max_length=200)


class AmbientTool:
    side_effect_level = "workspace_write"
    requires_run_option = "ambient"

    def __init__(self, action, schema, description, title):
        self.tool_id = self.name = f"ambient.{action}"
        self.action, self.schema = action, schema
        self.description = description
        self.input_schema = schema.model_json_schema()
        self.presentation = {"title_i18n": title}

    async def invoke(self, args, ctx=None):
        frame = current_ambient()
        if frame is None:
            raise PermissionError("ambient actions require an active autonomous execution")
        frame.service.assert_execution()
        value = self.schema.model_validate(args).model_dump()
        if self.action == "reflect":
            return frame.service.reflect(**value)
        if self.action == "annotate":
            return frame.service.annotate(**value)
        return await frame.service.say(**value)


def create_tools(runtime):
    return [
        AmbientTool("reflect", Reflection, "Retain working attention, open questions and an interpretation across activations. This never writes personal Memory or declares Runtime facts.", {"zh": "更新当前理解", "en": "Update working understanding"}),
        AmbientTool("annotate", Annotation, "Leave a useful note on an exact visible message span. Use the supplied message id and Unicode offsets. Existing annotations and user feedback should prevent repeated notes.", {"zh": "添加批注", "en": "Add annotation"}),
        AmbientTool("say", Speech, "Send one useful, model-authored message in the current conversation. Prefer quiet work or inline notes when interrupting the user is unnecessary.", {"zh": "主动交流", "en": "Share an update"}),
    ]
