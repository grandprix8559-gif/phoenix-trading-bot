# -*- coding: utf-8 -*-
"""
Phoenix v5.0 — Pivot Point Calculator

피봇 포인트 계산:
- Standard Pivot
- Fibonacci Pivot
- Camarilla Pivot

활용:
- 지지선/저항선 기반 진입
- TP/SL 레벨 설정
- 추세 판단 보조
"""

import pandas as pd
from typing import Dict, Optional
from datetime import datetime, timedelta

from bot.utils.logger import get_logger

logger = get_logger("PivotCalc")


class PivotCalculator:
    """피봇 포인트 계산기"""
    
    @staticmethod
    def calculate_standard(high: float, low: float, close: float) -> Dict:
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
        
        r1 = (2 * pp) - low
        r2 = pp + (high - low)
        r3 = high + 2 * (pp - low)
        
        s1 = (2 * pp) - high
        s2 = pp - (high - low)
        s3 = low - 2 * (high - pp)
        
        return {
            "type": "standard",
            "pp": round(pp, 2),
            "r1": round(r1, 2),
            "r2": round(r2, 2),
            "r3": round(r3, 2),
            "s1": round(s1, 2),
            "s2": round(s2, 2),
            "s3": round(s3, 2),
        }
    
    @staticmethod
    def calculate_fibonacci(high: float, low: float, close: float) -> Dict:
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
        
        r1 = pp + 0.382 * range_hl
        r2 = pp + 0.618 * range_hl
        r3 = pp + 1.0 * range_hl
        
        s1 = pp - 0.382 * range_hl
        s2 = pp - 0.618 * range_hl
        s3 = pp - 1.0 * range_hl
        
        return {
            "type": "fibonacci",
            "pp": round(pp, 2),
            "r1": round(r1, 2),
            "r2": round(r2, 2),
            "r3": round(r3, 2),
            "s1": round(s1, 2),
            "s2": round(s2, 2),
            "s3": round(s3, 2),
        }
    
    @staticmethod
    def calculate_camarilla(high: float, low: float, close: float) -> Dict:
        """
        Camarilla Pivot Points (스캘핑용)
        
        더 촘촘한 레벨 제공
        """
        range_hl = high - low
        
        r4 = close + range_hl * 1.1 / 2
        r3 = close + range_hl * 1.1 / 4
        r2 = close + range_hl * 1.1 / 6
        r1 = close + range_hl * 1.1 / 12
        
        s1 = close - range_hl * 1.1 / 12
        s2 = close - range_hl * 1.1 / 6
        s3 = close - range_hl * 1.1 / 4
        s4 = close - range_hl * 1.1 / 2
        
        pp = (high + low + close) / 3
        
        return {
            "type": "camarilla",
            "pp": round(pp, 2),
            "r1": round(r1, 2),
            "r2": round(r2, 2),
            "r3": round(r3, 2),
            "r4": round(r4, 2),
            "s1": round(s1, 2),
            "s2": round(s2, 2),
            "s3": round(s3, 2),
            "s4": round(s4, 2),
        }
    
    @classmethod
    def calculate(cls, high: float, low: float, close: float, 
                  pivot_type: str = "standard") -> Dict:
        """
        피봇 포인트 계산 (타입별)
        
        Args:
            high: 전일 고가
            low: 전일 저가
            close: 전일 종가
            pivot_type: "standard", "fibonacci", "camarilla"
        """
        if pivot_type == "fibonacci":
            return cls.calculate_fibonacci(high, low, close)
        elif pivot_type == "camarilla":
            return cls.calculate_camarilla(high, low, close)
        else:
            return cls.calculate_standard(high, low, close)
    
    @classmethod
    def calculate_from_df(cls, df: pd.DataFrame, pivot_type: str = "standard") -> Dict:
        """
        DataFrame에서 전일 데이터로 피봇 계산
        
        Args:
            df: OHLCV DataFrame (최소 2일치)
            pivot_type: 피봇 타입
        """
        try:
            if df is None or len(df) < 48:  # 30분봉 기준 최소 1일
                return {}
            
            # 전일 데이터 추출 (어제 00:00 ~ 23:59)
            # 간단히 마지막 48개 봉의 이전 48개 봉 사용
            if len(df) >= 96:
                prev_day = df.iloc[-96:-48]
            else:
                prev_day = df.iloc[:-48]
            
            if len(prev_day) == 0:
                return {}
            
            high = prev_day["high"].max()
            low = prev_day["low"].min()
            close = prev_day["close"].iloc[-1]
            
            pivot = cls.calculate(high, low, close, pivot_type)
            
            # 현재가 대비 위치 분석 추가
            current_price = df["close"].iloc[-1]
            pivot["current_price"] = current_price
            pivot["price_position"] = cls.analyze_price_position(current_price, pivot)
            
            return pivot
            
        except Exception as e:
            logger.error(f"[Pivot Calc Error] {e}")
            return {}
    
    @staticmethod
    def analyze_price_position(price: float, pivot: Dict) -> Dict:
        """
        현재가의 피봇 대비 위치 분석
        
        Returns:
            {
                "zone": "above_r2" | "r1_r2" | "pp_r1" | "s1_pp" | "s1_s2" | "below_s2",
                "nearest_support": float,
                "nearest_resistance": float,
                "trend_bias": "bullish" | "bearish" | "neutral",
                "distance_to_pp_pct": float
            }
        """
        pp = pivot.get("pp", price)
        r1 = pivot.get("r1", price * 1.01)
        r2 = pivot.get("r2", price * 1.02)
        s1 = pivot.get("s1", price * 0.99)
        s2 = pivot.get("s2", price * 0.98)
        
        # 가격 위치 판단
        if price >= r2:
            zone = "above_r2"
            nearest_support = r2
            nearest_resistance = pivot.get("r3", r2 * 1.01)
            trend_bias = "bullish"
        elif price >= r1:
            zone = "r1_r2"
            nearest_support = r1
            nearest_resistance = r2
            trend_bias = "bullish"
        elif price >= pp:
            zone = "pp_r1"
            nearest_support = pp
            nearest_resistance = r1
            trend_bias = "bullish"
        elif price >= s1:
            zone = "s1_pp"
            nearest_support = s1
            nearest_resistance = pp
            trend_bias = "neutral"
        elif price >= s2:
            zone = "s1_s2"
            nearest_support = s2
            nearest_resistance = s1
            trend_bias = "bearish"
        else:
            zone = "below_s2"
            nearest_support = pivot.get("s3", s2 * 0.99)
            nearest_resistance = s2
            trend_bias = "bearish"
        
        # PP 대비 거리
        distance_to_pp_pct = (price - pp) / pp * 100
        
        return {
            "zone": zone,
            "nearest_support": round(nearest_support, 2),
            "nearest_resistance": round(nearest_resistance, 2),
            "trend_bias": trend_bias,
            "distance_to_pp_pct": round(distance_to_pp_pct, 2),
        }
    
    @staticmethod
    def get_entry_signal(price: float, pivot: Dict, tolerance: float = 0.005) -> Dict:
        """
        피봇 기반 진입 신호
        
        Args:
            price: 현재가
            pivot: 피봇 데이터
            tolerance: 허용 오차 (0.5%)
        
        Returns:
            {
                "signal": "buy" | "sell" | "hold",
                "reason": str,
                "confidence": float,
                "target_tp": float,
                "target_sl": float
            }
        """
        if not pivot:
            return {"signal": "hold", "reason": "피봇 데이터 없음", "confidence": 0}
        
        pp = pivot.get("pp", price)
        r1 = pivot.get("r1", price * 1.01)
        r2 = pivot.get("r2", price * 1.02)
        s1 = pivot.get("s1", price * 0.99)
        s2 = pivot.get("s2", price * 0.98)
        
        position = pivot.get("price_position", {})
        zone = position.get("zone", "unknown")
        
        # S1 근처 + 반등 조짐 → 매수
        s1_distance = abs(price - s1) / s1
        if s1_distance <= tolerance and zone in ["s1_pp", "s1_s2"]:
            return {
                "signal": "buy",
                "reason": f"S1 지지선({s1:,.0f}) 근처 반등",
                "confidence": 0.7,
                "target_tp": pp,  # PP를 1차 목표
                "target_sl": s2,  # S2를 손절
                "pivot_level": "S1",
            }
        
        # S2 근처 + 강한 지지 → 강한 매수
        s2_distance = abs(price - s2) / s2
        if s2_distance <= tolerance and zone == "s1_s2":
            return {
                "signal": "buy",
                "reason": f"S2 강한 지지선({s2:,.0f}) 근처",
                "confidence": 0.8,
                "target_tp": s1,
                "target_sl": s2 * 0.99,  # S2 아래
                "pivot_level": "S2",
            }
        
        # R1 근처 → 매도 고려
        r1_distance = abs(price - r1) / r1
        if r1_distance <= tolerance and zone in ["pp_r1", "r1_r2"]:
            return {
                "signal": "sell",
                "reason": f"R1 저항선({r1:,.0f}) 근처",
                "confidence": 0.6,
                "target_tp": pp,
                "target_sl": r2,
                "pivot_level": "R1",
            }
        
        # R2 돌파 → 추세 추종 매수
        if zone == "above_r2":
            return {
                "signal": "buy",
                "reason": f"R2({r2:,.0f}) 돌파 추세 추종",
                "confidence": 0.65,
                "target_tp": pivot.get("r3", r2 * 1.01),
                "target_sl": r1,
                "pivot_level": "R2_breakout",
            }
        
        # PP 위에서 상승 추세
        if zone == "pp_r1" and position.get("trend_bias") == "bullish":
            return {
                "signal": "hold",
                "reason": f"PP({pp:,.0f}) 위, 상승 추세 유지",
                "confidence": 0.5,
                "target_tp": r1,
                "target_sl": pp,
                "pivot_level": "above_PP",
            }
        
        # 기본: 관망
        return {
            "signal": "hold",
            "reason": f"명확한 피봇 신호 없음 (zone: {zone})",
            "confidence": 0.3,
            "target_tp": None,
            "target_sl": None,
            "pivot_level": None,
        }
    
    @staticmethod
    def get_pivot_based_tp_sl(entry_price: float, pivot: Dict, 
                               direction: str = "long") -> Dict:
        """
        피봇 기반 TP/SL 계산
        
        Args:
            entry_price: 진입가
            pivot: 피봇 데이터
            direction: "long" or "short"
        
        Returns:
            {
                "tp1": float,
                "tp2": float,
                "tp3": float,
                "sl": float,
                "tp1_pct": float,
                ...
            }
        """
        if not pivot:
            # 기본값 반환
            if direction == "long":
                return {
                    "tp1": entry_price * 1.015,
                    "tp2": entry_price * 1.03,
                    "tp3": entry_price * 1.05,
                    "sl": entry_price * 0.985,
                }
            else:
                return {
                    "tp1": entry_price * 0.985,
                    "tp2": entry_price * 0.97,
                    "tp3": entry_price * 0.95,
                    "sl": entry_price * 1.015,
                }
        
        pp = pivot.get("pp", entry_price)
        r1 = pivot.get("r1", entry_price * 1.01)
        r2 = pivot.get("r2", entry_price * 1.02)
        r3 = pivot.get("r3", entry_price * 1.03)
        s1 = pivot.get("s1", entry_price * 0.99)
        s2 = pivot.get("s2", entry_price * 0.98)
        s3 = pivot.get("s3", entry_price * 0.97)
        
        if direction == "long":
            # 매수 포지션: 저항선을 TP, 지지선을 SL
            result = {
                "tp1": r1 if r1 > entry_price else entry_price * 1.015,
                "tp2": r2 if r2 > entry_price else entry_price * 1.03,
                "tp3": r3 if r3 > entry_price else entry_price * 1.05,
                "sl": s1 if s1 < entry_price else entry_price * 0.985,
            }
        else:
            # 매도 포지션: 지지선을 TP, 저항선을 SL
            result = {
                "tp1": s1 if s1 < entry_price else entry_price * 0.985,
                "tp2": s2 if s2 < entry_price else entry_price * 0.97,
                "tp3": s3 if s3 < entry_price else entry_price * 0.95,
                "sl": r1 if r1 > entry_price else entry_price * 1.015,
            }
        
        # 퍼센트 계산
        result["tp1_pct"] = (result["tp1"] - entry_price) / entry_price * 100
        result["tp2_pct"] = (result["tp2"] - entry_price) / entry_price * 100
        result["tp3_pct"] = (result["tp3"] - entry_price) / entry_price * 100
        result["sl_pct"] = (result["sl"] - entry_price) / entry_price * 100
        
        return result


# 편의 함수
def get_pivot_levels(df: pd.DataFrame, pivot_type: str = "standard") -> Dict:
    """DataFrame에서 피봇 레벨 계산"""
    return PivotCalculator.calculate_from_df(df, pivot_type)


def get_pivot_signal(price: float, pivot: Dict, tolerance: float = 0.005) -> Dict:
    """피봇 기반 진입 신호"""
    return PivotCalculator.get_entry_signal(price, pivot, tolerance)
