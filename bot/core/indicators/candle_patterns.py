# -*- coding: utf-8 -*-
"""
Phoenix v5.3.2b — 캔들 패턴 감지 모듈 (개선 버전)

캔들스틱 패턴을 감지하여 AI 프롬프트 보조 지표로 활용합니다.

구현 패턴 (1단계):
- Bullish/Bearish Engulfing (상승/하락 잉걸핑)
- Hammer / Inverted Hammer (해머/역해머)
- Doji / Long-Legged Doji (도지/롱레그 도지)

🔥 v5.3.2b 개선사항:
- 잉걸핑 감지 마진 5% 추가 (감지율 향상)
- 해머 추세 확인 로직 개선 (연속 하락 캔들 비율)
- 롱레그 도지 구분 추가
- 엣지 케이스 처리 강화
- 성능 최적화 (데이터 미리 추출)

v5.3.2 신규 생성
"""

import pandas as pd
from typing import List, Dict, Optional, Tuple
from dataclasses import dataclass

from bot.utils.logger import get_logger

logger = get_logger("CandlePatterns")


# =========================================================
# 데이터 클래스
# =========================================================

@dataclass
class CandlePattern:
    """캔들 패턴 정보"""
    pattern: str        # 영문 패턴명
    name_kr: str        # 한글 패턴명
    signal: str         # buy / sell / neutral
    strength: float     # 신호 강도 (0.0 ~ 1.0)
    description: str    # 패턴 설명
    
    def to_dict(self) -> Dict:
        return {
            "pattern": self.pattern,
            "name_kr": self.name_kr,
            "signal": self.signal,
            "strength": self.strength,
            "description": self.description,
        }


# =========================================================
# 캔들 패턴 감지기
# =========================================================

class CandlePatternDetector:
    """
    캔들 패턴 감지기 (v5.3.2b 개선 버전)
    
    OHLCV DataFrame을 받아 캔들스틱 패턴을 감지합니다.
    감지된 패턴은 AI 프롬프트의 보조 지표로 활용됩니다.
    """
    
    # 패턴 감지에 필요한 최소 캔들 수
    MIN_CANDLES = 5
    
    # 도지 몸통 비율 임계값
    DOJI_BODY_RATIO = 0.10  # 10%
    
    # 해머 그림자 비율 임계값
    HAMMER_SHADOW_RATIO = 0.60   # 60%
    HAMMER_BODY_MAX_RATIO = 0.30  # 30%
    HAMMER_OPPOSITE_MAX = 0.10    # 10%
    
    # 🔥 v5.3.2b: 잉걸핑 마진 (5%)
    ENGULFING_MARGIN_RATIO = 0.05
    
    # 🔥 v5.3.2b: 롱레그 도지 그림자 임계값
    LONG_LEG_SHADOW_RATIO = 0.30  # 30%
    
    def __init__(self):
        self.last_patterns: List[CandlePattern] = []
    
    def detect_all(self, df: pd.DataFrame) -> List[Dict]:
        """
        모든 캔들 패턴 감지
        
        Args:
            df: OHLCV DataFrame (open, high, low, close, volume 컬럼 필요)
                최소 5개 이상의 캔들 필요
        
        Returns:
            감지된 패턴 리스트
            [{"pattern": "bullish_engulfing", "signal": "buy", "strength": 0.8, ...}, ...]
        """
        patterns = []
        
        if df is None or len(df) < self.MIN_CANDLES:
            return patterns
        
        # DataFrame 컬럼 검증
        required_cols = ['open', 'high', 'low', 'close']
        if not all(col in df.columns for col in required_cols):
            logger.warning("[CandlePattern] 필수 컬럼 누락 (open/high/low/close)")
            return patterns
        
        try:
            # 🔥 v5.3.2b: 엣지 케이스 검증
            if not self._validate_data(df):
                return patterns
            
            # 🔥 v5.3.2b: 성능 최적화 - 데이터 미리 추출
            candle_data = self._extract_candle_data(df)
            
            # === 잉걸핑 패턴 ===
            bullish_eng = self._detect_bullish_engulfing(candle_data)
            if bullish_eng:
                patterns.append(bullish_eng.to_dict())
            
            bearish_eng = self._detect_bearish_engulfing(candle_data)
            if bearish_eng:
                patterns.append(bearish_eng.to_dict())
            
            # === 해머 패턴 ===
            hammer = self._detect_hammer(candle_data, df)
            if hammer:
                patterns.append(hammer.to_dict())
            
            inv_hammer = self._detect_inverted_hammer(candle_data, df)
            if inv_hammer:
                patterns.append(inv_hammer.to_dict())
            
            # === 도지 패턴 ===
            doji = self._detect_doji(candle_data)
            if doji:
                patterns.append(doji.to_dict())
            
            # 결과 캐시
            self.last_patterns = [CandlePattern(**p) for p in patterns]
            
            if patterns:
                pattern_names = [p['name_kr'] for p in patterns]
                logger.debug(f"[CandlePattern] 감지됨: {', '.join(pattern_names)}")
            
        except Exception as e:
            logger.error(f"[CandlePattern] 감지 오류: {e}")
        
        return patterns
    
    # =========================================================
    # 🔥 v5.3.2b: 데이터 검증 및 추출
    # =========================================================
    
    def _validate_data(self, df: pd.DataFrame) -> bool:
        """
        🔥 v5.3.2b: 데이터 유효성 검증
        
        엣지 케이스 필터링
        """
        try:
            curr_close = float(df.iloc[-1]['close'])
            prev_close = float(df.iloc[-2]['close'])
            
            # 1. 가격이 0인 경우
            if curr_close == 0 or prev_close == 0:
                logger.debug("[CandlePattern] 가격 0 감지, 스킵")
                return False
            
            # 2. 동일 가격 캔들 연속 (거래 없음)
            last_two = df.iloc[-2:]
            if last_two['high'].std() == 0 and last_two['low'].std() == 0:
                logger.debug("[CandlePattern] 동일 가격 연속, 스킵")
                return False
            
            # 3. 비정상적 스파이크 필터링 (50% 이상 변동)
            price_change = abs(curr_close / prev_close - 1)
            if price_change > 0.5:
                logger.warning(f"[CandlePattern] 비정상 가격 변동 감지: {price_change:.1%}, 스킵")
                return False
            
            return True
            
        except Exception as e:
            logger.debug(f"[CandlePattern] 검증 오류: {e}")
            return False
    
    def _extract_candle_data(self, df: pd.DataFrame) -> Dict:
        """
        🔥 v5.3.2b: 캔들 데이터 미리 추출 (성능 최적화)
        
        반복 접근 방지를 위해 한 번에 추출
        """
        prev = df.iloc[-2]
        curr = df.iloc[-1]
        
        prev_o = float(prev['open'])
        prev_h = float(prev['high'])
        prev_l = float(prev['low'])
        prev_c = float(prev['close'])
        
        curr_o = float(curr['open'])
        curr_h = float(curr['high'])
        curr_l = float(curr['low'])
        curr_c = float(curr['close'])
        
        # 공통 계산
        prev_body = abs(prev_c - prev_o)
        curr_body = abs(curr_c - curr_o)
        curr_total = curr_h - curr_l
        
        curr_lower_shadow = min(curr_o, curr_c) - curr_l
        curr_upper_shadow = curr_h - max(curr_o, curr_c)
        
        return {
            "prev": {"open": prev_o, "high": prev_h, "low": prev_l, "close": prev_c, "body": prev_body},
            "curr": {"open": curr_o, "high": curr_h, "low": curr_l, "close": curr_c, "body": curr_body,
                     "total": curr_total, "lower_shadow": curr_lower_shadow, "upper_shadow": curr_upper_shadow},
        }
    
    def _is_downtrend(self, df: pd.DataFrame, lookback: int = 3) -> bool:
        """
        🔥 v5.3.2b: 하락 추세 확인 (개선됨)
        
        최근 N개 캔들 중 하락 캔들이 60% 이상인지 확인
        """
        if len(df) < lookback + 2:
            return False
        
        recent = df.iloc[-(lookback+1):-1]
        bearish_count = sum(recent['close'] < recent['open'])
        return bearish_count >= lookback * 0.6
    
    def _is_uptrend(self, df: pd.DataFrame, lookback: int = 3) -> bool:
        """
        🔥 v5.3.2b: 상승 추세 확인
        
        최근 N개 캔들 중 상승 캔들이 60% 이상인지 확인
        """
        if len(df) < lookback + 2:
            return False
        
        recent = df.iloc[-(lookback+1):-1]
        bullish_count = sum(recent['close'] > recent['open'])
        return bullish_count >= lookback * 0.6
    
    # =========================================================
    # 개별 패턴 감지 메서드
    # =========================================================
    
    def _detect_bullish_engulfing(self, data: Dict) -> Optional[CandlePattern]:
        """
        상승 잉걸핑 감지
        
        조건:
        1. 전일: 음봉 (close < open)
        2. 금일: 양봉 (close > open)
        3. 금일 몸통이 전일 몸통 완전히 감싸기 (🔥 5% 마진 허용)
        """
        prev = data["prev"]
        curr = data["curr"]
        
        # 전일 음봉, 금일 양봉
        prev_bearish = prev["close"] < prev["open"]
        curr_bullish = curr["close"] > curr["open"]
        
        if not (prev_bearish and curr_bullish):
            return None
        
        # 🔥 v5.3.2b: 5% 마진 허용 (감지율 향상)
        margin = prev["body"] * self.ENGULFING_MARGIN_RATIO
        
        engulfing = (curr["open"] <= prev["close"] + margin) and (curr["close"] >= prev["open"] - margin)
        
        if not engulfing:
            return None
        
        # 강도 계산: 금일 몸통 크기 / 전일 몸통 크기
        if prev["body"] > 0:
            body_ratio = curr["body"] / prev["body"]
            strength = min(0.9, 0.7 + (body_ratio - 1) * 0.1)
        else:
            strength = 0.75
        
        return CandlePattern(
            pattern="bullish_engulfing",
            name_kr="상승 잉걸핑",
            signal="buy",
            strength=round(strength, 2),
            description="음봉 후 양봉이 완전히 감싸는 강한 상승 반전 신호"
        )
    
    def _detect_bearish_engulfing(self, data: Dict) -> Optional[CandlePattern]:
        """
        하락 잉걸핑 감지
        
        조건:
        1. 전일: 양봉 (close > open)
        2. 금일: 음봉 (close < open)
        3. 금일 몸통이 전일 몸통 완전히 감싸기 (🔥 5% 마진 허용)
        """
        prev = data["prev"]
        curr = data["curr"]
        
        # 전일 양봉, 금일 음봉
        prev_bullish = prev["close"] > prev["open"]
        curr_bearish = curr["close"] < curr["open"]
        
        if not (prev_bullish and curr_bearish):
            return None
        
        # 🔥 v5.3.2b: 5% 마진 허용
        margin = prev["body"] * self.ENGULFING_MARGIN_RATIO
        
        engulfing = (curr["open"] >= prev["close"] - margin) and (curr["close"] <= prev["open"] + margin)
        
        if not engulfing:
            return None
        
        # 강도 계산
        if prev["body"] > 0:
            body_ratio = curr["body"] / prev["body"]
            strength = min(0.9, 0.7 + (body_ratio - 1) * 0.1)
        else:
            strength = 0.75
        
        return CandlePattern(
            pattern="bearish_engulfing",
            name_kr="하락 잉걸핑",
            signal="sell",
            strength=round(strength, 2),
            description="양봉 후 음봉이 완전히 감싸는 강한 하락 반전 신호"
        )
    
    def _detect_hammer(self, data: Dict, df: pd.DataFrame) -> Optional[CandlePattern]:
        """
        해머 감지
        
        조건:
        1. 긴 아래꼬리 (전체 길이의 60% 이상)
        2. 짧은 몸통 (전체 길이의 30% 이하)
        3. 윗꼬리 거의 없음 (전체 길이의 10% 이하)
        4. 🔥 v5.3.2b: 하락 추세 후 출현 시 신뢰도 증가
        """
        curr = data["curr"]
        
        if curr["total"] == 0:
            return None
        
        body_ratio = curr["body"] / curr["total"]
        lower_ratio = curr["lower_shadow"] / curr["total"]
        upper_ratio = curr["upper_shadow"] / curr["total"]
        
        # 해머 조건 검증
        is_hammer = (
            lower_ratio >= self.HAMMER_SHADOW_RATIO and
            body_ratio <= self.HAMMER_BODY_MAX_RATIO and
            upper_ratio <= self.HAMMER_OPPOSITE_MAX
        )
        
        if not is_hammer:
            return None
        
        # 강도 계산: 아래꼬리가 길수록 강함
        strength = min(0.85, 0.6 + (lower_ratio - 0.6) * 0.5)
        
        # 🔥 v5.3.2b: 하락 추세 확인 (개선된 로직)
        if self._is_downtrend(df, lookback=3):
            strength = min(0.9, strength + 0.1)
        
        return CandlePattern(
            pattern="hammer",
            name_kr="해머",
            signal="buy",
            strength=round(strength, 2),
            description="긴 아래꼬리의 상승 반전 신호 (하락 추세에서 유효)"
        )
    
    def _detect_inverted_hammer(self, data: Dict, df: pd.DataFrame) -> Optional[CandlePattern]:
        """
        역해머 감지
        
        조건:
        1. 긴 윗꼬리 (전체 길이의 60% 이상)
        2. 짧은 몸통 (전체 길이의 30% 이하)
        3. 아래꼬리 거의 없음 (전체 길이의 10% 이하)
        """
        curr = data["curr"]
        
        if curr["total"] == 0:
            return None
        
        body_ratio = curr["body"] / curr["total"]
        lower_ratio = curr["lower_shadow"] / curr["total"]
        upper_ratio = curr["upper_shadow"] / curr["total"]
        
        # 역해머 조건 검증
        is_inv_hammer = (
            upper_ratio >= self.HAMMER_SHADOW_RATIO and
            body_ratio <= self.HAMMER_BODY_MAX_RATIO and
            lower_ratio <= self.HAMMER_OPPOSITE_MAX
        )
        
        if not is_inv_hammer:
            return None
        
        # 강도 계산: 윗꼬리가 길수록 강함 (해머보다 약간 낮음)
        strength = min(0.75, 0.5 + (upper_ratio - 0.6) * 0.5)
        
        # 🔥 v5.3.2b: 하락 추세 확인
        if self._is_downtrend(df, lookback=3):
            strength = min(0.8, strength + 0.05)
        
        return CandlePattern(
            pattern="inverted_hammer",
            name_kr="역해머",
            signal="buy",
            strength=round(strength, 2),
            description="긴 윗꼬리의 상승 반전 신호 (해머보다 약함)"
        )
    
    def _detect_doji(self, data: Dict) -> Optional[CandlePattern]:
        """
        도지 감지 (🔥 v5.3.2b: 롱레그 도지 구분 추가)
        
        조건:
        1. 몸통이 전체 길이의 10% 이하 (시가 ≈ 종가)
        2. 🔥 롱레그 도지: 양쪽 그림자 모두 30% 이상
        """
        curr = data["curr"]
        
        if curr["total"] == 0:
            # 완전한 도지 (high = low = open = close)
            return CandlePattern(
                pattern="doji",
                name_kr="도지",
                signal="neutral",
                strength=0.5,
                description="시가와 종가가 동일한 추세 전환 경고 신호"
            )
        
        body_ratio = curr["body"] / curr["total"]
        
        if body_ratio > self.DOJI_BODY_RATIO:
            return None
        
        lower_ratio = curr["lower_shadow"] / curr["total"]
        upper_ratio = curr["upper_shadow"] / curr["total"]
        
        # 🔥 v5.3.2b: 롱레그 도지 구분
        if lower_ratio >= self.LONG_LEG_SHADOW_RATIO and upper_ratio >= self.LONG_LEG_SHADOW_RATIO:
            # 양쪽 그림자가 모두 긴 경우 → 롱레그 도지 (더 강한 신호)
            strength = min(0.8, 0.5 + (self.DOJI_BODY_RATIO - body_ratio) * 3)
            return CandlePattern(
                pattern="long_legged_doji",
                name_kr="롱레그 도지",
                signal="neutral",
                strength=round(strength, 2),
                description="양쪽 그림자가 긴 강한 추세 전환 신호"
            )
        
        # 일반 도지
        strength = min(0.7, 0.4 + (self.DOJI_BODY_RATIO - body_ratio) * 3)
        
        return CandlePattern(
            pattern="doji",
            name_kr="도지",
            signal="neutral",
            strength=round(strength, 2),
            description="시가와 종가가 거의 같은 추세 전환 경고 신호"
        )
    
    # =========================================================
    # 유틸리티 메서드
    # =========================================================
    
    def get_pattern_summary(self, patterns: List[Dict]) -> str:
        """
        AI 프롬프트용 요약 문자열 생성
        
        Args:
            patterns: detect_all()의 반환값
            
        Returns:
            "캔들패턴: 상승 잉걸핑(buy, 80%), 해머(buy, 70%)"
        """
        if not patterns:
            return ""
        
        summaries = []
        for p in patterns:
            strength_pct = int(p['strength'] * 100)
            summaries.append(f"{p['name_kr']}({p['signal']}, {strength_pct}%)")
        
        return "캔들패턴: " + ", ".join(summaries)
    
    def get_dominant_signal(self, patterns: List[Dict]) -> Optional[Dict]:
        """
        가장 강한 신호 반환
        
        Args:
            patterns: detect_all()의 반환값
            
        Returns:
            가장 강한 패턴 또는 None
        """
        if not patterns:
            return None
        
        # neutral 제외하고 가장 강한 신호
        non_neutral = [p for p in patterns if p['signal'] != 'neutral']
        
        if non_neutral:
            return max(non_neutral, key=lambda x: x['strength'])
        
        return max(patterns, key=lambda x: x['strength'])


# =========================================================
# 싱글톤 인스턴스 및 편의 함수
# =========================================================

_detector: Optional[CandlePatternDetector] = None


def get_detector() -> CandlePatternDetector:
    """싱글톤 감지기 반환"""
    global _detector
    if _detector is None:
        _detector = CandlePatternDetector()
    return _detector


def detect_patterns(df: pd.DataFrame) -> List[Dict]:
    """
    캔들 패턴 감지 편의 함수
    
    Args:
        df: OHLCV DataFrame
        
    Returns:
        감지된 패턴 리스트
    """
    return get_detector().detect_all(df)


def get_pattern_summary(df: pd.DataFrame) -> str:
    """
    AI 프롬프트용 패턴 요약 편의 함수
    
    Args:
        df: OHLCV DataFrame
        
    Returns:
        "캔들패턴: 상승 잉걸핑(buy, 80%)" 형태 문자열
    """
    detector = get_detector()
    patterns = detector.detect_all(df)
    return detector.get_pattern_summary(patterns)


def get_patterns_for_ai(df: pd.DataFrame) -> Optional[str]:
    """
    AI 프롬프트용 패턴 정보 반환
    
    패턴이 없으면 None, 있으면 요약 문자열 반환
    
    Args:
        df: OHLCV DataFrame
        
    Returns:
        패턴 요약 문자열 또는 None
    """
    summary = get_pattern_summary(df)
    return summary if summary else None
