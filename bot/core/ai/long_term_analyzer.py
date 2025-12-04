# -*- coding: utf-8 -*-
"""
Phoenix v5.3.0 — 장기 추세 분석기

일봉/주봉 기반 장기 추세 분석 및 ATR 기반 동적 SL 계산을 담당합니다.

🔥 v5.3.0:
- ai_decision.py에서 분리
- analyze_long_term_trend() 메서드
- calculate_dynamic_sl() 메서드
"""

from typing import Dict, Optional
from dataclasses import dataclass, field

from config import Config
from bot.utils.logger import get_logger

logger = get_logger("AI.LongTermAnalyzer")


# =========================================================
# 데이터 클래스
# =========================================================

@dataclass
class LongTermTrend:
    """장기 추세 분석 결과"""
    trend: str = "neutral"  # strong_bull, bull, neutral, bear, strong_bear
    trend_strength: float = 0.5  # 0.0 ~ 1.0
    weekly_momentum: str = "횡보"  # 상승, 횡보, 하락
    daily_momentum: str = "횡보"  # 상승, 횡보, 하락
    recommendation: str = "관망"  # 적극 매수, 매수, 관망, 매도, 적극 매도
    sl_adjustment: float = 1.0  # SL 조정 배수 (1.0 ~ 1.5)
    
    def to_dict(self) -> Dict:
        return {
            "trend": self.trend,
            "trend_strength": self.trend_strength,
            "weekly_momentum": self.weekly_momentum,
            "daily_momentum": self.daily_momentum,
            "recommendation": self.recommendation,
            "sl_adjustment": self.sl_adjustment,
        }


# =========================================================
# 장기 추세 분석기
# =========================================================

class LongTermAnalyzer:
    """
    장기 추세 분석기
    
    일봉과 주봉 데이터를 분석하여 장기 추세를 판단하고,
    ATR 기반으로 적절한 SL을 계산합니다.
    """
    
    @classmethod
    def analyze_trend(
        cls,
        indicators_daily: Optional[Dict] = None,
        indicators_weekly: Optional[Dict] = None,
    ) -> LongTermTrend:
        """
        일봉/주봉 기반 장기 추세 분석
        
        Args:
            indicators_daily: 일봉 지표
            indicators_weekly: 주봉 지표
            
        Returns:
            LongTermTrend 객체
        """
        result = LongTermTrend()
        
        # 주봉 분석
        if indicators_weekly:
            weekly_ema = indicators_weekly.get("ema_status", "unknown")
            weekly_rsi = indicators_weekly.get("rsi", 50)
            weekly_adx = indicators_weekly.get("adx", 20)
            
            if weekly_ema in ["uptrend", "golden_cross_recent"]:
                result.weekly_momentum = "상승"
                if weekly_adx >= 25:
                    result.trend = "strong_bull"
                    result.trend_strength = 0.9
                else:
                    result.trend = "bull"
                    result.trend_strength = 0.7
            elif weekly_ema in ["downtrend", "dead_cross_recent"]:
                result.weekly_momentum = "하락"
                if weekly_adx >= 25:
                    result.trend = "strong_bear"
                    result.trend_strength = 0.9
                else:
                    result.trend = "bear"
                    result.trend_strength = 0.7
        
        # 일봉 분석으로 미세 조정
        if indicators_daily:
            daily_ema = indicators_daily.get("ema_status", "unknown")
            daily_rsi = indicators_daily.get("rsi", 50)
            
            if daily_ema in ["uptrend", "golden_cross_recent"]:
                result.daily_momentum = "상승"
            elif daily_ema in ["downtrend", "dead_cross_recent"]:
                result.daily_momentum = "하락"
            
            # 일봉/주봉 방향 일치 시 신호 강화
            if result.weekly_momentum == result.daily_momentum:
                result.trend_strength = min(result.trend_strength + 0.1, 1.0)
            
            # 일봉/주봉 방향 불일치 시 신호 약화
            elif result.weekly_momentum != "횡보" and result.daily_momentum != "횡보":
                if result.weekly_momentum != result.daily_momentum:
                    result.trend_strength = max(result.trend_strength - 0.2, 0.3)
                    result.sl_adjustment = 1.3  # SL 확대
        
        # 추천 결정
        if result.trend == "strong_bull":
            result.recommendation = "적극 매수"
        elif result.trend == "bull":
            result.recommendation = "매수"
        elif result.trend == "strong_bear":
            result.recommendation = "적극 매도"
            result.sl_adjustment = 1.5  # 하락장 SL 확대
        elif result.trend == "bear":
            result.recommendation = "매도"
            result.sl_adjustment = 1.3
        else:
            result.recommendation = "관망"
        
        return result
    
    @classmethod
    def calculate_dynamic_sl(
        cls,
        atr_pct: float,
        market_condition: str,
        long_term_trend: Optional[Dict] = None,
    ) -> float:
        """
        ATR 기반 동적 SL 계산
        
        Args:
            atr_pct: ATR 퍼센트 (예: 3.5)
            market_condition: 시장 상황
            long_term_trend: 장기 추세 분석 결과 딕셔너리
            
        Returns:
            SL 비율 (예: 0.045 = 4.5%)
        """
        sl_min = getattr(Config, 'AI_SL_MIN', 0.03)
        sl_max = getattr(Config, 'AI_SL_MAX', 0.07)
        
        # ATR 등급별 배수
        if atr_pct <= 2:
            multiplier = getattr(Config, 'ATR_SL_MULTIPLIER_LOW', 2.0)
        elif atr_pct <= 4:
            multiplier = getattr(Config, 'ATR_SL_MULTIPLIER_MEDIUM', 1.8)
        elif atr_pct <= 6:
            multiplier = getattr(Config, 'ATR_SL_MULTIPLIER_HIGH', 1.5)
        else:
            multiplier = getattr(Config, 'ATR_SL_MULTIPLIER_EXTREME', 1.2)
        
        # 기본 SL = ATR × 배수
        base_sl = (atr_pct / 100) * multiplier
        
        # 장기 추세 조정
        sl_adjustment = 1.0
        if long_term_trend:
            sl_adjustment = long_term_trend.get("sl_adjustment", 1.0)
        adjusted_sl = base_sl * sl_adjustment
        
        # 시장 상황별 추가 조정
        if market_condition == "high_volatility":
            adjusted_sl *= 1.2
        elif market_condition == "strong_downtrend":
            adjusted_sl *= 1.3
        
        # 범위 제한
        final_sl = max(sl_min, min(adjusted_sl, sl_max))
        
        return round(final_sl, 4)
    
    @classmethod
    def is_trend_aligned(
        cls,
        long_term_trend: Optional[Dict] = None,
        short_term_condition: str = "sideways",
    ) -> bool:
        """
        장기 추세와 단기 상황의 정렬 여부 확인
        
        Args:
            long_term_trend: 장기 추세 분석 결과
            short_term_condition: 단기 시장 상황
            
        Returns:
            정렬 여부 (True = 정렬됨)
        """
        if not long_term_trend:
            return False
        
        trend = long_term_trend.get("trend", "neutral")
        
        # 장기 상승 + 단기 상승 = 정렬
        if trend in ["strong_bull", "bull"]:
            return short_term_condition in ["strong_uptrend", "weak_uptrend"]
        
        # 장기 하락 + 단기 하락 = 정렬
        if trend in ["strong_bear", "bear"]:
            return short_term_condition in ["strong_downtrend", "weak_downtrend"]
        
        # 장기 중립 + 단기 횡보 = 정렬
        if trend == "neutral":
            return short_term_condition in ["sideways", "high_volatility"]
        
        return False
    
    @classmethod
    def should_avoid_entry(
        cls,
        long_term_trend: Optional[Dict] = None,
    ) -> tuple:
        """
        진입 회피 여부 판단
        
        Args:
            long_term_trend: 장기 추세 분석 결과
            
        Returns:
            (회피 여부, 이유)
        """
        if not long_term_trend:
            return (False, "")
        
        trend = long_term_trend.get("trend", "neutral")
        weekly_momentum = long_term_trend.get("weekly_momentum", "횡보")
        daily_momentum = long_term_trend.get("daily_momentum", "횡보")
        
        # 주봉 하락 추세
        if trend in ["bear", "strong_bear"]:
            return (True, f"주봉 하락 추세 ({long_term_trend.get('recommendation', '매도')})")
        
        # 주봉/일봉 방향 불일치
        if weekly_momentum != "횡보" and daily_momentum != "횡보":
            if weekly_momentum != daily_momentum:
                return (True, f"주봉({weekly_momentum})/일봉({daily_momentum}) 방향 불일치")
        
        return (False, "")


# =========================================================
# 편의 함수
# =========================================================

def analyze_long_term_trend(
    indicators_daily: Optional[Dict] = None,
    indicators_weekly: Optional[Dict] = None,
) -> Dict:
    """
    장기 추세 분석 (편의 함수)
    
    기존 AIDecisionEngine.analyze_long_term_trend()와 동일한 시그니처
    
    Returns:
        딕셔너리 형태의 분석 결과
    """
    result = LongTermAnalyzer.analyze_trend(indicators_daily, indicators_weekly)
    return result.to_dict()


def calculate_dynamic_sl(
    atr_pct: float,
    market_condition: str,
    long_term_trend: Optional[Dict] = None,
) -> float:
    """
    동적 SL 계산 (편의 함수)
    
    기존 AIDecisionEngine.calculate_dynamic_sl()과 동일한 시그니처
    """
    return LongTermAnalyzer.calculate_dynamic_sl(
        atr_pct, market_condition, long_term_trend
    )


def should_avoid_entry(long_term_trend: Optional[Dict] = None) -> tuple:
    """진입 회피 여부 판단 (편의 함수)"""
    return LongTermAnalyzer.should_avoid_entry(long_term_trend)


def is_trend_aligned(
    long_term_trend: Optional[Dict] = None,
    short_term_condition: str = "sideways",
) -> bool:
    """추세 정렬 여부 확인 (편의 함수)"""
    return LongTermAnalyzer.is_trend_aligned(long_term_trend, short_term_condition)
