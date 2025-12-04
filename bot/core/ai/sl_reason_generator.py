# -*- coding: utf-8 -*-
"""
Phoenix v5.3.0 — SL 근거 생성기

손절 승인 요청 시 전략적 근거를 생성합니다.

🔥 v5.3.0:
- ai_decision.py에서 분리
- generate_sl_rationale() 메서드
- 피봇 포인트 지지선 분석
"""

import pandas as pd
from typing import Dict, Optional
from dataclasses import dataclass

from config import Config
from bot.utils.logger import get_logger

logger = get_logger("AI.SLReasonGenerator")


# =========================================================
# 데이터 클래스
# =========================================================

@dataclass
class SLRationale:
    """SL 근거 결과"""
    recommendation: str = "손절"  # 손절 / 홀드
    confidence: float = 0.5
    rationale: str = ""
    support_level: Optional[float] = None
    recovery_chance: float = 0.3
    risk_if_hold: str = ""
    rsi: float = 50
    ema_status: str = "unknown"
    pnl_pct: float = 0.0
    
    def to_dict(self) -> Dict:
        return {
            "recommendation": self.recommendation,
            "confidence": round(self.confidence, 2),
            "rationale": self.rationale,
            "support_level": self.support_level,
            "recovery_chance": round(self.recovery_chance, 2),
            "risk_if_hold": self.risk_if_hold,
            "rsi": self.rsi,
            "ema_status": self.ema_status,
            "pnl_pct": round(self.pnl_pct, 2),
        }


# =========================================================
# SL 근거 생성기
# =========================================================

class SLReasonGenerator:
    """
    SL 근거 생성기
    
    손절 승인 요청 시 기술적 분석 기반의 전략적 근거를 생성합니다.
    """
    
    @classmethod
    def _calculate_recovery_chance(
        cls,
        rsi: float,
        ema_status: str,
        near_support: bool,
        atr_pct: float,
    ) -> float:
        """
        회복 가능성 계산
        
        Args:
            rsi: RSI 값
            ema_status: EMA 상태
            near_support: 지지선 근접 여부
            atr_pct: ATR 퍼센트
            
        Returns:
            회복 가능성 (0.0 ~ 1.0)
        """
        chance = 0.3  # 기본값
        
        # RSI 과매도
        if rsi < 30:
            chance += 0.1
        
        # EMA 상승 추세
        if ema_status in ["uptrend", "golden_cross_recent"]:
            chance += 0.2
        
        # 지지선 근접
        if near_support:
            chance += 0.15
        
        # 고변동성은 부정적
        if atr_pct > 4:
            chance -= 0.1
        
        return min(0.8, max(0.1, chance))
    
    @classmethod
    def _check_support_level(
        cls,
        current_price: float,
        pivot_data: Optional[Dict],
    ) -> tuple:
        """
        지지선 확인
        
        Args:
            current_price: 현재 가격
            pivot_data: 피봇 포인트 데이터
            
        Returns:
            (지지선 가격, 지지선 근접 여부)
        """
        support_level = None
        near_support = False
        
        if not pivot_data:
            return (None, False)
        
        s1 = pivot_data.get("s1", pivot_data.get("S1", 0))
        s2 = pivot_data.get("s2", pivot_data.get("S2", 0))
        
        if s1 and current_price > s1 * 0.99:
            support_level = s1
            near_support = (current_price - s1) / s1 < 0.02 if s1 > 0 else False
        elif s2 and current_price > s2 * 0.99:
            support_level = s2
            near_support = (current_price - s2) / s2 < 0.02 if s2 > 0 else False
        
        return (support_level, near_support)
    
    @classmethod
    def _build_rationale_string(
        cls,
        pnl_pct: float,
        rsi: float,
        ema_status: str,
        near_support: bool,
        support_level: Optional[float],
    ) -> str:
        """
        근거 문자열 생성
        
        Args:
            pnl_pct: 손익 퍼센트
            rsi: RSI 값
            ema_status: EMA 상태
            near_support: 지지선 근접 여부
            support_level: 지지선 가격
            
        Returns:
            근거 문자열
        """
        parts = []
        
        if pnl_pct <= -3.0:
            parts.append(f"손실 {pnl_pct:.1f}% (임계치 초과)")
        else:
            parts.append(f"현재 손실 {pnl_pct:.1f}%")
        
        parts.append(f"RSI {rsi:.0f} (참고)")
        
        if near_support and support_level:
            parts.append(f"S1 지지선 근접 ({support_level:,.0f})")
        
        if ema_status == "downtrend":
            parts.append("EMA 하락 추세")
        elif ema_status == "uptrend":
            parts.append("EMA 상승 추세")
        
        return " | ".join(parts)
    
    @classmethod
    def generate(
        cls,
        symbol: str,
        position: Dict,
        current_price: float,
        df30: Optional[pd.DataFrame] = None,
        pivot_data: Optional[Dict] = None,
    ) -> SLRationale:
        """
        SL 승인 요청 시 전략적 근거 생성
        
        Args:
            symbol: 심볼
            position: 포지션 정보
            current_price: 현재 가격
            df30: 30분봉 DataFrame
            pivot_data: 피봇 포인트 데이터 (선택)
            
        Returns:
            SLRationale 객체
        """
        try:
            entry_price = position.get("entry_price", current_price)
            pnl_pct = (current_price - entry_price) / entry_price * 100
            
            # 지표 계산
            rsi = 50
            ema_status = "unknown"
            atr_pct = 2.0
            
            if df30 is not None and len(df30) >= 20:
                try:
                    # Phase 2에서 만든 indicators 모듈 활용
                    from bot.core.indicators import calculate_indicators
                    indicators = calculate_indicators(df30, symbol)
                    if indicators:
                        rsi = indicators.get("rsi", 50)
                        ema_status = indicators.get("ema_status", "unknown")
                        atr_pct = indicators.get("atr_pct", 2)
                except ImportError:
                    # 폴백: 간단한 계산
                    pass
            
            # 피봇 데이터가 없으면 계산 시도
            if pivot_data is None and df30 is not None:
                try:
                    from bot.core.pivot_calculator import get_pivot_levels
                    pivot_data = get_pivot_levels(
                        df30, 
                        getattr(Config, 'PIVOT_TYPE', 'standard')
                    )
                except ImportError:
                    pass
            
            # 지지선 확인
            support_level, near_support = cls._check_support_level(
                current_price, pivot_data
            )
            
            # 회복 가능성 계산
            recovery_chance = cls._calculate_recovery_chance(
                rsi, ema_status, near_support, atr_pct
            )
            
            # SL 임계값 (Config에서)
            sl_threshold = getattr(Config, 'AI_SL_MIN', 0.03) * 100  # 3%
            
            # 추천 결정
            recommendation = "손절"
            confidence = 0.5
            risk_if_hold = ""
            
            if pnl_pct <= -5.0:
                recommendation = "손절"
                confidence = 0.90
                risk_if_hold = "손실 확대 위험 매우 높음"
            elif pnl_pct <= -3.5:
                recommendation = "손절"
                confidence = 0.80
                risk_if_hold = "손실 확대 위험 높음"
            elif recovery_chance >= 0.6:
                recommendation = "홀드"
                confidence = recovery_chance
                risk_if_hold = "지지선 이탈 시 추가 하락"
            elif pnl_pct <= -sl_threshold:
                recommendation = "손절"
                confidence = 0.7
                risk_if_hold = "추세 전환 미확인"
            else:
                recommendation = "홀드"
                confidence = 0.5
                risk_if_hold = "변동성 주의"
            
            # 근거 문자열 생성
            rationale = cls._build_rationale_string(
                pnl_pct, rsi, ema_status, near_support, support_level
            )
            
            return SLRationale(
                recommendation=recommendation,
                confidence=confidence,
                rationale=rationale,
                support_level=support_level,
                recovery_chance=recovery_chance,
                risk_if_hold=risk_if_hold,
                rsi=rsi,
                ema_status=ema_status,
                pnl_pct=pnl_pct,
            )
            
        except Exception as e:
            logger.error(f"[SL Rationale Error] {symbol}: {e}")
            return SLRationale(
                recommendation="손절",
                confidence=0.5,
                rationale="분석 오류 - 안전 우선",
                risk_if_hold="분석 불가",
            )


# =========================================================
# 편의 함수
# =========================================================

def generate_sl_rationale(
    symbol: str,
    pos: Dict,
    current_price: float,
    df30: Optional[pd.DataFrame] = None,
) -> Dict:
    """
    SL 근거 생성 (편의 함수)
    
    기존 AIDecisionEngine.generate_sl_rationale()과 동일한 시그니처
    
    Returns:
        딕셔너리 형태의 근거
    """
    result = SLReasonGenerator.generate(symbol, pos, current_price, df30)
    return result.to_dict()
