"""SelfModel cognition and host expressions use the ordinary tool registry."""
from pydantic import BaseModel, ConfigDict

from gateway.public_contracts import SituationUpdate, SemanticUIWrite, EnvironmentInspect, EnvironmentInteraction


class EmptyInput(BaseModel):
    model_config = ConfigDict(extra="forbid")


class _SituationTool:
    def __init__(self, model, name, schema, description, title, *, read_only=False):
        self.model = model
        self.tool_id = self.name = name
        self.input_schema = schema.model_json_schema()
        self.schema = schema
        self.description = description
        self.side_effect_level = "read_only" if read_only else "workspace_write"
        self.presentation = {"title_i18n": title}

    async def invoke(self, args, ctx=None):
        if ctx is None or not ctx.user_id:
            raise PermissionError("an authenticated Runtime identity is required")
        command = self.schema.model_validate(args)
        if self.name == "cognition.context":
            return await self.model.build_context(user_id=ctx.user_id, run_context=(ctx.metadata or {}).get("run_context"))
        if self.name == "cognition.update_situation":
            return await self.model.update_situation(ctx.user_id, command)
        if self.name == "semantic_ui.inspect":
            return self.model.semantic_ui.view(ctx.user_id)
        if self.name == "environment.inspect":
            return await self.model.environment_sources.inspect(ctx.user_id, command.resource)
        if self.name == "environment.interact":
            return await self.model.environment_sources.interact(ctx.user_id, command)
        return await self.model.semantic_ui.present(ctx.user_id, command)


def create_situation_tools(model):
    return [
        _SituationTool(model, "environment.inspect", EnvironmentInspect, "Read a current object snapshot, including declared component relationships, actual app values, available operations and versions. Unsupported sources remain unknown; declarations are not proof of visual correspondence or external business facts.", {"zh": "查看当前对象", "en": "Inspect environment object"}, read_only=True),
        _SituationTool(model, "environment.interact", EnvironmentInteraction, "Apply a declared app component operation through Runtime using current state and definition revisions. Only validated scalar app mutations are supported, never arbitrary code or tool names. For external actions and Task changes use their existing governed capabilities.", {"zh": "操作界面组件", "en": "Interact with component"}),
        _SituationTool(model, "cognition.context", EmptyInput, "Read Global and Situational context, including current working revision, recent changes, visible surface and unresolved questions. No model call or Memory write.", {"zh": "了解当前情境", "en": "Read current situation"}, read_only=True),
        _SituationTool(model, "cognition.update_situation", SituationUpdate, "Revise SelfModel working attention, questions and interpretation using its current working revision. Keep unresolved matters across conversations. Interpretations are not verified Memory facts or Runtime state changes.", {"zh": "更新情境理解", "en": "Update situation"}),
        _SituationTool(model, "semantic_ui.inspect", EmptyInput, "Read your persistent host expressions and user responses before creating or updating them.", {"zh": "查看互动", "en": "Inspect expressions"}, read_only=True),
        _SituationTool(model, "semantic_ui.present", SemanticUIWrite, "Express a note, gesture, choice or ongoing panel to the user. Use their language and current situation; humor and warmth are welcome when appropriate. Reuse expression_id and expected_revision to update/hide without regenerating an app. Personal expressions have no session; message anchors require an owned session and exact message id. Choices record feedback only, never authorize tools or establish facts. Use Intelligent Canvas instead for calculators, editors and other applications.", {"zh": "表达与互动", "en": "Express and interact"}),
    ]
