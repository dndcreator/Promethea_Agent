class EchoTool:
    tool_id = "utils.echo"
    name = "utils.echo"
    description = "Echo input text."
    side_effect_level = "read_only"

    async def invoke(self, args, ctx=None):
        return {"echo": str((args or {}).get("text") or "")}
