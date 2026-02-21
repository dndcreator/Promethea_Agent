import json, os
import tempfile
from pathlib import Path
from typing import Dict, TYPE_CHECKING

if TYPE_CHECKING:
    from .message_manager import Session

class SessionStorage:

    def __init__(self, path: str | None = None):
        
        default_path = Path(__file__).resolve().parents[1] / "sessions.json"
        self.path = str(default_path) if not path else path
    
    def load_all(self) -> Dict[str, "Session"]:
        from .message_manager import Session
        
        if not os.path.exists(self.path):
            return {}
        try:
            with open(self.path, "r", encoding="utf-8") as f:
                raw = json.load(f)
            return {sid: Session(**payload) for sid,payload in raw.items()}
        except Exception:
            return {}
    
    def save_all(self, sessions: Dict[str, "Session"]):
        data = {sid: s.model_dump() if hasattr(s, "model_dump") else s.dict()
            for sid, s in sessions.items()}
        
        target_path = Path(self.path)
        target_path.parent.mkdir(parents=True, exist_ok=True)
        
        
        dir_path = target_path.parent
        fd, temp_path = tempfile.mkstemp(dir=dir_path, prefix=f"{target_path.name}.tmp", text=True)
        
        try:
            with os.fdopen(fd, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
                f.flush()
                os.fsync(f.fileno())
            
            os.replace(temp_path, target_path)
        except Exception as e:
            try:
                os.unlink(temp_path)
            except OSError:
                pass
            raise e
