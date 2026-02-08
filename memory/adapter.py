"""
璁板繂绯荤粺閫傞厤鍣?瑙ｅ喅瀵硅瘽绯荤粺鍜岃蹇嗙郴缁熸帴鍙ｄ笉涓€鑷寸殑闂
"""
import logging
import time
from typing import Optional
import threading

logger = logging.getLogger(__name__)


class MemoryAdapter:
    """
    璁板繂绯荤粺閫傞厤鍣?    
    灏?MessageManager 鐨勭畝鍗曟帴鍙ｉ€傞厤鍒?HotLayerManager 鐨勫鏉傛帴鍙?    """
    
    def __init__(self):
        """鍒濆鍖栭€傞厤鍣?""
        self.enabled = False
        self._config = None
        self.hot_layer = None
        self.recall_engine = None
        self._warm_layer = None
        self._cold_layer = None
        self._forgetting = None
        self._session_cache = {}  # 缂撳瓨姣忎釜 session 鐨勬秷鎭巻鍙?        # 閲嶈锛歁essageManager 浼氬湪涓嶅悓绾跨▼閲岃Е鍙戝啓鍏ワ紙run_in_executor锛?        # hot_layer 鏄湁鐘舵€佸璞★紙session_id 浼氳淇敼锛夛紝蹇呴』鍔犻攣閬垮厤骞跺彂鍐欏叆涓插彴
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
        """鍒濆鍖栬蹇嗙郴缁燂紙澶辫触涓嶆姏寮傚父锛?""
        try:
            from config import load_config
            config = load_config()
            self._config = config
            
            # 妫€鏌ユ槸鍚﹀惎鐢?            if not config.memory.enabled:
                logger.info("璁板繂绯荤粺鏈惎鐢紙config.memory.enabled = false锛?)
                return
            
            # 浣跨敤宸ュ巶鍑芥暟鍒涘缓
            from memory import create_hot_layer_manager
            # 鍒濆鍖栨椂缁欎竴涓粯璁?session_id锛屽疄闄呬娇鐢ㄦ椂浼氬姩鎬佹洿鏂?            self.hot_layer = create_hot_layer_manager("_adapter_init", "default_user")
            
            if self.hot_layer:
                # 鍒濆鍖栧彫鍥炲紩鎿?                from .auto_recall import AutoRecallEngine
                self.recall_engine = AutoRecallEngine(
                    connector=self.hot_layer.connector,
                    extractor=self.hot_layer.extractor
                )
                self.enabled = True
                logger.info("鉁?璁板繂绯荤粺閫傞厤鍣ㄥ垵濮嬪寲鎴愬姛锛堝惈鍙洖寮曟搸锛?)
            else:
                logger.info("璁板繂绯荤粺涓嶅彲鐢紙Neo4j 鏈繛鎺ユ垨閰嶇疆閿欒锛?)
                
        except Exception as e:
            logger.warning(f"璁板繂绯荤粺鍒濆鍖栧け璐? {e}")
            self.enabled = False
    
    def add_message(self, session_id: str, role: str, content: str, user_id: str = "default_user") -> bool:
        """
        娣诲姞娑堟伅鍒拌蹇嗙郴缁?        
        Args:
            session_id: 浼氳瘽ID
            role: 瑙掕壊 (user/assistant)
            content: 娑堟伅鍐呭
            user_id: 鐢ㄦ埛ID (榛樿涓?default_user)
            
        Returns:
            鏄惁鎴愬姛
        """
        if not self.enabled or not self.hot_layer:
            return False
        
        try:
            with self._hot_layer_lock:
                # 鏇存柊 session_id 鍜?user_id锛圚otLayerManager 鏄湁鐘舵€佺殑锛?                self.hot_layer.session_id = session_id
                self.hot_layer.user_id = user_id
            
                # 鑾峰彇涓婁笅鏂囷紙浠庣紦瀛橈級
            context = self._get_context(session_id)
            
                # 璋冪敤璁板繂绯荤粺
            stats = self.hot_layer.process_message(role, content, context)
            
                # 鏇存柊缂撳瓨
            self._update_cache(session_id, role, content)
            
                logger.debug(f"璁板繂宸蹭繚瀛? {stats}")
            return True
            
        except Exception as e:
            logger.error(f"璁板繂绯荤粺澶勭悊澶辫触: {e}")
            return False
    
    def _get_context(self, session_id: str) -> list:
        """鑾峰彇浼氳瘽涓婁笅鏂囷紙鏈€杩?鏉℃秷鎭級"""
        if session_id not in self._session_cache:
            self._session_cache[session_id] = []
        return self._session_cache[session_id][-5:]  # 鍙彇鏈€杩?鏉?    
    def _update_cache(self, session_id: str, role: str, content: str):
        """鏇存柊涓婁笅鏂囩紦瀛?""
        if session_id not in self._session_cache:
            self._session_cache[session_id] = []
        
        self._session_cache[session_id].append({
            "role": role,
            "content": content
        })
        
        # 闄愬埗缂撳瓨澶у皬锛堟渶澶氫繚鐣?0鏉★級
        if len(self._session_cache[session_id]) > 10:
            self._session_cache[session_id] = self._session_cache[session_id][-10:]
    
    def get_context(self, query: str, session_id: str, user_id: str = "default_user") -> str:
        """
        鑾峰彇鐩稿叧璁板繂涓婁笅鏂囷紙鑷姩鍙洖锛?        
        Args:
            query: 鐢ㄦ埛褰撳墠娑堟伅
            session_id: 浼氳瘽ID
            user_id: 鐢ㄦ埛ID
            
        Returns:
            鏍煎紡鍖栫殑涓婁笅鏂囧瓧绗︿覆
        """
        if not self.enabled or not self.recall_engine:
            return ""
        
        try:
            return self.recall_engine.recall(query, session_id, user_id)
        except Exception as e:
            logger.error(f"鑾峰彇璁板繂涓婁笅鏂囧け璐? {e}")
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
        """妫€鏌ヨ蹇嗙郴缁熸槸鍚﹀彲鐢?""
        return self.enabled and self.hot_layer is not None


# 鍏ㄥ眬鍗曚緥
_memory_adapter_instance: Optional[MemoryAdapter] = None


def get_memory_adapter() -> MemoryAdapter:
    """鑾峰彇鍏ㄥ眬璁板繂閫傞厤鍣ㄥ疄渚?""
    global _memory_adapter_instance
    if _memory_adapter_instance is None:
        _memory_adapter_instance = MemoryAdapter()
    return _memory_adapter_instance


