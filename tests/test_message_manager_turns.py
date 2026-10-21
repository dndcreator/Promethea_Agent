from gateway.http.message_manager import MessageManager


class _NoopStore:
    def __init__(self):
        self.last = {}

    def load_all(self):
        return {}

    def save_all(self, sessions):
        self.last = sessions


def _build_manager() -> MessageManager:
    mgr = MessageManager()
    mgr.session_store = _NoopStore()
    mgr.session = {}
    mgr.memory_adapter = None
    return mgr


def test_turn_commit_is_atomic():
    mgr = _build_manager()
    sid = mgr.create_session("s1", user_id="u1")

    assert mgr.begin_turn(sid, "t1", "user", "hello", "u1")
    # TODO: comment cleaned

    assert mgr.commit_turn(sid, "t1", "world", user_id="u1")
    msgs = mgr.get_messages(sid, user_id="u1")
    assert len(msgs) == 2
    assert msgs[0]["role"] == "user" and msgs[0]["content"] == "hello"
    assert msgs[1]["role"] == "assistant" and msgs[1]["content"] == "world"


def test_turn_commit_persists_reasoning_tree_on_assistant_message():
    mgr = _build_manager()
    sid = mgr.create_session("s1", user_id="u1")

    assert mgr.begin_turn(sid, "t1", "user", "hello", "u1")
    assert mgr.commit_turn(
        sid,
        "t1",
        "world",
        user_id="u1",
        reasoning_tree_id="tree-1",
    )

    messages = mgr.get_session(sid, user_id="u1")["messages"]
    assert messages[0]["reasoning_tree_id"] is None
    assert messages[1]["reasoning_tree_id"] == "tree-1"


def test_turn_commit_persists_turn_identity_and_visible_reasoning():
    mgr = _build_manager()
    sid = mgr.create_session("s1", user_id="u1")
    steps = [{"step_id": "step-1", "source": "provider", "content": "Check the facts."}]

    assert mgr.begin_turn(sid, "t1", "user", "hello", "u1")
    assert mgr.commit_turn(sid, "t1", "world", user_id="u1", reasoning_steps=steps)

    messages = mgr.get_messages(sid, user_id="u1")
    assert messages[0]["conversation_turn_id"] == "t1"
    assert messages[1]["conversation_turn_id"] == "t1"
    assert messages[1]["reasoning_steps"] == steps


def test_turn_commit_idempotent_no_duplicate():
    mgr = _build_manager()
    sid = mgr.create_session("s1", user_id="u1")

    assert mgr.begin_turn(sid, "t1", "user", "hello", "u1")
    assert mgr.commit_turn(sid, "t1", "world", user_id="u1")
    # TODO: comment cleaned

    msgs = mgr.get_messages(sid, user_id="u1")
    assert len(msgs) == 2


def test_turn_abort_retains_request_and_runtime_status_without_an_assistant_answer():
    mgr = _build_manager()
    sid = mgr.create_session("s1", user_id="u1")

    assert mgr.begin_turn(sid, "t1", "user", "hello", "u1")
    assert mgr.abort_turn(sid, "t1", user_id="u1")
    messages = mgr.get_messages(sid, user_id="u1")
    assert [item["role"] for item in messages] == ["user", "status"]
    assert messages[0]["content"] == "hello"
    assert messages[1]["run_status"] == "interrupted"
    assert mgr.get_recent_messages(sid, user_id="u1") == [messages[0]]
    assert not mgr.commit_turn(sid, "t1", "late answer", user_id="u1")
    assert not mgr.begin_turn(sid, "t1", "user", "hello", "u1")


def test_failed_turn_keeps_reasoning_and_error_through_export_import():
    source = _build_manager()
    sid = source.create_session("s1", user_id="u1")
    source.begin_turn(sid, "t1", "user", "Build a calculator", "u1")
    source.abort_turn(sid, "t1", user_id="u1", error={"code": "MODEL_OUTPUT_LIMIT"}, reasoning_steps=[{"content": "Prepare components"}])
    restored = _build_manager()
    restored.replace_user_sessions(user_id="u1", sessions=source.export_user_sessions(user_id="u1"))
    messages = restored.get_messages(sid, user_id="u1")
    assert messages[-1]["error"]["code"] == "MODEL_OUTPUT_LIMIT"
    assert messages[-1]["reasoning_steps"] == [{"content": "Prepare components"}]
    assert restored.get_session_info(sid, user_id="u1")["last_message"] == "Build a calculator"


def test_followup_is_persisted_against_its_message_anchor():
    mgr = _build_manager()
    sid = mgr.create_session("s1", user_id="u1")
    assert mgr.begin_turn(sid, "t1", "user", "hello", "u1")
    assert mgr.commit_turn(sid, "t1", "a useful answer", user_id="u1")
    message = mgr.get_messages(sid, user_id="u1")[1]

    followup = mgr.add_followup(
        sid,
        user_id="u1",
        message_id=message["id"],
        selected_text="useful",
        start_offset=2,
        end_offset=8,
        query_type="why",
        custom_query=None,
        query="Why?",
        response="Because it is actionable.",
    )

    assert followup and followup["message_id"] == message["id"]
    assert mgr.get_session(sid, user_id="u1")["followups"][0]["response"] == "Because it is actionable."


def test_workspace_session_round_trip_keeps_message_ids_and_followups():
    source = _build_manager()
    sid = source.create_session("s1", user_id="u1")
    assert source.begin_turn(sid, "t1", "user", "hello", "u1")
    assert source.commit_turn(sid, "t1", "a useful answer", user_id="u1", reasoning_tree_id="tree-1")
    message = source.get_messages(sid, user_id="u1")[1]
    assert source.add_followup(
        sid, user_id="u1", message_id=message["id"], selected_text="useful", start_offset=2, end_offset=8,
        query_type="why", custom_query=None, query="Why?", response="Because it is actionable.",
    )

    restored = _build_manager()
    result = restored.replace_user_sessions(user_id="u1", sessions=source.export_user_sessions(user_id="u1"))
    assert result["imported_sessions"] == 1
    restored_message = restored.get_messages(sid, user_id="u1")[1]
    assert restored_message["id"] == message["id"]
    assert restored_message["reasoning_tree_id"] == "tree-1"
    assert restored.get_session(sid, user_id="u1")["followups"][0]["message_id"] == message["id"]
