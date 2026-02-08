import json, os
import tempfile
from pathlib import Path
from typing import Dict, TYPE_CHECKING

if TYPE_CHECKING:
    from .message_manager import Session

class SessionStorage:

    def __init__(self, path: str | None = None):
        
        # 固定到项目目录，避免因启动时 cwd 不同导致“会话看起来丢了”
        default_path = Path(__file__).resolve().parents[1] / "sessions.json"
        self.path = str(default_path) if not path else path
    
    def load_all(self) -> Dict[str, "Session"]:
        # 延迟导入避免循环依赖
        from .message_manager import Session
        
        if not os.path.exists(self.path):
            return {}
        try:
            with open(self.path, "r", encoding="utf-8") as f:
                raw = json.load(f)
            return {sid: Session(**payload) for sid,payload in raw.items()}
        except Exception:
            # 如果加载失败（文件损坏），返回空字典防止服务挂掉，并保留坏文件供排查
            return {}
    
    def save_all(self, sessions: Dict[str, "Session"]):
        data = {sid: s.model_dump() if hasattr(s, "model_dump") else s.dict()
            for sid, s in sessions.items()}
        
        target_path = Path(self.path)
        target_path.parent.mkdir(parents=True, exist_ok=True)
        
        # 原子写入：先写临时文件，flush/fsync 后再重命名
        # 在 Windows 上 os.replace 不能直接覆盖已打开文件，但这里是覆盖未被打开的目标文件，通常可行。
        # 为保险起见，使用 delete=False 的 NamedTemporaryFile 手动控制
        
        dir_path = target_path.parent
        fd, temp_path = tempfile.mkstemp(dir=dir_path, prefix=f"{target_path.name}.tmp", text=True)
        
        try:
            with os.fdopen(fd, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
                f.flush()
                os.fsync(f.fileno())
            
            # 原子替换
            os.replace(temp_path, target_path)
        except Exception as e:
            # 写入失败时尝试清理临时文件
            try:
                os.unlink(temp_path)
            except OSError:
                pass
            raise e
