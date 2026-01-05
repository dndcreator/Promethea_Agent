"""性能指标收集器"""

import time
from typing import Dict, Any
from datetime import datetime


class MetricsCollector:
    """轻量级性能监控"""
    
    def __init__(self):
        self.stats = {
            'llm_calls': 0,
            'llm_total_time': 0.0,
            'prompt_tokens': 0,
            'completion_tokens': 0,
            'memory_recalls': 0,
            'memory_total_time': 0.0,
            'memory_items_recalled': 0,
            'sessions_created': 0,
            'messages_total': 0,
            'start_time': datetime.now()
        }
    
    def record_llm_call(self, duration: float, prompt_tokens: int = 0, completion_tokens: int = 0):
        """记录LLM调用"""
        self.stats['llm_calls'] += 1
        self.stats['llm_total_time'] += duration
        self.stats['prompt_tokens'] += prompt_tokens
        self.stats['completion_tokens'] += completion_tokens
    
    def record_memory_recall(self, duration: float, items_count: int = 0):
        """记录记忆召回"""
        self.stats['memory_recalls'] += 1
        self.stats['memory_total_time'] += duration
        self.stats['memory_items_recalled'] += items_count
    
    def record_message(self):
        """记录消息"""
        self.stats['messages_total'] += 1
    
    def record_session(self):
        """记录会话创建"""
        self.stats['sessions_created'] += 1
    
    def get_stats(self) -> Dict[str, Any]:
        """获取统计数据"""
        total_tokens = self.stats['prompt_tokens'] + self.stats['completion_tokens']
        
        # 估算成本（GPT-4为例：$0.03/1K prompt, $0.06/1K completion）
        estimated_cost = (
            self.stats['prompt_tokens'] / 1000 * 0.03 +
            self.stats['completion_tokens'] / 1000 * 0.06
        )
        
        uptime = (datetime.now() - self.stats['start_time']).total_seconds()
        
        return {
            'llm': {
                'calls': self.stats['llm_calls'],
                'avg_time_ms': round(self.stats['llm_total_time'] * 1000 / max(1, self.stats['llm_calls'])),
                'total_tokens': total_tokens,
                'prompt_tokens': self.stats['prompt_tokens'],
                'completion_tokens': self.stats['completion_tokens']
            },
            'memory': {
                'recalls': self.stats['memory_recalls'],
                'avg_time_ms': round(self.stats['memory_total_time'] * 1000 / max(1, self.stats['memory_recalls'])),
                'items_recalled': self.stats['memory_items_recalled']
            },
            'sessions': {
                'created': self.stats['sessions_created'],
                'messages': self.stats['messages_total']
            },
            'cost': {
                'estimated_usd': round(estimated_cost, 4)
            },
            'uptime_seconds': round(uptime)
        }
    
    def reset(self):
        """重置统计"""
        self.__init__()


# 全局实例
_metrics_collector = MetricsCollector()


def get_metrics_collector() -> MetricsCollector:
    """获取全局监控实例"""
    return _metrics_collector

