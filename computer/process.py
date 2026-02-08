"""
进程管理控制器
"""
import subprocess
import signal
from typing import Dict, Any, List, Optional
from .base import ComputerController, ComputerCapability, ComputerResult
import logging

logger = logging.getLogger("Computer.Process")


class ProcessController(ComputerController):
    """进程管理控制器"""
    
    def __init__(self):
        super().__init__("Process", ComputerCapability.PROCESS)
        self.psutil = None
        self.active_processes: Dict[int, Any] = {}  # pid -> subprocess.Popen
    
    async def initialize(self) -> bool:
        """初始化进程管理"""
        try:
            # 动态导入 psutil
            import psutil
            self.psutil = psutil
            
            self.is_initialized = True
            logger.info("Process controller initialized")
            return True
        except ImportError:
            logger.error("psutil not installed. Run: pip install psutil")
            return False
        except Exception as e:
            logger.error(f"Failed to initialize process controller: {e}")
            return False
    
    async def cleanup(self) -> bool:
        """清理资源 - 终止所有活动进程"""
        try:
            for pid, proc in list(self.active_processes.items()):
                try:
                    if proc.poll() is None:  # 进程仍在运行
                        proc.terminate()
                        proc.wait(timeout=3)
                except Exception as e:
                    logger.warning(f"Failed to terminate process {pid}: {e}")
            
            self.active_processes.clear()
            self.is_initialized = False
            logger.info("Process controller cleaned up")
            return True
        except Exception as e:
            logger.error(f"Error cleaning up process controller: {e}")
            return False
    
    async def execute(self, action: str, params: Dict[str, Any]) -> ComputerResult:
        """执行进程操作"""
        if not self.is_initialized:
            return ComputerResult(
                success=False,
                error="Process controller not initialized"
            )
        
        try:
            action_map = {
                'run': self._run_command,
                'run_async': self._run_async,
                'list': self._list_processes,
                'get': self._get_process,
                'kill': self._kill_process,
                'terminate': self._terminate_process,
                'wait': self._wait_process,
                'get_output': self._get_output,
                'system_info': self._get_system_info,
            }
            
            handler = action_map.get(action)
            if not handler:
                return ComputerResult(
                    success=False,
                    error=f"Unknown action: {action}"
                )
            
            result = await handler(params)
            return ComputerResult(success=True, result=result)
            
        except Exception as e:
            logger.error(f"Error executing {action}: {e}")
            return ComputerResult(success=False, error=str(e))
    
    def get_available_actions(self) -> List[Dict[str, Any]]:
        """获取可用操作列表"""
        return [
            {"name": "run", "description": "运行命令（同步）", "params": ["command", "cwd?", "env?", "timeout?"]},
            {"name": "run_async", "description": "运行命令（异步）", "params": ["command", "cwd?", "env?"]},
            {"name": "list", "description": "列出进程", "params": ["filter?"]},
            {"name": "get", "description": "获取进程信息", "params": ["pid"]},
            {"name": "kill", "description": "强制终止进程", "params": ["pid"]},
            {"name": "terminate", "description": "优雅终止进程", "params": ["pid"]},
            {"name": "wait", "description": "等待进程结束", "params": ["pid", "timeout?"]},
            {"name": "get_output", "description": "获取进程输出", "params": ["pid"]},
            {"name": "system_info", "description": "获取系统信息", "params": []},
        ]
    
    # ============ 命令执行 ============
    
    async def _run_command(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """同步运行命令"""
        command = params.get('command')
        cwd = params.get('cwd')
        env = params.get('env')
        timeout = params.get('timeout', 30)
        shell = params.get('shell', True)
        
        if not command:
            raise ValueError("Missing required parameter: command")
        
        try:
            result = subprocess.run(
                command,
                shell=shell,
                cwd=cwd,
                env=env,
                capture_output=True,
                text=True,
                timeout=timeout
            )
            
            return {
                "returncode": result.returncode,
                "stdout": result.stdout,
                "stderr": result.stderr,
                "success": result.returncode == 0
            }
        except subprocess.TimeoutExpired:
            return {
                "returncode": -1,
                "error": f"Command timed out after {timeout}s",
                "success": False
            }
        except Exception as e:
            return {
                "returncode": -1,
                "error": str(e),
                "success": False
            }
    
    async def _run_async(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """异步运行命令"""
        command = params.get('command')
        cwd = params.get('cwd')
        env = params.get('env')
        shell = params.get('shell', True)
        
        if not command:
            raise ValueError("Missing required parameter: command")
        
        proc = subprocess.Popen(
            command,
            shell=shell,
            cwd=cwd,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True
        )
        
        self.active_processes[proc.pid] = proc
        
        return {
            "pid": proc.pid,
            "command": command,
            "status": "running"
        }
    
    # ============ 进程管理 ============
    
    async def _list_processes(self, params: Dict[str, Any]) -> List[Dict[str, Any]]:
        """列出进程"""
        filter_name = params.get('filter')
        
        processes = []
        for proc in self.psutil.process_iter(['pid', 'name', 'status', 'cpu_percent', 'memory_percent']):
            try:
                info = proc.info
                
                # 过滤
                if filter_name and filter_name.lower() not in info['name'].lower():
                    continue
                
                processes.append({
                    "pid": info['pid'],
                    "name": info['name'],
                    "status": info['status'],
                    "cpu_percent": info.get('cpu_percent', 0),
                    "memory_percent": info.get('memory_percent', 0)
                })
            except (self.psutil.NoSuchProcess, self.psutil.AccessDenied):
                continue
        
        return processes
    
    async def _get_process(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """获取进程详细信息"""
        pid = params.get('pid')
        
        if pid is None:
            raise ValueError("Missing required parameter: pid")
        
        try:
            proc = self.psutil.Process(pid)
            
            return {
                "pid": proc.pid,
                "name": proc.name(),
                "status": proc.status(),
                "cpu_percent": proc.cpu_percent(interval=0.1),
                "memory_percent": proc.memory_percent(),
                "memory_info": proc.memory_info()._asdict(),
                "num_threads": proc.num_threads(),
                "create_time": proc.create_time(),
                "cmdline": proc.cmdline(),
                "cwd": proc.cwd() if hasattr(proc, 'cwd') else None,
            }
        except self.psutil.NoSuchProcess:
            raise ValueError(f"Process {pid} not found")
        except self.psutil.AccessDenied:
            raise PermissionError(f"Access denied to process {pid}")
    
    async def _kill_process(self, params: Dict[str, Any]) -> str:
        """强制终止进程"""
        pid = params.get('pid')
        
        if pid is None:
            raise ValueError("Missing required parameter: pid")
        
        try:
            proc = self.psutil.Process(pid)
            proc.kill()
            
            # 从活动进程中移除
            if pid in self.active_processes:
                del self.active_processes[pid]
            
            return f"Process {pid} killed"
        except self.psutil.NoSuchProcess:
            raise ValueError(f"Process {pid} not found")
        except self.psutil.AccessDenied:
            raise PermissionError(f"Access denied to kill process {pid}")
    
    async def _terminate_process(self, params: Dict[str, Any]) -> str:
        """优雅终止进程"""
        pid = params.get('pid')
        
        if pid is None:
            raise ValueError("Missing required parameter: pid")
        
        try:
            proc = self.psutil.Process(pid)
            proc.terminate()
            
            # 从活动进程中移除
            if pid in self.active_processes:
                del self.active_processes[pid]
            
            return f"Process {pid} terminated"
        except self.psutil.NoSuchProcess:
            raise ValueError(f"Process {pid} not found")
        except self.psutil.AccessDenied:
            raise PermissionError(f"Access denied to terminate process {pid}")
    
    async def _wait_process(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """等待进程结束"""
        pid = params.get('pid')
        timeout = params.get('timeout', 30)
        
        if pid is None:
            raise ValueError("Missing required parameter: pid")
        
        if pid in self.active_processes:
            proc_obj = self.active_processes[pid]
            try:
                returncode = proc_obj.wait(timeout=timeout)
                del self.active_processes[pid]
                
                return {
                    "pid": pid,
                    "returncode": returncode,
                    "completed": True
                }
            except subprocess.TimeoutExpired:
                return {
                    "pid": pid,
                    "completed": False,
                    "error": f"Timeout after {timeout}s"
                }
        else:
            # 检查系统进程
            try:
                proc = self.psutil.Process(pid)
                proc.wait(timeout=timeout)
                return {
                    "pid": pid,
                    "completed": True
                }
            except self.psutil.TimeoutExpired:
                return {
                    "pid": pid,
                    "completed": False,
                    "error": f"Timeout after {timeout}s"
                }
            except self.psutil.NoSuchProcess:
                return {
                    "pid": pid,
                    "completed": True,
                    "note": "Process already finished"
                }
    
    async def _get_output(self, params: Dict[str, Any]) -> Dict[str, str]:
        """获取进程输出"""
        pid = params.get('pid')
        
        if pid is None:
            raise ValueError("Missing required parameter: pid")
        
        if pid not in self.active_processes:
            raise ValueError(f"Process {pid} not found in active processes")
        
        proc = self.active_processes[pid]
        
        # 非阻塞读取
        stdout, stderr = proc.communicate() if proc.poll() is not None else ("", "")
        
        return {
            "pid": pid,
            "stdout": stdout,
            "stderr": stderr,
            "returncode": proc.returncode
        }
    
    # ============ 系统信息 ============
    
    async def _get_system_info(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """获取系统信息"""
        cpu_percent = self.psutil.cpu_percent(interval=0.1)
        memory = self.psutil.virtual_memory()
        disk = self.psutil.disk_usage('/')
        
        return {
            "cpu": {
                "percent": cpu_percent,
                "count": self.psutil.cpu_count(),
                "count_logical": self.psutil.cpu_count(logical=True)
            },
            "memory": {
                "total": memory.total,
                "available": memory.available,
                "percent": memory.percent,
                "used": memory.used,
                "free": memory.free
            },
            "disk": {
                "total": disk.total,
                "used": disk.used,
                "free": disk.free,
                "percent": disk.percent
            },
            "boot_time": self.psutil.boot_time()
        }
