# -*- coding: utf-8 -*-
"""
Phoenix v5.3.0 — 통합 기술적 지표 모듈

모든 기술적 지표 계산을 단일 모듈에서 관리
- RSI, EMA, MACD, Bollinger Bands
- ATR, ADX
- Volume 분석
- 지표 결과 캐싱

기존 중복 제거:
- ai_decision.py: calculate_indicators()
- strategy_engine.py: rsi(), ema(), macd(), bollinger(), calculate_atr()
"""

import numpy as np
import pandas as pd
import ta
from typing import Dict, Optional, Tuple
from dataclasses import dataclass, asdict

from bot.utils.logger import get_logger
from bot.utils.cache import indicator_cache, cached
from bot.utils.decorators import safe_execute
from bot.utils.validators import safe_float

logger = get_logger("Indicators")


# =========================================================
# 데이터 클래스
# =========================================================

@dataclass
class IndicatorResult:
    """기술적 지표 계산 결과"""
    # 기본 지표
    rsi: float = 50.0
    rsi_prev: float = 50.0
    
    # EMA
    ema20: float = 0.0
    ema50: float = 0.0
    ema_status: str = "unknown"  # uptrend, downtrend, golden_cross_recent, dead_cross_recent
    price_vs_ema20_pct: float = 0.0
    
    # MACD
    macd_line: float = 0.0
    macd_signal: float = 0.0
    macd_hist: float = 0.0
    macd_cross: str = "none"  # bullish, bearish, none
    
    # Bollinger Bands
    bb_upper: float = 0.0
    bb_middle: float = 0.0
    bb_lower: float = 0.0
    bb_position: str = "middle"  # upper, middle, lower
    bb_width: float = 0.0
    
    # ATR / ADX
    atr: float = 0.0
    atr_pct: float = 0.0
    adx: float = 20.0
    
    # Stochastic RSI
    stoch_rsi: float = 0.5
    stoch_rsi_k: float = 0.5
    stoch_rsi_d: float = 0.5
    
    # Volume
    volume_ratio: float = 1.0
    volume_sma20: float = 0.0
    vwap: float = 0.0
    
    # 가격 정보
    current_price: float = 0.0
    change_24h: float = 0.0
    change_1h: float = 0.0
    
    # 유효성
    is_valid: bool = True
    
    def to_dict(self) -> Dict:
        """딕셔너리로 변환 (반올림 적용)"""
        return {
            "rsi": round(self.rsi, 1),
            "rsi_prev": round(self.rsi_prev, 1),
            "ema20": round(self.ema20, 2),
            "ema50": round(self.ema50, 2),
            "ema_status": self.ema_status,
            "price_vs_ema20_pct": round(self.price_vs_ema20_pct, 2),
            "macd_line": round(self.macd_line, 4),
            "macd_signal": round(self.macd_signal, 4),
            "macd_hist": round(self.macd_hist, 4),
            "macd_cross": self.macd_cross,
            "bb_upper": round(self.bb_upper, 2),
            "bb_middle": round(self.bb_middle, 2),
            "bb_lower": round(self.bb_lower, 2),
            "bb_position": self.bb_position,
            "bb_width": round(self.bb_width, 4),
            "atr": round(self.atr, 2),
            "atr_pct": round(self.atr_pct, 2),
            "adx": round(self.adx, 1),
            "stoch_rsi": round(self.stoch_rsi, 2),
            "volume_ratio": round(self.volume_ratio, 2),
            "vwap": round(self.vwap, 2),
            "current_price": round(self.current_price, 2),
            "change_24h": round(self.change_24h, 2),
            "change_1h": round(self.change_1h, 2),
            "is_valid": self.is_valid,
        }
    
    def to_ai_summary(self) -> Dict:
        """AI 분석용 요약 (기존 ai_decision 호환)"""
        return {
            "rsi": round(self.rsi, 1),
            "ema_status": self.ema_status,
            "ema20": round(self.ema20, 2),
            "ema50": round(self.ema50, 2),
            "price_vs_ema20_pct": round(self.price_vs_ema20_pct, 2),
            "atr": round(self.atr, 2),
            "atr_pct": round(self.atr_pct, 2),
            "adx": round(self.adx, 1),
            "change_24h": round(self.change_24h, 2),
            "current_price": round(self.current_price, 2),
            "volume_ratio": round(self.volume_ratio, 2),
        }


@dataclass
class ATRInfo:
    """ATR 상세 정보"""
    value: float = 0.0
    pct: float = 0.0
    grade: str = "mid"  # low, mid, high, extreme
    
    def to_dict(self) -> Dict:
        return asdict(self)


# =========================================================
# 기본 지표 계산 함수 (ta 라이브러리 미사용)
# =========================================================

def ema(series: pd.Series, period: int) -> pd.Series:
    """지수이동평균 (EMA)"""
    return series.ewm(span=period, adjust=False).mean()


def sma(series: pd.Series, period: int) -> pd.Series:
    """단순이동평균 (SMA)"""
    return series.rolling(window=period).mean()


def rsi_manual(series: pd.Series, period: int = 14) -> pd.Series:
    """RSI 수동 계산"""
    delta = series.diff()
    gain = delta.where(delta > 0, 0).rolling(period).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(period).mean()
    rs = gain / loss.replace(0, np.nan)
    return 100 - (100 / (1 + rs))


def macd_manual(series: pd.Series) -> Tuple[pd.Series, pd.Series, pd.Series]:
    """MACD 수동 계산"""
    ema12 = ema(series, 12)
    ema26 = ema(series, 26)
    macd_line = ema12 - ema26
    signal = ema(macd_line, 9)
    hist = macd_line - signal
    return macd_line, signal, hist


def bollinger_manual(
    series: pd.Series, 
    window: int = 20, 
    num_std: float = 2
) -> Tuple[pd.Series, pd.Series, pd.Series]:
    """볼린저 밴드 수동 계산"""
    mid = series.rolling(window).mean()
    std = series.rolling(window).std()
    upper = mid + std * num_std
    lower = mid - std * num_std
    return upper, mid, lower


def stoch_rsi_manual(series: pd.Series, period: int = 14) -> pd.Series:
    """Stochastic RSI 수동 계산"""
    r = rsi_manual(series, period)
    lowest = r.rolling(period).min()
    highest = r.rolling(period).max()
    return (r - lowest) / (highest - lowest + 1e-9)


def atr_manual(df: pd.DataFrame, period: int = 14) -> pd.Series:
    """ATR 수동 계산"""
    high = df["high"]
    low = df["low"]
    close = df["close"]
    
    tr1 = high - low
    tr2 = abs(high - close.shift(1))
    tr3 = abs(low - close.shift(1))
    
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    return tr.rolling(period).mean()


# =========================================================
# TechnicalIndicators 클래스
# =========================================================

class TechnicalIndicators:
    """
    통합 기술적 지표 계산기
    
    Usage:
        indicators = TechnicalIndicators()
        result = indicators.calculate(df, symbol="SOL/KRW")
        
        # 캐싱 사용
        result = indicators.calculate_cached(df, symbol="SOL/KRW")
    """
    
    # 싱글톤 인스턴스
    _instance = None
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance
    
    @staticmethod
    def _determine_ema_status(
        ema20_current: float,
        ema50_current: float,
        ema20_prev: float,
        ema50_prev: float,
    ) -> str:
        """EMA 상태 판단"""
        if ema20_current > ema50_current:
            if ema20_prev <= ema50_prev:
                return "golden_cross_recent"
            return "uptrend"
        else:
            if ema20_prev >= ema50_prev:
                return "dead_cross_recent"
            return "downtrend"
    
    @staticmethod
    def _determine_bb_position(price: float, bb_upper: float, bb_lower: float) -> str:
        """볼린저 밴드 내 위치 판단"""
        bb_range = bb_upper - bb_lower
        if bb_range <= 0:
            return "middle"
        
        position = (price - bb_lower) / bb_range
        
        if position >= 0.8:
            return "upper"
        elif position <= 0.2:
            return "lower"
        return "middle"
    
    @staticmethod
    def _determine_macd_cross(
        macd_hist_current: float,
        macd_hist_prev: float,
    ) -> str:
        """MACD 크로스 판단"""
        if macd_hist_prev <= 0 and macd_hist_current > 0:
            return "bullish"
        elif macd_hist_prev >= 0 and macd_hist_current < 0:
            return "bearish"
        return "none"
    
    def calculate(
        self, 
        df: pd.DataFrame, 
        symbol: str = "",
        use_ta_lib: bool = True,
    ) -> IndicatorResult:
        """
        모든 기술적 지표 계산
        
        Args:
            df: OHLCV DataFrame (최소 50행)
            symbol: 심볼 (로깅용)
            use_ta_lib: ta 라이브러리 사용 여부
            
        Returns:
            IndicatorResult
        """
        result = IndicatorResult(is_valid=False)
        
        if df is None or len(df) < 50:
            logger.warning(
                f"[{symbol}] 지표 계산 불가: 데이터 부족 "
                f"({len(df) if df is not None else 0}행)"
            )
            return result
        
        try:
            df = df.copy()
            close = df["close"]
            high = df["high"]
            low = df["low"]
            volume = df["volume"]
            
            # ===== RSI =====
            if use_ta_lib:
                df["rsi"] = ta.momentum.rsi(close, window=14)
            else:
                df["rsi"] = rsi_manual(close, 14)
            
            result.rsi = safe_float(df["rsi"].iloc[-1], 50)
            result.rsi_prev = safe_float(df["rsi"].iloc[-2], 50) if len(df) > 1 else result.rsi
            
            # ===== EMA =====
            if use_ta_lib:
                df["ema20"] = ta.trend.ema_indicator(close, window=20)
                df["ema50"] = ta.trend.ema_indicator(close, window=50)
            else:
                df["ema20"] = ema(close, 20)
                df["ema50"] = ema(close, 50)
            
            result.ema20 = safe_float(df["ema20"].iloc[-1], 0)
            result.ema50 = safe_float(df["ema50"].iloc[-1], 0)
            
            ema20_prev = safe_float(df["ema20"].iloc[-2], result.ema20) if len(df) > 1 else result.ema20
            ema50_prev = safe_float(df["ema50"].iloc[-2], result.ema50) if len(df) > 1 else result.ema50
            
            result.ema_status = self._determine_ema_status(
                result.ema20, result.ema50, ema20_prev, ema50_prev
            )
            
            # ===== 현재가 =====
            result.current_price = safe_float(close.iloc[-1], 0)
            
            # EMA20 대비 %
            if result.ema20 > 0:
                result.price_vs_ema20_pct = (
                    (result.current_price - result.ema20) / result.ema20 * 100
                )
            
            # ===== MACD =====
            if use_ta_lib:
                macd_obj = ta.trend.MACD(close)
                df["macd_line"] = macd_obj.macd()
                df["macd_signal"] = macd_obj.macd_signal()
                df["macd_hist"] = macd_obj.macd_diff()
            else:
                df["macd_line"], df["macd_signal"], df["macd_hist"] = macd_manual(close)
            
            result.macd_line = safe_float(df["macd_line"].iloc[-1], 0)
            result.macd_signal = safe_float(df["macd_signal"].iloc[-1], 0)
            result.macd_hist = safe_float(df["macd_hist"].iloc[-1], 0)
            
            macd_hist_prev = safe_float(df["macd_hist"].iloc[-2], 0) if len(df) > 1 else 0
            result.macd_cross = self._determine_macd_cross(result.macd_hist, macd_hist_prev)
            
            # ===== Bollinger Bands =====
            if use_ta_lib:
                bb = ta.volatility.BollingerBands(close, window=20, window_dev=2)
                df["bb_upper"] = bb.bollinger_hband()
                df["bb_middle"] = bb.bollinger_mavg()
                df["bb_lower"] = bb.bollinger_lband()
            else:
                df["bb_upper"], df["bb_middle"], df["bb_lower"] = bollinger_manual(close)
            
            result.bb_upper = safe_float(df["bb_upper"].iloc[-1], 0)
            result.bb_middle = safe_float(df["bb_middle"].iloc[-1], 0)
            result.bb_lower = safe_float(df["bb_lower"].iloc[-1], 0)
            result.bb_position = self._determine_bb_position(
                result.current_price, result.bb_upper, result.bb_lower
            )
            
            if result.bb_middle > 0:
                result.bb_width = (result.bb_upper - result.bb_lower) / result.bb_middle
            
            # ===== ATR =====
            if use_ta_lib:
                df["atr"] = ta.volatility.average_true_range(high, low, close, window=14)
            else:
                df["atr"] = atr_manual(df, 14)
            
            result.atr = safe_float(df["atr"].iloc[-1], 0)
            if result.current_price > 0:
                result.atr_pct = result.atr / result.current_price * 100
            
            # ===== ADX =====
            if use_ta_lib:
                df["adx"] = ta.trend.adx(high, low, close, window=14)
            else:
                # ADX는 복잡하므로 ta 라이브러리 사용 권장
                df["adx"] = ta.trend.adx(high, low, close, window=14)
            
            result.adx = safe_float(df["adx"].iloc[-1], 20)
            
            # ===== Stochastic RSI =====
            if use_ta_lib:
                stoch = ta.momentum.StochRSIIndicator(close, window=14, smooth1=3, smooth2=3)
                df["stoch_rsi"] = stoch.stochrsi()
                df["stoch_rsi_k"] = stoch.stochrsi_k()
                df["stoch_rsi_d"] = stoch.stochrsi_d()
            else:
                df["stoch_rsi"] = stoch_rsi_manual(close, 14)
                df["stoch_rsi_k"] = df["stoch_rsi"]
                df["stoch_rsi_d"] = df["stoch_rsi"].rolling(3).mean()
            
            result.stoch_rsi = safe_float(df["stoch_rsi"].iloc[-1], 0.5)
            result.stoch_rsi_k = safe_float(df["stoch_rsi_k"].iloc[-1], 0.5)
            result.stoch_rsi_d = safe_float(df["stoch_rsi_d"].iloc[-1], 0.5)
            
            # ===== Volume =====
            df["volume_sma20"] = volume.rolling(20).mean()
            result.volume_sma20 = safe_float(df["volume_sma20"].iloc[-1], 0)
            
            if result.volume_sma20 > 0:
                result.volume_ratio = safe_float(volume.iloc[-1], 0) / result.volume_sma20
            
            # VWAP
            df["vwap"] = (volume * (high + low + close) / 3).cumsum() / volume.cumsum()
            result.vwap = safe_float(df["vwap"].iloc[-1], 0)
            
            # ===== 변화율 =====
            # 24시간 (48 * 30분봉)
            if len(df) >= 48:
                price_24h_ago = safe_float(close.iloc[-48], 0)
                if price_24h_ago > 0:
                    result.change_24h = (
                        (result.current_price - price_24h_ago) / price_24h_ago * 100
                    )
            
            # 1시간 (2 * 30분봉)
            if len(df) >= 2:
                price_1h_ago = safe_float(close.iloc[-2], 0)
                if price_1h_ago > 0:
                    result.change_1h = (
                        (result.current_price - price_1h_ago) / price_1h_ago * 100
                    )
            
            result.is_valid = True
            return result
            
        except Exception as e:
            logger.error(f"[{symbol}] 지표 계산 오류: {e}")
            return result
    
    def calculate_cached(
        self, 
        df: pd.DataFrame, 
        symbol: str,
        ttl: int = 60,
    ) -> IndicatorResult:
        """
        캐싱된 지표 계산
        
        Args:
            df: OHLCV DataFrame
            symbol: 심볼 (캐시 키)
            ttl: 캐시 TTL (초)
            
        Returns:
            IndicatorResult
        """
        cache_key = f"indicators:{symbol}"
        
        cached_result = indicator_cache.get(cache_key)
        if cached_result is not None:
            return cached_result
        
        result = self.calculate(df, symbol)
        
        if result.is_valid:
            indicator_cache.set(cache_key, result, ttl)
        
        return result
    
    def calculate_atr_info(
        self, 
        df: pd.DataFrame,
        current_price: float = None,
    ) -> ATRInfo:
        """
        ATR 상세 정보 계산
        
        Args:
            df: OHLCV DataFrame
            current_price: 현재가 (없으면 df에서 추출)
            
        Returns:
            ATRInfo
        """
        info = ATRInfo()
        
        if df is None or len(df) < 15:
            return info
        
        try:
            df = df.copy()
            df["atr"] = atr_manual(df, 14)
            
            info.value = safe_float(df["atr"].iloc[-1], 0)
            
            if current_price is None:
                current_price = safe_float(df["close"].iloc[-1], 0)
            
            if current_price > 0:
                info.pct = info.value / current_price * 100
            
            # 등급 판단
            if info.pct < 2:
                info.grade = "low"
            elif info.pct < 4:
                info.grade = "mid"
            elif info.pct < 7:
                info.grade = "high"
            else:
                info.grade = "extreme"
            
            return info
            
        except Exception as e:
            logger.error(f"ATR 계산 오류: {e}")
            return info


# =========================================================
# 싱글톤 인스턴스 및 편의 함수
# =========================================================

# 글로벌 인스턴스
_indicators = TechnicalIndicators()


def calculate_indicators(df: pd.DataFrame, symbol: str = "") -> Dict:
    """
    지표 계산 (ai_decision 호환 형식)
    
    기존 ai_decision.calculate_indicators() 대체
    """
    result = _indicators.calculate(df, symbol)
    return result.to_ai_summary() if result.is_valid else {}


def calculate_indicators_full(df: pd.DataFrame, symbol: str = "") -> IndicatorResult:
    """전체 지표 계산"""
    return _indicators.calculate(df, symbol)


def calculate_indicators_cached(df: pd.DataFrame, symbol: str) -> IndicatorResult:
    """캐싱된 전체 지표 계산"""
    return _indicators.calculate_cached(df, symbol)


def calculate_atr(df: pd.DataFrame, period: int = 14) -> float:
    """
    ATR 계산 (strategy_engine 호환)
    
    기존 strategy_engine.calculate_atr() 대체
    """
    if df is None or len(df) < period + 1:
        return 0.0
    
    try:
        atr_series = atr_manual(df, period)
        return safe_float(atr_series.iloc[-1], 0.0)
    except:
        return 0.0


def get_atr_info(df: pd.DataFrame, current_price: float = None) -> ATRInfo:
    """ATR 상세 정보"""
    return _indicators.calculate_atr_info(df, current_price)


def invalidate_indicator_cache(symbol: str = None):
    """지표 캐시 무효화"""
    if symbol:
        indicator_cache.delete(f"indicators:{symbol}")
    else:
        indicator_cache.clear()
