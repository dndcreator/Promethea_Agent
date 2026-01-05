"""置信度分析器 - 识别AI回复中的不确定结论"""

import re
import math
import numpy as np
from typing import List, Dict, Tuple, Optional
from dataclasses import dataclass


@dataclass
class UncertainMark:
    """不确定标记"""
    text: str              # 句子内容
    start_pos: int         # 在完整文本中的起始位置
    end_pos: int           # 结束位置
    avg_prob: float        # 平均概率
    signal_score: float    # 信号综合得分
    level: str             # critical/high/medium
    signals: Dict[str, float]  # 触发的信号详情


class ConfidenceAnalyzer:
    """置信度分析器"""
    
    def __init__(self, config: dict = None):
        self.config = config or {}
        
        # 不确定性标志词（不是硬编码句式，而是信号词）
        self.uncertainty_markers = {
            '可能': 0.4, '也许': 0.4, '大概': 0.3,
            '取决于': 0.3, '一般来说': 0.2, '通常': 0.2,
            '建议': 0.3, '推荐': 0.3,
            '应该': 0.2, '最好': 0.2,
            '但': 0.1, '不过': 0.1,
            '或许': 0.3, '可以考虑': 0.3,
        }
    
    def analyze(self, response_text: str, logprobs_data: Optional[dict]) -> List[UncertainMark]:
        """
        分析回复，返回需要标记的不确定部分
        
        Args:
            response_text: AI回复文本
            logprobs_data: OpenAI API返回的logprobs数据
        
        Returns:
            标记列表
        """
        if not logprobs_data:
            return []
        
        # 1. 分句
        sentences = self._split_sentences(response_text)
        
        # 2. 为每个句子评分
        candidates = []
        for sentence_text, start_pos, end_pos in sentences:
            # 获取这句话的token概率
            token_probs, top_probs_list = self._get_sentence_probs(
                sentence_text, start_pos, end_pos, logprobs_data
            )
            
            if not token_probs:
                continue
            
            # 多信号评分
            should_mark, score, signals = self._evaluate_signals(
                sentence_text, token_probs, top_probs_list
            )
            
            if should_mark:
                avg_prob = np.mean(token_probs)
                level = self._classify_level(avg_prob, score)
                
                candidates.append(UncertainMark(
                    text=sentence_text,
                    start_pos=start_pos,
                    end_pos=end_pos,
                    avg_prob=avg_prob,
                    signal_score=score,
                    level=level,
                    signals=signals
                ))
        
        # 3. 按级别和密度过滤
        return self._filter_marks(candidates, response_text)
    
    def _split_sentences(self, text: str) -> List[Tuple[str, int, int]]:
        """分句，返回(句子, 起始位置, 结束位置)"""
        sentences = []
        # 按常见句子结束符分割
        pattern = r'([^。！？\n]+[。！？\n]|[^。！？\n]+$)'
        
        for match in re.finditer(pattern, text):
            sentence = match.group(0).strip()
            if len(sentence) > 5:  # 过滤太短的句子
                sentences.append((sentence, match.start(), match.end()))
        
        return sentences
    
    def _get_sentence_probs(
        self, 
        sentence: str, 
        start_pos: int, 
        end_pos: int, 
        logprobs_data: dict
    ) -> Tuple[List[float], List[list]]:
        """获取句子中每个token的概率（基于位置重叠检测）"""
        token_probs = []
        top_probs_list = []
        
        # logprobs_data 结构: {'content': [{'token': '...', 'logprob': -0.001, 'top_logprobs': [...]}]}
        content = logprobs_data.get('content', [])
        if not content:
            return token_probs, top_probs_list
        
        # 第一步：重建完整文本，记录每个token的位置
        accumulated_text = ""
        token_positions = []
        
        for token_data in content:
            token = token_data.get('token', '')
            token_start = len(accumulated_text)
            accumulated_text += token
            token_end = len(accumulated_text)
            token_positions.append((token_start, token_end, token_data))
        
        # 第二步：用区间重叠检测找出属于目标句子的tokens
        for token_start, token_end, token_data in token_positions:
            # 检查token区间和句子区间是否有重叠
            # 重叠条件：token_start < end_pos AND token_end > start_pos
            if token_start < end_pos and token_end > start_pos:
                logprob = token_data.get('logprob', 0)
                prob = math.exp(logprob) if logprob is not None else 0.5
                token_probs.append(prob)
                
                # 收集top候选概率
                top_logprobs = token_data.get('top_logprobs', [])
                if top_logprobs:
                    top_probs = [math.exp(t.get('logprob', -10)) for t in top_logprobs]
                    top_probs_list.append(top_probs)
        
        return token_probs, top_probs_list
    
    def _evaluate_signals(
        self, 
        sentence: str, 
        token_probs: List[float],
        top_probs_list: List[list]
    ) -> Tuple[bool, float, Dict[str, float]]:
        """
        多信号评分（不硬编码句式）
        
        Returns:
            (是否应该标记, 综合得分, 信号详情)
        """
        signals = {}
        
        # 信号1: 整体概率偏低
        avg_prob = np.mean(token_probs)
        if avg_prob < 0.4:
            signals['low_confidence'] = (0.4 - avg_prob) * 2
        
        # 信号2: 概率方差大（有些词特别不确定）
        prob_variance = np.var(token_probs)
        if prob_variance > 0.03:
            signals['high_variance'] = min(prob_variance * 10, 0.5)
        
        # 信号3: 包含不确定性标志词
        modal_score = 0
        for marker, weight in self.uncertainty_markers.items():
            if marker in sentence:
                modal_score += weight
        if modal_score > 0:
            signals['has_modal_word'] = min(modal_score, 0.6)
        
        # 信号4: 句子复杂度（长句+多分句）
        if len(sentence) > 30 and ('，' in sentence or '、' in sentence):
            signals['complex_structure'] = 0.2
        
        # 信号5: top候选差距小（概率分布平均 - 你提到的核心点）
        if top_probs_list:
            close_gaps = 0
            for top_probs in top_probs_list:
                if len(top_probs) >= 2:
                    gap = top_probs[0] - top_probs[1]
                    if gap < 0.15:  # 第一名和第二名差距<15%
                        close_gaps += 1
            
            if close_gaps / len(top_probs_list) > 0.3:  # 超过30%的token概率分布平均
                signals['probability_distributed'] = 0.4
        
        # 综合评分
        total_score = sum(signals.values())
        
        # 动态阈值：至少2个信号，且总分>0.6
        threshold = self.config.get('signal_threshold', 0.6)
        should_mark = len(signals) >= 2 and total_score > threshold
        
        return should_mark, total_score, signals
    
    def _classify_level(self, avg_prob: float, signal_score: float) -> str:
        """分级"""
        if avg_prob < 0.25 or signal_score > 1.0:
            return 'critical'  # 极不确定
        elif avg_prob < 0.35 or signal_score > 0.8:
            return 'high'      # 很不确定
        else:
            return 'medium'    # 不太确定
    
    def _filter_marks(self, candidates: List[UncertainMark], full_text: str) -> List[UncertainMark]:
        """
        按级别和密度过滤
        
        策略：
        1. 分级显示（根据配置）
        2. 密度控制（避免标记扎堆）
        """
        if not candidates:
            return []
        
        # 1. 按级别过滤
        show_critical = self.config.get('show_critical', True)
        show_high = self.config.get('show_high', True)
        show_medium = self.config.get('show_medium', False)
        
        selected = []
        for mark in candidates:
            if (mark.level == 'critical' and show_critical) or \
               (mark.level == 'high' and show_high) or \
               (mark.level == 'medium' and show_medium):
                selected.append(mark)
        
        # 2. 按得分排序（最不确定的优先）
        selected.sort(key=lambda m: m.signal_score, reverse=True)
        
        # 3. 密度控制（避免标记太近）
        min_distance = self.config.get('min_mark_distance', 80)
        filtered = []
        
        for mark in selected:
            # 检查是否和已选中的标记太近
            too_close = any(
                abs(mark.start_pos - existing.start_pos) < min_distance
                for existing in filtered
            )
            
            if not too_close:
                filtered.append(mark)
        
        return filtered


def create_analyzer(config: dict = None) -> ConfidenceAnalyzer:
    """工厂函数"""
    return ConfidenceAnalyzer(config)



