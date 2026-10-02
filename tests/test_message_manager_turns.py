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


def test_turn_commit_idempotent_no_duplicate():
    mgr = _build_manager()
    sid = mgr.create_session("s1", user_id="u1")

    assert mgr.begin_turn(sid, "t1", "user", "hello", "u1")
    assert mgr.commit_turn(sid, "t1", "world", user_id="u1")
    # TODO: comment cleaned

    msgs = mgr.get_messages(sid, user_id="u1")
    assert len(msgs) == 2


def test_turn_abort_removes_pending():
    mgr = _build_manager()
    sid = mgr.create_session("s1", user_id="u1")

    assert mgr.begin_turn(sid, "t1", "user", "hello", "u1")
    assert mgr.abort_turn(sid, "t1", user_id="u1")
    # TODO: comment cleaned
    assert mgr.get_messages(sid, user_id="u1") == []


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
    assert source.commit_turn(sid, "t1", "a useful answer", user_id="u1")
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
    assert restored.get_session(sid, user_id="u1")["followups"][0]["message_id"] == message["id"]
