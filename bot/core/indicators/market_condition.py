# -*- coding: utf-8 -*-
"""
Phoenix v5.3.0 — 시장 상황 판단 모듈

시장 상황 분석 및 판단
- 추세 판단 (strong_uptrend, weak_uptrend, sideways, etc.)
- BTC 마켓 모드
- 시간대별 조정
- ATR 등급

기존 ai_decision.py: detect_market_condition() 통합
"""

import pandas as pd
from typing import Dict, Optional, Tuple
from dataclasses import dataclass, asdict
from datetime import datetime

from bot.utils.logger import get_logger
from bot.utils.cache import btc_context_cache, indicator_cache
from bot.utils.validators import safe_float

logger = get_logger("MarketCondition")


# =========================================================
# 데이터 클래스
# =========================================================

@dataclass
class MarketCondition:
    """시장 상황"""
    condition: str = "unknown"  # strong_uptrend, weak_uptrend, sideways, weak_downtrend, strong_downtrend, high_volatility
    trend: str = "neutral"  # bullish, bearish, neutral
    volatility: str = "normal"  # low, normal, high, extreme
    strength: int = 0  # -3 ~ +3
    confidence: float = 0.5  # 0.0 ~ 1.0
    reason: str = ""
    
    def to_dict(self) -> Dict:
        return asdict(self)
    
    @property
    def is_bullish(self) -> bool:
        return self.condition in ["strong_uptrend", "weak_uptrend"]
    
    @property
    def is_bearish(self) -> bool:
        return self.condition in ["strong_downtrend", "weak_downtrend"]
    
    @property
    def is_sideways(self) -> bool:
        return self.condition == "sideways"
    
    @property
    def is_high_volatility(self) -> bool:
        return self.volatility in ["high", "extreme"]


@dataclass
class BTCContext:
    """BTC 마켓 컨텍스트"""
    mode: str = "neutral"  # bull_strong, bull_normal, neutral, bear_normal, bear_strong
    trend: str = "neutral"  # bullish, bearish, neutral
    change_24h: float = 0.0
    volatility: str = "normal"
    position_mult: float = 1.0  # 포지션 크기 배수
    tp_mult: float = 1.0  # TP 배수
    strength_adjust: int = 0  # 신호 강도 조정
    
    def to_dict(self) -> Dict:
        return asdict(self)


@dataclass
class TimeContext:
    """시간대 컨텍스트"""
    hour: int = 12
    is_high_volatility_time: bool = False  # 22:00 ~ 02:00
    is_low_volatility_time: bool = False  # 06:00 ~ 09:00
    position_mult: float = 1.0
    reason: str = ""
    
    def to_dict(self) -> Dict:
        return asdict(self)


# =========================================================
# MarketConditionAnalyzer 클래스
# =========================================================

class MarketConditionAnalyzer:
    """
    시장 상황 분석기
    
    Usage:
        analyzer = MarketConditionAnalyzer()
        condition = analyzer.detect(indicators)
        btc_ctx = analyzer.get_btc_context(btc_df)
    """
    
    # 싱글톤 인스턴스
    _instance = None
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance
    
    def detect(
        self,
        indicators: Dict,
        btc_context: BTCContext = None,
    ) -> MarketCondition:
        """
        시장 상황 판단 (ai_decision.detect_market_condition 대체)
        
        Args:
            indicators: 지표 딕셔너리 (IndicatorResult.to_dict() 형식)
            btc_context: BTC 컨텍스트 (선택)
            
        Returns:
            MarketCondition
        """
        result = MarketCondition()
        
        if not indicators:
            return result
        
        # 지표 추출
        atr_pct = safe_float(indicators.get("atr_pct"), 2)
        ema_status = indicators.get("ema_status", "unknown")
        adx = safe_float(indicators.get("adx"), 20)
        rsi = safe_float(indicators.get("rsi"), 50)
        volume_ratio = safe_float(indicators.get("volume_ratio"), 1.0)
        
        # 변동성 판단
        if atr_pct > 7:
            result.volatility = "extreme"
        elif atr_pct > 5:
            result.volatility = "high"
        elif atr_pct > 3:
            result.volatility = "normal"
        else:
            result.volatility = "low"
        
        # 고변동성 우선 처리
        if atr_pct > 5:
            result.condition = "high_volatility"
            result.trend = "neutral"
            result.strength = 0
            result.confidence = 0.7
            result.reason = f"ATR {atr_pct:.1f}% (고변동성)"
            return result
        
        # EMA 기반 추세 판단
        if ema_status in ["uptrend", "golden_cross_recent"]:
            if adx >= 25:
                result.condition = "strong_uptrend"
                result.trend = "bullish"
                result.strength = 3
                result.confidence = 0.8
            else:
                result.condition = "weak_uptrend"
                result.trend = "bullish"
                result.strength = 1
                result.confidence = 0.6
            
            if ema_status == "golden_cross_recent":
                result.reason = "골든크로스 발생"
            else:
                result.reason = f"상승추세 (ADX: {adx:.0f})"
        
        elif ema_status in ["downtrend", "dead_cross_recent"]:
            if adx >= 25:
                result.condition = "strong_downtrend"
                result.trend = "bearish"
                result.strength = -3
                result.confidence = 0.8
            else:
                result.condition = "weak_downtrend"
                result.trend = "bearish"
                result.strength = -1
                result.confidence = 0.6
            
            if ema_status == "dead_cross_recent":
                result.reason = "데드크로스 발생"
            else:
                result.reason = f"하락추세 (ADX: {adx:.0f})"
        
        else:
            result.condition = "sideways"
            result.trend = "neutral"
            result.strength = 0
            result.confidence = 0.5
            result.reason = "횡보장"
        
        # RSI 극단값으로 추가 조정
        if rsi > 70:
            result.confidence *= 0.8  # 과매수 시 신뢰도 감소
            result.reason += f" | RSI 과매수 ({rsi:.0f})"
        elif rsi < 30:
            result.confidence *= 0.8
            result.reason += f" | RSI 과매도 ({rsi:.0f})"
        
        # 거래량 확인
        if volume_ratio > 2.0:
            result.confidence *= 1.1  # 거래량 급증 시 신뢰도 증가
            result.reason += f" | 거래량 급증 ({volume_ratio:.1f}x)"
        
        # BTC 영향 반영
        if btc_context:
            if btc_context.mode == "bear_strong" and result.is_bullish:
                result.confidence *= 0.7
                result.reason += " | BTC 약세 주의"
            elif btc_context.mode == "bull_strong" and result.is_bearish:
                result.confidence *= 0.7
                result.reason += " | BTC 강세 반전 가능"
        
        return result
    
    def get_btc_context(
        self,
        btc_df: pd.DataFrame,
        use_cache: bool = True,
    ) -> BTCContext:
        """
        BTC 마켓 컨텍스트 분석 (ai_decision.get_btc_context 대체)
        
        Args:
            btc_df: BTC OHLCV DataFrame
            use_cache: 캐시 사용 여부
            
        Returns:
            BTCContext
        """
        # 캐시 확인
        if use_cache:
            cached = btc_context_cache.get("btc_context")
            if cached is not None:
                return cached
        
        result = BTCContext()
        
        if btc_df is None or len(btc_df) < 50:
            return result
        
        try:
            close = btc_df["close"]
            current = safe_float(close.iloc[-1], 0)
            
            if current <= 0:
                return result
            
            # 24시간 변화율
            if len(btc_df) >= 48:
                price_24h = safe_float(close.iloc[-48], current)
                result.change_24h = ((current - price_24h) / price_24h * 100)
            
            # EMA 상태
            ema20 = close.ewm(span=20, adjust=False).mean().iloc[-1]
            ema50 = close.ewm(span=50, adjust=False).mean().iloc[-1]
            
            # ATR 기반 변동성
            high = btc_df["high"]
            low = btc_df["low"]
            tr = pd.concat([
                high - low,
                abs(high - close.shift(1)),
                abs(low - close.shift(1))
            ], axis=1).max(axis=1)
            atr = tr.rolling(14).mean().iloc[-1]
            atr_pct = atr / current * 100 if current > 0 else 0
            
            # 변동성 등급
            if atr_pct > 5:
                result.volatility = "high"
            elif atr_pct > 3:
                result.volatility = "normal"
            else:
                result.volatility = "low"
            
            # 모드 판단
            if result.change_24h > 5:
                result.mode = "bull_strong"
                result.trend = "bullish"
                result.position_mult = 1.2
                result.tp_mult = 1.3
                result.strength_adjust = 2
            elif result.change_24h > 2:
                result.mode = "bull_normal"
                result.trend = "bullish"
                result.position_mult = 1.1
                result.tp_mult = 1.1
                result.strength_adjust = 1
            elif result.change_24h < -5:
                result.mode = "bear_strong"
                result.trend = "bearish"
                result.position_mult = 0.7
                result.tp_mult = 0.8
                result.strength_adjust = -2
            elif result.change_24h < -2:
                result.mode = "bear_normal"
                result.trend = "bearish"
                result.position_mult = 0.9
                result.tp_mult = 0.9
                result.strength_adjust = -1
            else:
                result.mode = "neutral"
                result.trend = "neutral"
            
            # EMA 추세로 보정
            if ema20 > ema50 and result.mode.startswith("bear"):
                result.mode = "neutral"
                result.strength_adjust = 0
            elif ema20 < ema50 and result.mode.startswith("bull"):
                result.mode = "neutral"
                result.strength_adjust = 0
            
            # 캐싱
            if use_cache:
                btc_context_cache.set("btc_context", result, ttl=60)
            
            return result
            
        except Exception as e:
            logger.error(f"BTC 컨텍스트 분석 오류: {e}")
            return result
    
    def get_time_context(self, current_time: datetime = None) -> TimeContext:
        """
        시간대 컨텍스트 분석
        
        Args:
            current_time: 현재 시간 (기본: 현재)
            
        Returns:
            TimeContext
        """
        if current_time is None:
            current_time = datetime.now()
        
        result = TimeContext(hour=current_time.hour)
        
        hour = current_time.hour
        
        # 22:00 ~ 02:00 (고변동성 시간대)
        if hour >= 22 or hour < 2:
            result.is_high_volatility_time = True
            result.position_mult = 0.8  # 포지션 줄임
            result.reason = "야간 고변동성 시간대 (22~02시)"
        
        # 06:00 ~ 09:00 (저변동성 시간대)
        elif 6 <= hour < 9:
            result.is_low_volatility_time = True
            result.position_mult = 0.9
            result.reason = "새벽 저변동성 시간대 (06~09시)"
        
        else:
            result.reason = "일반 거래 시간대"
        
        return result
    
    def get_atr_grade(self, atr_pct: float) -> str:
        """
        ATR 등급 판단
        
        Args:
            atr_pct: ATR 백분율
            
        Returns:
            등급 (low, mid, high, extreme)
        """
        if atr_pct < 2:
            return "low"
        elif atr_pct < 4:
            return "mid"
        elif atr_pct < 7:
            return "high"
        else:
            return "extreme"
    
    def get_entry_ratio_by_condition(
        self,
        condition: MarketCondition,
    ) -> float:
        """
        시장 상황별 진입 비율 계산
        
        Args:
            condition: 시장 상황
            
        Returns:
            1차 진입 비율 (0.0 ~ 1.0)
        """
        # Config 값 참조 (없으면 기본값)
        ratios = {
            "strong_uptrend": 0.60,  # 강한 상승: 60%
            "weak_uptrend": 0.40,     # 약한 상승: 40%
            "sideways": 0.30,         # 횡보: 30%
            "weak_downtrend": 0.25,   # 약한 하락: 25%
            "strong_downtrend": 0.20, # 강한 하락: 20%
            "high_volatility": 0.25,  # 고변동성: 25%
        }
        
        return ratios.get(condition.condition, 0.30)


# =========================================================
# 싱글톤 인스턴스 및 편의 함수
# =========================================================

# 글로벌 인스턴스
_analyzer = MarketConditionAnalyzer()


def detect_market_condition(
    indicators: Dict,
    btc_context: BTCContext = None,
) -> str:
    """
    시장 상황 판단 (ai_decision 호환)
    
    Args:
        indicators: 지표 딕셔너리
        btc_context: BTC 컨텍스트
        
    Returns:
        상황 문자열 (strong_uptrend, weak_uptrend, sideways, etc.)
    """
    condition = _analyzer.detect(indicators, btc_context)
    return condition.condition


def detect_market_condition_full(
    indicators: Dict,
    btc_context: BTCContext = None,
) -> MarketCondition:
    """시장 상황 전체 분석"""
    return _analyzer.detect(indicators, btc_context)


def get_btc_context(btc_df: pd.DataFrame) -> Dict:
    """
    BTC 컨텍스트 조회 (ai_decision 호환)
    
    Args:
        btc_df: BTC OHLCV DataFrame
        
    Returns:
        컨텍스트 딕셔너리
    """
    ctx = _analyzer.get_btc_context(btc_df)
    return ctx.to_dict()


def get_btc_context_full(btc_df: pd.DataFrame) -> BTCContext:
    """BTC 컨텍스트 전체"""
    return _analyzer.get_btc_context(btc_df)


def get_time_context() -> TimeContext:
    """현재 시간대 컨텍스트"""
    return _analyzer.get_time_context()


def get_atr_grade(atr_pct: float) -> str:
    """ATR 등급"""
    return _analyzer.get_atr_grade(atr_pct)


def get_entry_ratio(condition: str) -> float:
    """
    상황별 진입 비율 (strategy_engine 호환)
    
    Args:
        condition: 시장 상황 문자열
        
    Returns:
        진입 비율 (0.0 ~ 1.0)
    """
    # 문자열을 MarketCondition으로 변환
    mc = MarketCondition(condition=condition)
    return _analyzer.get_entry_ratio_by_condition(mc)


def should_avoid_entry(
    condition: MarketCondition,
    btc_context: BTCContext = None,
) -> Tuple[bool, str]:
    """
    진입 회피 여부 판단
    
    Args:
        condition: 시장 상황
        btc_context: BTC 컨텍스트
        
    Returns:
        (회피 여부, 이유)
    """
    # 강한 하락장
    if condition.condition == "strong_downtrend":
        return True, "강한 하락장 진입 금지"
    
    # BTC 급락장
    if btc_context and btc_context.mode == "bear_strong":
        return True, "BTC 급락장 진입 금지"
    
    # 극심한 변동성
    if condition.volatility == "extreme":
        return True, "극심한 변동성 진입 금지"
    
    return False, ""


def invalidate_market_cache():
    """시장 상황 캐시 무효화"""
    btc_context_cache.delete("btc_context")
