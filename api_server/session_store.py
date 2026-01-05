import json, os
from pathlib import Path
from typing import Dict, TYPE_CHECKING

if TYPE_CHECKING:
    from .message_manager import Session

class SessionStorage:

    def __init__(self, path: str = "sessions.json"):
        
        self.path = path
    
    def load_all(self) -> Dict[str, "Session"]:
        # 延迟导入避免循环依赖
        from .message_manager import Session
        
        if not os.path.exists(self.path):
            return {}
        with open(self.path, "r", encoding="utf-8") as f:
            raw = json.load(f)

        return {sid: Session(**payload) for sid,payload in raw.items()}
    
    def save_all(self, sessions: Dict[str, "Session"]):

        data = {sid: s.model_dump() if hasattr(s, "model_dump") else s.dict()
            for sid, s in sessions.items()}
        Path(os.path.dirname(self.path) or ".").mkdir(parents = True, exist_ok = True)
        with open(self.path, "w", encoding = "utf-8") as f:
            json.dump(data, f, ensure_ascii = False)