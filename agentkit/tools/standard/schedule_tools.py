"""Agent access to the existing owner-scoped temporal runtime."""
from gateway.tools.schema import input_object, text, integer, boolean


class RuntimeScheduleTool:
    tool_id = name = "runtime.schedule"
    side_effect_level = "workspace_write"
    description = "Persist an owner-scoped schedule for a registered tool. Observe mode accepts only declared read-only observation sources and publishes changes to Runtime without a model call. Sensitive targets cannot run unattended."
    input_schema = input_object({"name": text(), "service_name": text(), "tool_name": text(),
        "args": {"type": "object"}, "interval_seconds": integer(minimum=1),
        "trigger": {"type": "object"}, "timezone_name": text(), "observe": boolean()},
        required=("name", "service_name", "tool_name"))

    def __init__(self, gateway_server):
        self.server = gateway_server

    def scheduler(self):
        scheduler = getattr(self.server, "kernel_scheduler", None)
        if scheduler is None:
            raise RuntimeError("temporal runtime is unavailable")
        return scheduler.schedules

    async def invoke(self, args, ctx=None):
        if ctx is None or not ctx.user_id:
            raise PermissionError("scheduling requires an authenticated owner")
        return await self.scheduler().create_job(**{key: value for key, value in args.items() if key in self.input_schema["properties"]})


class RuntimeScheduleControlTool(RuntimeScheduleTool):
    def __init__(self, gateway_server, operation):
        super().__init__(gateway_server)
        self.operation = operation
        self.tool_id = self.name = {"list": "runtime.schedules", "pause": "runtime.pause_schedule",
            "resume": "runtime.resume_schedule", "remove": "runtime.remove_schedule"}[operation]
        self.side_effect_level = "read_only" if operation == "list" else "workspace_write"
        self.description = f"{operation.capitalize()} the current owner's persistent schedules."
        self.input_schema = input_object() if operation == "list" else input_object({"job_id": text()}, required=("job_id",))

    async def invoke(self, args, ctx=None):
        if ctx is None or not ctx.user_id:
            raise PermissionError("schedule management requires an authenticated owner")
        method = {"list": "list_jobs", "pause": "pause_job", "resume": "resume_job", "remove": "remove_job"}[self.operation]
        return await getattr(self.scheduler(), method)(**{key: value for key, value in args.items() if key in self.input_schema["properties"]})
