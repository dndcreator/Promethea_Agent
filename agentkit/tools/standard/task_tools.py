from gateway.tools.schema import input_object, text


class TaskStartTool:
    tool_id = name = "task.start"
    domain = "task"
    side_effect_level = "workspace_write"
    input_schema = input_object({"title": text()}, required=("title",))
    description = (
        "Start the current user's request as a durable task before starting multi-step work that should survive "
        "interruption, approval, or a conversation switch. Use for delegated work with a deliverable, not a direct "
        "answer or a quick lookup. The task will do the work; do not run the same work in this chat."
    )
    presentation = {"title": "Start task", "title_i18n": {"en": "Start task", "zh": "\u542f\u52a8\u4efb\u52a1"}, "subject_arg": "title"}

    def __init__(self, tasks):
        self.tasks = tasks

    async def invoke(self, args, ctx=None):
        return self.tasks.start(ctx, args["title"])

    @staticmethod
    def present_result(args, result):
        if isinstance(result, dict) and result.get("task_id"):
            return {"references": [{"kind": "task", "target": result["task_id"], "label": result["title"]}]}
        return {}


class TaskListTool(TaskStartTool):
    tool_id = name = "task.list"
    side_effect_level = "read_only"
    input_schema = input_object()
    description = (
        "List the user's recent durable chat tasks across conversations. When the user asks to continue existing "
        "work, find the matching task here first. Ask the user if the intended task is ambiguous."
    )
    presentation = {"title": "Find tasks", "title_i18n": {"en": "Find tasks", "zh": "\u67e5\u627e\u4efb\u52a1"}}

    async def invoke(self, args, ctx=None):
        return self.tasks.list(ctx)


class TaskResumeTool(TaskStartTool):
    tool_id = name = "task.resume"
    input_schema = input_object({"task_id": text()}, required=("task_id",))
    description = (
        "Continue an existing task when the user asks to resume that work. Use its exact task ID from task.list. "
        "This attaches the current chat without changing the execution workspace. It never grants approval. "
        "If the task is running, complete or awaiting explicit input, return its current state instead."
    )
    presentation = {"title": "Continue task", "title_i18n": {"en": "Continue task", "zh": "\u7ee7\u7eed\u4efb\u52a1"}}

    async def invoke(self, args, ctx=None):
        return self.tasks.resume(ctx, args["task_id"])
