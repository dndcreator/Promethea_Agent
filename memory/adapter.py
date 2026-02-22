"""
conversation system to the richer multi-layer memory system (hot / warm / cold).
"""
import logging
import time
from typing import Optional
import threading
from .session_scope import scoped_session_id

logger = logging.getLogger(__name__)


class MemoryAdapter:
    """
    Memory system adapter.
    
    Exposes a very small API that the rest of the agent can call, while
    internally delegating to the hot/warm/cold/forgetting managers.
    """
    
    def __init__(self):
        """Initialise the adapter and (best-effort) memory stack."""
        self.enabled = False
        self._config = None
        self.hot_layer = None
        self.recall_engine = None
        self._warm_layer = None
        self._cold_layer = None
        self._forgetting = None
        # Cache recent messages for each session to build lightweight context.
        # Important: MessageManager may run in different threads (run_in_executor);
        # hot_layer carries state (session_id / user_id), so we must guard access.
        self._session_cache = {}
        self._hot_layer_lock = threading.Lock()
        self._maintenance_lock = threading.Lock()
        self._idle_timer_lock = threading.Lock()
        self._idle_timers = {}
        self._maintenance_state = {}
        self._maintenance_defaults = {
            'cluster_every_messages': 12,
            'cluster_min_interval_s': 300,
            'idle_cluster_delay_s': 120,
            'idle_cluster_min_messages': 2,
            'idle_cluster_min_interval_s': 60,
            'summary_min_interval_s': 600,
            'decay_interval_s': 24 * 3600,
        }
        self._maintenance_persist_keys = (
            'messages',
            'messages_since_cluster',
            'last_message_at',
            'last_cluster_at',
            'last_summary_at',
            'last_decay_at',
        )
        self._init_memory_system()
    
    def _init_memory_system(self):
        """Initialise memory system (fail-soft: never raise to callers)."""
        try:
            from config import load_config
            config = load_config()
            self._config = config
            self._load_maintenance_defaults_from_config(config)
            
            # Check if memory is enabled in config
            if not config.memory.enabled:
                logger.info("Memory system disabled (config.memory.enabled = false)")
                return
            
            # Use factory helpers to create hot-layer manager
            from memory import create_hot_layer_manager
            # During init we give a dummy session_id; it will be updated per call.
            self.hot_layer = create_hot_layer_manager("_adapter_init", "default_user")
            
            if self.hot_layer:
                # Initialise auto-recall engine
                from .auto_recall import AutoRecallEngine
                self.recall_engine = AutoRecallEngine(
                    connector=self.hot_layer.connector,
                    extractor=self.hot_layer.extractor
                )
                self.enabled = True
                logger.info("Memory adapter initialised successfully (with auto-recall)")
            else:
                logger.info("Memory system not available (Neo4j not connected or misconfigured)")
                
        except Exception as e:
            logger.warning(f"Memory system initialisation failed: {e}")
            self.enabled = False

    def _load_maintenance_defaults_from_config(self, config):
        warm = getattr(config.memory, "warm_layer", None)
        if warm is None:
            return
        self._maintenance_defaults['cluster_every_messages'] = max(
            1, int(getattr(warm, 'cluster_every_messages', self._maintenance_defaults['cluster_every_messages']))
        )
        self._maintenance_defaults['cluster_min_interval_s'] = max(
            0, int(getattr(warm, 'cluster_min_interval_s', self._maintenance_defaults['cluster_min_interval_s']))
        )
        self._maintenance_defaults['idle_cluster_delay_s'] = max(
            10, int(getattr(warm, 'idle_cluster_delay_s', self._maintenance_defaults['idle_cluster_delay_s']))
        )
        self._maintenance_defaults['idle_cluster_min_messages'] = max(
            1, int(getattr(warm, 'idle_cluster_min_messages', self._maintenance_defaults['idle_cluster_min_messages']))
        )
        self._maintenance_defaults['idle_cluster_min_interval_s'] = max(
            0, int(getattr(warm, 'idle_cluster_min_interval_s', self._maintenance_defaults['idle_cluster_min_interval_s']))
        )
    
    def add_message(
        self,
        session_id: str,
        role: str,
        content: str,
        user_id: str = "default_user",
        metadata: Optional[dict] = None,
    ) -> bool:
        """
        Add a message into the memory system.
        
        Args:
            session_id: Conversation/session identifier.
            role: "user" or "assistant".
            content: Message text.
            user_id: Logical user id (default "default_user").
            
        Returns:
            bool: whether the message was successfully processed.
        """
        if not self.enabled or not self.hot_layer:
            return False
        
        try:
            scoped_sid = scoped_session_id(session_id, user_id)
            with self._hot_layer_lock:
                # Update stateful hot-layer with current session/user
                self.hot_layer.session_id = scoped_sid
                self.hot_layer.user_id = user_id
                
                # Build lightweight context from cache
                context = self._get_context(scoped_sid)
                
                # Call into memory system
                stats = self.hot_layer.process_message(
                    role,
                    content,
                    context,
                    metadata=metadata,
                )
                
                # Update cache
                self._update_cache(scoped_sid, role, content)
                
                logger.debug(f"Memory stored with stats: {stats}")
            return True
            
        except Exception as e:
            logger.error(f"Memory system processing failed: {e}")
            return False
    
    def _get_context(self, session_id: str) -> list:
        """Get recent context messages (up to last 5) for a session."""
        if session_id not in self._session_cache:
            self._session_cache[session_id] = []
        # Only keep a small sliding window to avoid unbounded growth
        return self._session_cache[session_id][-5:]
    def _update_cache(self, session_id: str, role: str, content: str):
        """Update in-memory context cache."""
        if session_id not in self._session_cache:
            self._session_cache[session_id] = []
        
        self._session_cache[session_id].append({
            "role": role,
            "content": content
        })
        
        # Limit cache size per session to at most 10 messages
        if len(self._session_cache[session_id]) > 10:
            self._session_cache[session_id] = self._session_cache[session_id][-10:]
    
    def get_context(self, query: str, session_id: str, user_id: str = "default_user") -> str:
        """
        Retrieve related memory context (auto recall).
        
        Args:
            query: Current user query text.
            session_id: Conversation/session identifier.
            user_id: Logical user id.
            
        Returns:
            Formatted context string (may be empty).
        """
        if not self.enabled or not self.recall_engine:
            return ""
        
        try:
            scoped_sid = scoped_session_id(session_id, user_id)
            return self.recall_engine.recall(query, scoped_sid, user_id)
        except Exception as e:
            logger.error(f"Failed to get memory context: {e}")
            return ""
    
    def _ensure_managers(self):
        if not self._config or not self.hot_layer:
            return

        if self._warm_layer is None and getattr(self._config.memory.warm_layer, 'enabled', False):
            try:
                from memory import create_warm_layer_manager
                self._warm_layer = create_warm_layer_manager(self.hot_layer.connector)
            except Exception as e:
                logger.debug(f"Warm layer init failed: {e}")

        if self._cold_layer is None:
            try:
                from memory import create_cold_layer_manager
                self._cold_layer = create_cold_layer_manager(self.hot_layer.connector)
            except Exception as e:
                logger.debug(f"Cold layer init failed: {e}")

        if self._forgetting is None:
            try:
                from memory import create_forgetting_manager
                self._forgetting = create_forgetting_manager(self.hot_layer.connector)
            except Exception as e:
                logger.debug(f"Forgetting manager init failed: {e}")

    def _get_maintenance_state(self, session_id: str) -> dict:
        with self._maintenance_lock:
            state = self._maintenance_state.get(session_id)
            if not state:
                state = {
                    'messages': 0,
                    'messages_since_cluster': 0,
                    'last_message_at': 0.0,
                    'last_cluster_at': 0.0,
                    'last_summary_at': 0.0,
                    'last_decay_at': 0.0,
                    'cluster_running': False,
                    'summary_running': False,
                    'decay_running': False,
                    'maintenance_queued': False,
                }
                persisted = self._load_maintenance_state(session_id)
                if persisted:
                    for key in self._maintenance_persist_keys:
                        if key in persisted:
                            state[key] = persisted[key]
                self._maintenance_state[session_id] = state
            return state

    def _load_maintenance_state(self, session_id: str) -> dict:
        """
        Load persisted maintenance state from Session node.
        This allows process restarts without losing maintenance continuity.
        """
        if not self.hot_layer:
            return {}
        try:
            rows = self.hot_layer.connector.query(
                """
                MATCH (s:Session {id: $session_id})
                RETURN
                    coalesce(s.maint_messages, 0) AS messages,
                    coalesce(s.maint_messages_since_cluster, 0) AS messages_since_cluster,
                    coalesce(s.maint_last_message_at, 0.0) AS last_message_at,
                    coalesce(s.maint_last_cluster_at, 0.0) AS last_cluster_at,
                    coalesce(s.maint_last_summary_at, 0.0) AS last_summary_at,
                    coalesce(s.maint_last_decay_at, 0.0) AS last_decay_at
                LIMIT 1
                """,
                {"session_id": f"session_{session_id}"},
            )
            if not rows:
                return {}
            row = rows[0]
            return {
                "messages": int(row.get("messages", 0) or 0),
                "messages_since_cluster": int(row.get("messages_since_cluster", 0) or 0),
                "last_message_at": float(row.get("last_message_at", 0.0) or 0.0),
                "last_cluster_at": float(row.get("last_cluster_at", 0.0) or 0.0),
                "last_summary_at": float(row.get("last_summary_at", 0.0) or 0.0),
                "last_decay_at": float(row.get("last_decay_at", 0.0) or 0.0),
            }
        except Exception as e:
            logger.debug(f"Load persisted maintenance state failed: {e}")
            return {}

    def _persist_maintenance_state(self, session_id: str, state: dict):
        if not self.hot_layer:
            return
        try:
            self.hot_layer.connector.query(
                """
                MATCH (s:Session {id: $session_id})
                SET
                    s.maint_messages = $messages,
                    s.maint_messages_since_cluster = $messages_since_cluster,
                    s.maint_last_message_at = $last_message_at,
                    s.maint_last_cluster_at = $last_cluster_at,
                    s.maint_last_summary_at = $last_summary_at,
                    s.maint_last_decay_at = $last_decay_at
                """,
                {
                    "session_id": f"session_{session_id}",
                    "messages": int(state.get("messages", 0)),
                    "messages_since_cluster": int(state.get("messages_since_cluster", 0)),
                    "last_message_at": float(state.get("last_message_at", 0.0)),
                    "last_cluster_at": float(state.get("last_cluster_at", 0.0)),
                    "last_summary_at": float(state.get("last_summary_at", 0.0)),
                    "last_decay_at": float(state.get("last_decay_at", 0.0)),
                },
            )
        except Exception as e:
            logger.debug(f"Persist maintenance state failed: {e}")

    def on_message_saved(self, session_id: str, role: str, user_id: str = 'default_user'):
        if not self.enabled or not self.hot_layer:
            return

        try:
            scoped_sid = scoped_session_id(session_id, user_id)
            self._ensure_managers()
            state = self._get_maintenance_state(scoped_sid)
            state['messages'] += 1
            state['messages_since_cluster'] += 1
            state['last_message_at'] = time.time()
            self._persist_maintenance_state(scoped_sid, state)
            self._schedule_maintenance(scoped_sid, state)
            if self._config and getattr(self._config.memory.warm_layer, 'enabled', False):
                self._schedule_idle_cluster_check(scoped_sid)
        except Exception as e:
            logger.debug(f"Memory maintenance skipped: {e}")

    def _schedule_maintenance(self, session_id: str, state: dict):
        with self._maintenance_lock:
            if state.get('maintenance_queued'):
                return
            state['maintenance_queued'] = True

        worker = threading.Thread(
            target=self._run_maintenance_worker,
            args=(session_id,),
            daemon=True,
        )
        worker.start()

    def _schedule_idle_cluster_check(self, session_id: str):
        delay_s = self._maintenance_defaults['idle_cluster_delay_s']

        with self._idle_timer_lock:
            prev = self._idle_timers.get(session_id)
            if prev:
                prev.cancel()

            timer = threading.Timer(delay_s, self._run_idle_cluster_check, args=(session_id,))
            timer.daemon = True
            self._idle_timers[session_id] = timer
            timer.start()

    def _run_idle_cluster_check(self, session_id: str):
        try:
            self._ensure_managers()
            state = self._get_maintenance_state(session_id)
            now = time.time()
            last_message_at = float(state.get('last_message_at', 0.0))
            delay_s = self._maintenance_defaults['idle_cluster_delay_s']
            if now - last_message_at < delay_s:
                return
            self._maybe_cluster(session_id, state, now, force_on_idle=True)
        except Exception as e:
            logger.debug(f"Idle warm-layer check skipped: {e}")
        finally:
            with self._idle_timer_lock:
                current = self._idle_timers.get(session_id)
                if current and not current.is_alive():
                    self._idle_timers.pop(session_id, None)

    def _run_maintenance_worker(self, session_id: str):
        try:
            state = self._get_maintenance_state(session_id)
            now = time.time()
            self._maybe_cluster(session_id, state, now)
            self._maybe_summarize(session_id, state, now)
            self._maybe_decay(session_id, state, now)
        except Exception as e:
            logger.debug(f"Memory maintenance worker skipped: {e}")
        finally:
            with self._maintenance_lock:
                state = self._maintenance_state.get(session_id)
                if state:
                    state['maintenance_queued'] = False

    def _maybe_cluster(self, session_id: str, state: dict, now: float, force_on_idle: bool = False):
        if not self._warm_layer or not self._config:
            return
        if not getattr(self._config.memory.warm_layer, 'enabled', False):
            return

        min_cluster = getattr(self._config.memory.warm_layer, 'min_cluster_size', 3)
        if force_on_idle:
            min_messages = max(
                min_cluster,
                self._maintenance_defaults['idle_cluster_min_messages'],
            )
            min_interval = self._maintenance_defaults['idle_cluster_min_interval_s']
            if state['messages_since_cluster'] < min_messages:
                return
            if now - state['last_cluster_at'] < min_interval:
                return
        else:
            cluster_every = max(self._maintenance_defaults['cluster_every_messages'], min_cluster * 4)
            min_interval = self._maintenance_defaults['cluster_min_interval_s']
            if state['messages_since_cluster'] < cluster_every:
                return
            if now - state['last_cluster_at'] < min_interval:
                return

        with self._maintenance_lock:
            if state['cluster_running']:
                return
            state['cluster_running'] = True

        try:
            created = self._warm_layer.cluster_entities(session_id)
            if created:
                logger.info(f"Warm layer clustered: session={session_id}, concepts={created}")
            state['messages_since_cluster'] = 0
            state['last_cluster_at'] = now
            self._persist_maintenance_state(session_id, state)
        finally:
            with self._maintenance_lock:
                state['cluster_running'] = False

    def _maybe_summarize(self, session_id: str, state: dict, now: float):
        if not self._cold_layer:
            return

        min_interval = self._maintenance_defaults['summary_min_interval_s']
        if now - state['last_summary_at'] < min_interval:
            return

        with self._maintenance_lock:
            if state['summary_running']:
                return
            state['summary_running'] = True

        try:
            if self._cold_layer.should_create_summary(session_id):
                summary_id = self._cold_layer.create_incremental_summary(session_id)
                if summary_id:
                    logger.info(f"Cold layer summary created: session={session_id}, summary={summary_id}")
                state['last_summary_at'] = now
                self._persist_maintenance_state(session_id, state)
        finally:
            with self._maintenance_lock:
                state['summary_running'] = False

    def _maybe_decay(self, session_id: str, state: dict, now: float):
        if not self._forgetting:
            return

        min_interval = self._maintenance_defaults['decay_interval_s']
        if now - state['last_decay_at'] < min_interval:
            return

        with self._maintenance_lock:
            if state['decay_running']:
                return
            state['decay_running'] = True

        try:
            self._forgetting.apply_time_decay(session_id)
            self._forgetting.cleanup_forgotten(session_id)
            self._forgetting.cleanup_episodic_messages(session_id)
            state['last_decay_at'] = now
            self._persist_maintenance_state(session_id, state)
        finally:
            with self._maintenance_lock:
                state['decay_running'] = False
    
    def is_enabled(self) -> bool:
        """Return True if the memory system is initialised and usable."""
        return self.enabled and self.hot_layer is not None


_memory_adapter_instance: Optional[MemoryAdapter] = None


def get_memory_adapter() -> MemoryAdapter:
    """Get the global MemoryAdapter singleton instance."""
    global _memory_adapter_instance
    if _memory_adapter_instance is None:
        _memory_adapter_instance = MemoryAdapter()
    return _memory_adapter_instance


