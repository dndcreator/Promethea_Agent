"""
File system controller.
"""
import os
import shutil
from pathlib import Path
from typing import Dict, Any, List, Optional
from .base import ComputerController, ComputerCapability, ComputerResult
import logging

logger = logging.getLogger("Computer.FileSystem")


class FileSystemController(ComputerController):
    """Computer controller for interacting with the file system."""
    
    def __init__(self, workspace_root: Optional[str] = None):
        super().__init__("FileSystem", ComputerCapability.FILESYSTEM)
        # Workspace root used to constrain the scope of file operations.
        self.workspace_root = Path(workspace_root) if workspace_root else Path.cwd()
        # Backward-compatible default: unrestricted unless workspace_root is explicitly provided
        self.restricted_mode = workspace_root is not None
    
    async def initialize(self) -> bool:
        """Initialise file system control."""
        try:
            # Ensure the workspace directory exists
            self.workspace_root.mkdir(parents=True, exist_ok=True)
            
            self.is_initialized = True
            logger.info(f"FileSystem controller initialized. Workspace: {self.workspace_root}")
            return True
        except Exception as e:
            logger.error(f"Failed to initialize filesystem controller: {e}")
            return False
    
    async def cleanup(self) -> bool:
        """Clean up resources."""
        self.is_initialized = False
        logger.info("FileSystem controller cleaned up")
        return True
    
    def _resolve_path(self, path_str: str) -> Path:
        """Resolve and validate a path inside the workspace (if restricted)."""
        path = Path(path_str)
        
        # If the path is relative, interpret it relative to the workspace root.
        if not path.is_absolute():
            path = self.workspace_root / path
        
        # Restricted mode: only allow access to paths inside the workspace.
        if self.restricted_mode:
            try:
                path.resolve().relative_to(self.workspace_root.resolve())
            except ValueError:
                raise PermissionError(
                    f"Access denied: {path} is outside workspace {self.workspace_root}"
                )
        
        return path
    
    async def execute(self, action: str, params: Dict[str, Any]) -> ComputerResult:
        """Dispatch and execute a file-system action."""
        if not self.is_initialized:
            return ComputerResult(
                success=False,
                error="FileSystem controller not initialized"
            )
        
        try:
            action_map = {
                'read': self._read_file,
                'write': self._write_file,
                'append': self._append_file,
                'delete': self._delete,
                'move': self._move,
                'copy': self._copy,
                'mkdir': self._mkdir,
                'list': self._list_dir,
                'exists': self._exists,
                'stat': self._get_stat,
                'search': self._search,
            }
            
            handler = action_map.get(action)
            if not handler:
                return ComputerResult(
                    success=False,
                    error=f"Unknown action: {action}"
                )
            
            result = await handler(params)
            return ComputerResult(success=True, result=result)
            
        except PermissionError as e:
            logger.error(f"Permission denied: {e}")
            return ComputerResult(success=False, error=str(e))
        except Exception as e:
            logger.error(f"Error executing {action}: {e}")
            return ComputerResult(success=False, error=str(e))
    
    def get_available_actions(self) -> List[Dict[str, Any]]:
        """Return a list of supported file-system actions."""
        return [
            {"name": "read", "description": "Read a file", "params": ["path", "encoding?"]},
            {"name": "write", "description": "Write a file", "params": ["path", "content", "encoding?"]},
            {"name": "append", "description": "Append to a file", "params": ["path", "content", "encoding?"]},
            {"name": "delete", "description": "Delete a file or directory", "params": ["path", "recursive?"]},
            {"name": "move", "description": "Move a file or directory", "params": ["src", "dst"]},
            {"name": "copy", "description": "Copy a file or directory", "params": ["src", "dst"]},
            {"name": "mkdir", "description": "Create a directory", "params": ["path", "parents?"]},
            {"name": "list", "description": "List directory contents", "params": ["path", "recursive?"]},
            {"name": "exists", "description": "Check path existence", "params": ["path"]},
            {"name": "stat", "description": "Get file metadata", "params": ["path"]},
            {"name": "search", "description": "Search for files", "params": ["pattern", "path?"]},
        ]
    
    # ============ File operations ============
    
    async def _read_file(self, params: Dict[str, Any]) -> str:
        """Read file contents as text."""
        path_str = params.get('path')
        encoding = params.get('encoding', 'utf-8')
        
        if not path_str:
            raise ValueError("Missing required parameter: path")
        
        path = self._resolve_path(path_str)
        
        if not path.exists():
            raise FileNotFoundError(f"File not found: {path}")
        
        if not path.is_file():
            raise IsADirectoryError(f"Not a file: {path}")
        
        return path.read_text(encoding=encoding)
    
    async def _write_file(self, params: Dict[str, Any]) -> str:
        """Write text content to a file (overwrite)."""
        path_str = params.get('path')
        content = params.get('content')
        encoding = params.get('encoding', 'utf-8')
        
        if not path_str or content is None:
            raise ValueError("Missing required parameters: path, content")
        
        path = self._resolve_path(path_str)
        
        # Ensure the parent directory exists
        path.parent.mkdir(parents=True, exist_ok=True)
        
        path.write_text(content, encoding=encoding)
        return f"Written to {path}"
    
    async def _append_file(self, params: Dict[str, Any]) -> str:
        """Append text content to an existing file."""
        path_str = params.get('path')
        content = params.get('content')
        encoding = params.get('encoding', 'utf-8')
        
        if not path_str or content is None:
            raise ValueError("Missing required parameters: path, content")
        
        path = self._resolve_path(path_str)
        
        with open(path, 'a', encoding=encoding) as f:
            f.write(content)
        
        return f"Appended to {path}"
    
    # ============ File / directory management ============
    
    async def _delete(self, params: Dict[str, Any]) -> str:
        """Delete a file or directory (optionally recursive)."""
        path_str = params.get('path')
        recursive = params.get('recursive', False)
        
        if not path_str:
            raise ValueError("Missing required parameter: path")
        
        path = self._resolve_path(path_str)
        
        if not path.exists():
            raise FileNotFoundError(f"Path not found: {path}")
        
        if path.is_file():
            path.unlink()
            return f"Deleted file: {path}"
        elif path.is_dir():
            if recursive:
                shutil.rmtree(path)
                return f"Deleted directory: {path}"
            else:
                path.rmdir()  # Only delete empty directories
                return f"Deleted empty directory: {path}"
    
    async def _move(self, params: Dict[str, Any]) -> str:
        """Move a file or directory to a new location."""
        src_str = params.get('src')
        dst_str = params.get('dst')
        
        if not src_str or not dst_str:
            raise ValueError("Missing required parameters: src, dst")
        
        src = self._resolve_path(src_str)
        dst = self._resolve_path(dst_str)
        
        if not src.exists():
            raise FileNotFoundError(f"Source not found: {src}")
        
        shutil.move(str(src), str(dst))
        return f"Moved {src} to {dst}"
    
    async def _copy(self, params: Dict[str, Any]) -> str:
        """Copy a file or directory to a new location."""
        src_str = params.get('src')
        dst_str = params.get('dst')
        
        if not src_str or not dst_str:
            raise ValueError("Missing required parameters: src, dst")
        
        src = self._resolve_path(src_str)
        dst = self._resolve_path(dst_str)
        
        if not src.exists():
            raise FileNotFoundError(f"Source not found: {src}")
        
        if src.is_file():
            shutil.copy2(str(src), str(dst))
            return f"Copied file {src} to {dst}"
        elif src.is_dir():
            shutil.copytree(str(src), str(dst), dirs_exist_ok=True)
            return f"Copied directory {src} to {dst}"
    
    async def _mkdir(self, params: Dict[str, Any]) -> str:
        """Create a directory (optionally with parents)."""
        path_str = params.get('path')
        parents = params.get('parents', True)
        
        if not path_str:
            raise ValueError("Missing required parameter: path")
        
        path = self._resolve_path(path_str)
        path.mkdir(parents=parents, exist_ok=True)
        return f"Created directory: {path}"
    
    async def _list_dir(self, params: Dict[str, Any]) -> List[Dict[str, Any]]:
        """List items in a directory (optionally recursive)."""
        path_str = params.get('path', '.')
        recursive = params.get('recursive', False)
        
        path = self._resolve_path(path_str)
        
        if not path.exists():
            raise FileNotFoundError(f"Directory not found: {path}")
        
        if not path.is_dir():
            raise NotADirectoryError(f"Not a directory: {path}")
        
        items = []
        
        if recursive:
            for item in path.rglob('*'):
                items.append(self._get_item_info(item))
        else:
            for item in path.iterdir():
                items.append(self._get_item_info(item))
        
        return items
    
    def _get_item_info(self, path: Path) -> Dict[str, Any]:
        """Get basic information about a file or directory."""
        stat = path.stat()
        return {
            "name": path.name,
            "path": str(path.relative_to(self.workspace_root) if self.workspace_root in path.parents else path),
            "type": "file" if path.is_file() else "directory",
            "size": stat.st_size if path.is_file() else 0,
            "modified": stat.st_mtime,
            "created": stat.st_ctime,
        }
    
    # ============ File information ============
    
    async def _exists(self, params: Dict[str, Any]) -> bool:
        """Check if a file or directory exists."""
        path_str = params.get('path')
        
        if not path_str:
            raise ValueError("Missing required parameter: path")
        
        path = self._resolve_path(path_str)
        return path.exists()
    
    async def _get_stat(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Get detailed file or directory statistics."""
        path_str = params.get('path')
        
        if not path_str:
            raise ValueError("Missing required parameter: path")
        
        path = self._resolve_path(path_str)
        
        if not path.exists():
            raise FileNotFoundError(f"Path not found: {path}")
        
        return self._get_item_info(path)
    
    async def _search(self, params: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Search for files by glob pattern under a base path."""
        pattern = params.get('pattern')
        search_path = params.get('path', '.')
        
        if not pattern:
            raise ValueError("Missing required parameter: pattern")
        
        path = self._resolve_path(search_path)
        
        if not path.exists():
            raise FileNotFoundError(f"Search path not found: {path}")
        
        results = []
        for item in path.rglob(pattern):
            results.append(self._get_item_info(item))
        
        return results
