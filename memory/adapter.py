"""
MemoryAdapter – adapts the simple MessageManager-style interface used by the
conversation system to the richer multi-layer memory system (hot / warm / cold).
"""
import logging
import time
from typing import Optional
import threading

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
        self._maintenance_state = {}
        self._maintenance_defaults = {
            'cluster_every_messages': 12,
            'cluster_min_interval_s': 300,
            'summary_min_interval_s': 600,
            'decay_interval_s': 24 * 3600,
        }
        self._init_memory_system()
    
    def _init_memory_system(self):
        """Initialise memory system (fail-soft: never raise to callers)."""
        try:
            from config import load_config
            config = load_config()
            self._config = config
            
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
    
    def add_message(self, session_id: str, role: str, content: str, user_id: str = "default_user") -> bool:
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
            with self._hot_layer_lock:
                # Update stateful hot-layer with current session/user
                self.hot_layer.session_id = session_id
                self.hot_layer.user_id = user_id
                
                # Build lightweight context from cache
                context = self._get_context(session_id)
                
                # Call into memory system
                stats = self.hot_layer.process_message(role, content, context)
                
                # Update cache
                self._update_cache(session_id, role, content)
                
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
            return self.recall_engine.recall(query, session_id, user_id)
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
                    'last_cluster_at': 0.0,
                    'last_summary_at': 0.0,
                    'last_decay_at': 0.0,
                    'cluster_running': False,
                    'summary_running': False,
                    'decay_running': False,
                }
                self._maintenance_state[session_id] = state
            return state

    def on_message_saved(self, session_id: str, role: str, user_id: str = 'default_user'):
        if not self.enabled or not self.hot_layer:
            return

        try:
            self._ensure_managers()
            state = self._get_maintenance_state(session_id)
            state['messages'] += 1
            state['messages_since_cluster'] += 1
            now = time.time()

            self._maybe_cluster(session_id, state, now)
            self._maybe_summarize(session_id, state, now)
            self._maybe_decay(session_id, state, now)
        except Exception as e:
            logger.debug(f"Memory maintenance skipped: {e}")

    def _maybe_cluster(self, session_id: str, state: dict, now: float):
        if not self._warm_layer or not self._config:
            return
        if not getattr(self._config.memory.warm_layer, 'enabled', False):
            return

        min_cluster = getattr(self._config.memory.warm_layer, 'min_cluster_size', 3)
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
            state['last_decay_at'] = now
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


