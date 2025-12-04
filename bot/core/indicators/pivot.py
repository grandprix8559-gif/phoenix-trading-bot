# -*- coding: utf-8 -*-
"""
Phoenix v5.3.0 — 피봇 포인트 모듈

피봇 포인트 계산 및 신호 생성
- Standard / Fibonacci / Camarilla Pivot
- 지지/저항 레벨
- 진입 신호

기존 pivot_calculator.py를 래핑하여 통합 인터페이스 제공
"""

import pandas as pd
from typing import Dict, Optional, List
from dataclasses import dataclass, asdict, field
from datetime import datetime

from bot.utils.logger import get_logger
from bot.utils.cache import indicator_cache
from bot.utils.validators import safe_float

logger = get_logger("PivotIndicator")


# =========================================================
# 데이터 클래스
# =========================================================

@dataclass
class PivotLevels:
    """피봇 레벨"""
    type: str = "standard"
    pp: float = 0.0
    r1: float = 0.0
    r2: float = 0.0
    r3: float = 0.0
    r4: float = 0.0  # Camarilla only
    s1: float = 0.0
    s2: float = 0.0
    s3: float = 0.0
    s4: float = 0.0  # Camarilla only
    
    def to_dict(self) -> Dict:
        result = {
            "type": self.type,
            "pp": round(self.pp, 2),
            "r1": round(self.r1, 2),
            "r2": round(self.r2, 2),
            "r3": round(self.r3, 2),
            "s1": round(self.s1, 2),
            "s2": round(self.s2, 2),
            "s3": round(self.s3, 2),
        }
        if self.type == "camarilla":
            result["r4"] = round(self.r4, 2)
            result["s4"] = round(self.s4, 2)
        return result
    
    def get_resistance_levels(self) -> List[float]:
        """저항 레벨 목록"""
        levels = [self.r1, self.r2, self.r3]
        if self.r4 > 0:
            levels.append(self.r4)
        return sorted([l for l in levels if l > 0])
    
    def get_support_levels(self) -> List[float]:
        """지지 레벨 목록"""
        levels = [self.s1, self.s2, self.s3]
        if self.s4 > 0:
            levels.append(self.s4)
        return sorted([l for l in levels if l > 0], reverse=True)


@dataclass
class PivotSignal:
    """피봇 기반 신호"""
    signal: str = "hold"  # buy, sell, hold
    strength: int = 0  # -3 ~ +3
    nearest_support: float = 0.0
    nearest_resistance: float = 0.0
    distance_to_support_pct: float = 0.0
    distance_to_resistance_pct: float = 0.0
    position: str = "middle"  # above_r1, above_pp, below_pp, below_s1, etc.
    reason: str = ""
    
    def to_dict(self) -> Dict:
        return {
            "signal": self.signal,
            "strength": self.strength,
            "nearest_support": round(self.nearest_support, 2),
            "nearest_resistance": round(self.nearest_resistance, 2),
            "distance_to_support_pct": round(self.distance_to_support_pct, 2),
            "distance_to_resistance_pct": round(self.distance_to_resistance_pct, 2),
            "position": self.position,
            "reason": self.reason,
        }


# =========================================================
# PivotCalculator 클래스
# =========================================================

class PivotCalculator:
    """
    피봇 포인트 계산기
    
    Usage:
        calc = PivotCalculator()
        levels = calc.calculate(high=100, low=90, close=95)
        signal = calc.get_signal(current_price=97, levels=levels)
    """
    
    @staticmethod
    def calculate_standard(high: float, low: float, close: float) -> PivotLevels:
        """
        Standard Pivot Points (표준 피봇)
        
        PP = (H + L + C) / 3
        R1 = (2 × PP) - L
        R2 = PP + (H - L)
        R3 = H + 2 × (PP - L)
        S1 = (2 × PP) - H
        S2 = PP - (H - L)
        S3 = L - 2 × (H - PP)
        """
        pp = (high + low + close) / 3
        
        return PivotLevels(
            type="standard",
            pp=pp,
            r1=(2 * pp) - low,
            r2=pp + (high - low),
            r3=high + 2 * (pp - low),
            s1=(2 * pp) - high,
            s2=pp - (high - low),
            s3=low - 2 * (high - pp),
        )
    
    @staticmethod
    def calculate_fibonacci(high: float, low: float, close: float) -> PivotLevels:
        """
        Fibonacci Pivot Points
        
        PP = (H + L + C) / 3
        R1 = PP + 0.382 × (H - L)
        R2 = PP + 0.618 × (H - L)
        R3 = PP + 1.0 × (H - L)
        S1 = PP - 0.382 × (H - L)
        S2 = PP - 0.618 × (H - L)
        S3 = PP - 1.0 × (H - L)
        """
        pp = (high + low + close) / 3
        range_hl = high - low
        
        return PivotLevels(
            type="fibonacci",
            pp=pp,
            r1=pp + 0.382 * range_hl,
            r2=pp + 0.618 * range_hl,
            r3=pp + 1.0 * range_hl,
            s1=pp - 0.382 * range_hl,
            s2=pp - 0.618 * range_hl,
            s3=pp - 1.0 * range_hl,
        )
    
    @staticmethod
    def calculate_camarilla(high: float, low: float, close: float) -> PivotLevels:
        """
        Camarilla Pivot Points (스캘핑용)
        
        더 촘촘한 레벨 제공
        """
        range_hl = high - low
        pp = (high + low + close) / 3
        
        return PivotLevels(
            type="camarilla",
            pp=pp,
            r1=close + range_hl * 1.1 / 12,
            r2=close + range_hl * 1.1 / 6,
            r3=close + range_hl * 1.1 / 4,
            r4=close + range_hl * 1.1 / 2,
            s1=close - range_hl * 1.1 / 12,
            s2=close - range_hl * 1.1 / 6,
            s3=close - range_hl * 1.1 / 4,
            s4=close - range_hl * 1.1 / 2,
        )
    
    @classmethod
    def calculate(
        cls,
        high: float,
        low: float,
        close: float,
        pivot_type: str = "standard",
    ) -> PivotLevels:
        """
        피봇 포인트 계산 (타입별)
        
        Args:
            high: 전일 고가
            low: 전일 저가
            close: 전일 종가
            pivot_type: "standard", "fibonacci", "camarilla"
            
        Returns:
            PivotLevels
        """
        if pivot_type == "fibonacci":
            return cls.calculate_fibonacci(high, low, close)
        elif pivot_type == "camarilla":
            return cls.calculate_camarilla(high, low, close)
        else:
            return cls.calculate_standard(high, low, close)
    
    @classmethod
    def calculate_from_df(
        cls,
        df: pd.DataFrame,
        pivot_type: str = "standard",
    ) -> Optional[PivotLevels]:
        """
        DataFrame에서 피봇 계산 (전일 데이터 사용)
        
        Args:
            df: OHLCV DataFrame
            pivot_type: 피봇 타입
            
        Returns:
            PivotLevels 또는 None
        """
        if df is None or len(df) < 2:
            return None
        
        try:
            # 전일 데이터 (마지막에서 두번째 행)
            prev = df.iloc[-2]
            
            high = safe_float(prev["high"], 0)
            low = safe_float(prev["low"], 0)
            close = safe_float(prev["close"], 0)
            
            if high <= 0 or low <= 0 or close <= 0:
                return None
            
            return cls.calculate(high, low, close, pivot_type)
            
        except Exception as e:
            logger.error(f"피봇 계산 오류: {e}")
            return None
    
    @staticmethod
    def get_signal(
        current_price: float,
        levels: PivotLevels,
        tolerance_pct: float = 0.5,
    ) -> PivotSignal:
        """
        피봇 기반 신호 생성
        
        Args:
            current_price: 현재가
            levels: 피봇 레벨
            tolerance_pct: 레벨 근접 판단 허용치 (%)
            
        Returns:
            PivotSignal
        """
        signal = PivotSignal()
        
        if current_price <= 0 or levels.pp <= 0:
            return signal
        
        # 지지/저항 레벨
        supports = levels.get_support_levels()
        resistances = levels.get_resistance_levels()
        
        # 가장 가까운 지지/저항 찾기
        nearest_support = 0.0
        nearest_resistance = 0.0
        
        for s in supports:
            if s < current_price:
                nearest_support = s
                break
        
        for r in resistances:
            if r > current_price:
                nearest_resistance = r
                break
        
        signal.nearest_support = nearest_support
        signal.nearest_resistance = nearest_resistance
        
        # 거리 계산
        if nearest_support > 0:
            signal.distance_to_support_pct = (
                (current_price - nearest_support) / nearest_support * 100
            )
        
        if nearest_resistance > 0:
            signal.distance_to_resistance_pct = (
                (nearest_resistance - current_price) / current_price * 100
            )
        
        # 위치 판단
        if current_price > levels.r2:
            signal.position = "above_r2"
        elif current_price > levels.r1:
            signal.position = "above_r1"
        elif current_price > levels.pp:
            signal.position = "above_pp"
        elif current_price > levels.s1:
            signal.position = "below_pp"
        elif current_price > levels.s2:
            signal.position = "below_s1"
        else:
            signal.position = "below_s2"
        
        # 신호 생성
        tolerance = current_price * tolerance_pct / 100
        
        # 지지선 근접 → 매수 신호
        if nearest_support > 0 and abs(current_price - nearest_support) < tolerance:
            signal.signal = "buy"
            signal.strength = 2
            signal.reason = f"지지선 S{supports.index(nearest_support)+1} 근접"
        
        # S2 이하 → 강한 매수
        elif current_price < levels.s2:
            signal.signal = "buy"
            signal.strength = 3
            signal.reason = "S2 하회 (과매도)"
        
        # 저항선 근접 → 매도 신호
        elif nearest_resistance > 0 and abs(current_price - nearest_resistance) < tolerance:
            signal.signal = "sell"
            signal.strength = -2
            signal.reason = f"저항선 R{resistances.index(nearest_resistance)+1} 근접"
        
        # R2 이상 → 강한 매도
        elif current_price > levels.r2:
            signal.signal = "sell"
            signal.strength = -3
            signal.reason = "R2 상회 (과매수)"
        
        # PP 위 → 약한 매수 유지
        elif current_price > levels.pp:
            signal.signal = "hold"
            signal.strength = 1
            signal.reason = "PP 상단 유지"
        
        # PP 아래 → 약한 매도 고려
        else:
            signal.signal = "hold"
            signal.strength = -1
            signal.reason = "PP 하단"
        
        return signal


# =========================================================
# 편의 함수 (기존 호환)
# =========================================================

def get_pivot_levels(
    df: pd.DataFrame,
    pivot_type: str = "standard",
    symbol: str = "",
) -> Optional[Dict]:
    """
    피봇 레벨 조회 (기존 pivot_calculator 호환)
    
    Args:
        df: OHLCV DataFrame
        pivot_type: 피봇 타입
        symbol: 심볼 (캐싱용)
        
    Returns:
        피봇 레벨 딕셔너리
    """
    # 캐시 확인
    cache_key = f"pivot:{symbol}:{pivot_type}" if symbol else None
    
    if cache_key:
        cached = indicator_cache.get(cache_key)
        if cached is not None:
            return cached
    
    # 계산
    levels = PivotCalculator.calculate_from_df(df, pivot_type)
    
    if levels is None:
        return None
    
    result = levels.to_dict()
    
    # 캐싱
    if cache_key:
        indicator_cache.set(cache_key, result, ttl=300)  # 5분 캐시
    
    return result


def get_pivot_signal(
    current_price: float,
    pivot_levels: Dict,
    tolerance_pct: float = 0.5,
) -> Dict:
    """
    피봇 신호 조회 (기존 pivot_calculator 호환)
    
    Args:
        current_price: 현재가
        pivot_levels: 피봇 레벨 딕셔너리
        tolerance_pct: 허용치 (%)
        
    Returns:
        신호 딕셔너리
    """
    if not pivot_levels:
        return {"signal": "hold", "strength": 0, "reason": "피봇 데이터 없음"}
    
    # Dict를 PivotLevels로 변환
    levels = PivotLevels(
        type=pivot_levels.get("type", "standard"),
        pp=safe_float(pivot_levels.get("pp"), 0),
        r1=safe_float(pivot_levels.get("r1"), 0),
        r2=safe_float(pivot_levels.get("r2"), 0),
        r3=safe_float(pivot_levels.get("r3"), 0),
        r4=safe_float(pivot_levels.get("r4"), 0),
        s1=safe_float(pivot_levels.get("s1"), 0),
        s2=safe_float(pivot_levels.get("s2"), 0),
        s3=safe_float(pivot_levels.get("s3"), 0),
        s4=safe_float(pivot_levels.get("s4"), 0),
    )
    
    signal = PivotCalculator.get_signal(current_price, levels, tolerance_pct)
    return signal.to_dict()


def calculate_pivot_all_types(
    df: pd.DataFrame,
) -> Dict[str, Dict]:
    """모든 타입 피봇 계산"""
    result = {}
    
    for pivot_type in ["standard", "fibonacci", "camarilla"]:
        levels = PivotCalculator.calculate_from_df(df, pivot_type)
        if levels:
            result[pivot_type] = levels.to_dict()
    
    return result


def invalidate_pivot_cache(symbol: str = None):
    """피봇 캐시 무효화"""
    if symbol:
        for pivot_type in ["standard", "fibonacci", "camarilla"]:
            indicator_cache.delete(f"pivot:{symbol}:{pivot_type}")
    else:
        # 전체 무효화는 indicator_cache.clear()로
        pass
