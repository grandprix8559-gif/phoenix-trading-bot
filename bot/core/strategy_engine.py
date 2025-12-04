# -*- coding: utf-8 -*-
"""
Phoenix v5.3.0 — Strategy Engine (Phase 2 indicators 모듈 적용)

🔥 v5.3.0 변경:
- bot.core.indicators 모듈 사용 (중복 제거)
- 로컬 지표 함수 삭제 → indicators 모듈로 통합
- IndicatorResult 클래스 활용

🔧 v5.1.0b 기능 유지:
- ADX/RSI 참고용 전환 (가중치 감소)
- 동적 분할 진입 + 장기 방향성
- 피봇 포인트 신호 통합
- MTF 분석 (30m/15m/5m)
"""

import numpy as np
import pandas as pd
from typing import Dict, Optional, Tuple

from config import Config
from bot.core.pivot_calculator import get_pivot_levels, get_pivot_signal
from bot.utils.logger import get_logger

# 🆕 v5.3.0: Phase 2 indicators 모듈 임포트
from bot.core.indicators.technical import (
    ema,
    rsi_manual as rsi,
    macd_manual as macd,
    bollinger_manual as bollinger,
    stoch_rsi_manual as stoch_rsi,
    calculate_atr,
    calculate_indicators_full,
    get_atr_info,
    IndicatorResult,
    ATRInfo,
)

logger = get_logger("StrategyEngine")


class StrategyEngine:
    """피봇 통합 전략 엔진 (v5.3.0 Phase 2 indicators 적용)"""

    VOLUME_BREAKOUT_ENABLED = False
    VOLUME_BREAKOUT_MULT = 2.5
    VOLUME_BREAKOUT_RSI_MIN = 45
    VOLUME_BREAKOUT_RSI_MAX = 70
    VOLUME_BREAKOUT_BONUS = 3

    def __init__(self, price_feed=None, aggressive=False):
        self.price_feed = price_feed
        self.aggressive = aggressive
        
        # Config에서 임계값 가져오기 (기본값 6)
        self.buy_threshold = 3 if aggressive else getattr(Config, 'SIGNAL_THRESHOLD', 6)
        self.sell_threshold = -5 if aggressive else -4
        self.pivot_enabled = getattr(Config, 'PIVOT_ENABLED', True)
        
        logger.info(f"[StrategyEngine v5.3.0] BUY>={self.buy_threshold}, Phase 2 indicators 적용")

    # =========================================================
    # 장기 방향성 분석 (일/주/월봉)
    # =========================================================
    def analyze_long_term_trend(self, df_daily=None, df_weekly=None, df_monthly=None) -> Dict:
        """
        장기 방향성 분석
        
        Returns:
            {
                "trend": "bull" | "neutral" | "bear",
                "daily_trend": str,
                "weekly_trend": str,
                "monthly_trend": str,
                "entry_ratio": float (0.2 ~ 0.6),
                "confidence": float (0.0 ~ 1.0),
            }
        """
        try:
            trends = []
            details = {}
            
            # 일봉 분석
            if df_daily is not None and len(df_daily) >= 20:
                daily_trend = self._analyze_trend(df_daily)
                trends.append(daily_trend)
                details["daily_trend"] = daily_trend
            else:
                details["daily_trend"] = "unknown"
            
            # 주봉 분석
            if df_weekly is not None and len(df_weekly) >= 10:
                weekly_trend = self._analyze_trend(df_weekly)
                trends.append(weekly_trend)
                details["weekly_trend"] = weekly_trend
            else:
                details["weekly_trend"] = "unknown"
            
            # 월봉 분석
            if df_monthly is not None and len(df_monthly) >= 6:
                monthly_trend = self._analyze_trend(df_monthly)
                trends.append(monthly_trend)
                details["monthly_trend"] = monthly_trend
            else:
                details["monthly_trend"] = "unknown"
            
            # 종합 판단
            if not trends:
                return {
                    "trend": "neutral",
                    "entry_ratio": Config.ENTRY_RATIO_SIDEWAYS,
                    "confidence": 0.3,
                    **details,
                }
            
            bull_count = sum(1 for t in trends if t == "bull")
            bear_count = sum(1 for t in trends if t == "bear")
            
            if bull_count >= 2:
                overall = "bull"
                entry_ratio = Config.ENTRY_RATIO_STRONG_UP if bull_count == 3 else Config.ENTRY_RATIO_WEAK_UP
                confidence = bull_count / len(trends)
            elif bear_count >= 2:
                overall = "bear"
                entry_ratio = Config.ENTRY_RATIO_STRONG_DOWN if bear_count == 3 else Config.ENTRY_RATIO_WEAK_DOWN
                confidence = bear_count / len(trends)
            else:
                overall = "neutral"
                entry_ratio = Config.ENTRY_RATIO_SIDEWAYS
                confidence = 0.5
            
            return {
                "trend": overall,
                "entry_ratio": entry_ratio,
                "confidence": round(confidence, 2),
                **details,
            }
            
        except Exception as e:
            logger.error(f"[Long Term Trend Error] {e}")
            return {
                "trend": "neutral",
                "entry_ratio": getattr(Config, 'ENTRY_RATIO_SIDEWAYS', 0.30),
                "confidence": 0.3,
            }
    
    def _analyze_trend(self, df) -> str:
        """
        🔧 v5.1.0b: 단일 타임프레임 추세 분석 (RSI 가중치 감소)
        🆕 v5.3.0: indicators 모듈 사용
        """
        try:
            close = df["close"]
            
            # 🆕 v5.3.0: indicators 모듈의 ema 함수 사용
            ema20_val = ema(close, 20).iloc[-1]
            ema50_val = ema(close, min(50, len(df) - 1)).iloc[-1]
            
            # 최근 가격 위치
            current = close.iloc[-1]
            
            # 🆕 v5.3.0: indicators 모듈의 rsi 함수 사용
            r = rsi(close, 14).iloc[-1]
            
            score = 0
            
            # EMA 정배열 (가중치 유지)
            if ema20_val > ema50_val:
                score += 2
            else:
                score -= 2
            
            # 가격 > EMA20 (가중치 유지)
            if current > ema20_val:
                score += 1
            else:
                score -= 1
            
            # 🔧 v5.1.0b: RSI 가중치 감소 (참고용)
            if r > 60:
                score += 0.5
            elif r < 40:
                score -= 0.5
            
            if score >= 2:
                return "bull"
            elif score <= -2:
                return "bear"
            else:
                return "neutral"
                
        except:
            return "neutral"

    # =========================================================
    # 🆕 v5.3.0: ATR 등급 판단 (indicators 모듈 사용)
    # =========================================================
    def get_atr_grade(self, df) -> Dict:
        """
        ATR 등급 판단 (v5.3.0: indicators 모듈 사용)
        
        Returns:
            {
                "grade": "low" | "mid" | "high" | "extreme",
                "atr": float,
                "atr_pct": float,
                "dca_interval": float,
            }
        """
        try:
            if df is None or len(df) < 15:
                return {
                    "grade": "mid",
                    "atr": 0,
                    "atr_pct": 0,
                    "dca_interval": Config.ATR_INTERVAL_MEDIUM,
                }
            
            # 🆕 v5.3.0: indicators 모듈의 get_atr_info 사용
            atr_info = get_atr_info(df)
            
            # ATR 등급에 따른 DCA 간격 결정
            if atr_info.grade == "low":
                dca_interval = Config.ATR_INTERVAL_LOW
            elif atr_info.grade == "mid":
                dca_interval = Config.ATR_INTERVAL_MEDIUM
            elif atr_info.grade == "high":
                dca_interval = Config.ATR_INTERVAL_HIGH
            else:  # extreme
                dca_interval = Config.ATR_INTERVAL_EXTREME
            
            return {
                "grade": atr_info.grade,
                "atr": round(atr_info.value, 4),
                "atr_pct": round(atr_info.pct, 2),
                "dca_interval": dca_interval,
            }
            
        except Exception as e:
            logger.error(f"[ATR Grade Error] {e}")
            return {
                "grade": "mid",
                "atr": 0,
                "atr_pct": 0,
                "dca_interval": Config.ATR_INTERVAL_MEDIUM,
            }

    # =========================================================
    # 동적 진입 비율 계산
    # =========================================================
    def calculate_entry_params(self, df30, df_daily=None, df_weekly=None, df_monthly=None) -> Dict:
        """
        동적 진입 파라미터 계산
        
        Returns:
            {
                "entry_ratio": float (1차 진입 비율),
                "dca_interval": float (분할 간격),
                "trend": str,
                "atr_grade": str,
            }
        """
        # 장기 방향성
        long_term = self.analyze_long_term_trend(df_daily, df_weekly, df_monthly)
        
        # ATR 등급
        atr_info = self.get_atr_grade(df30)
        
        return {
            "entry_ratio": long_term["entry_ratio"],
            "dca_interval": atr_info["dca_interval"],
            "trend": long_term["trend"],
            "trend_confidence": long_term.get("confidence", 0.5),
            "atr_grade": atr_info["grade"],
            "atr_pct": atr_info["atr_pct"],
        }

    def _calculate_volume_ratio(self, df, period: int = 20) -> float:
        """거래량 비율 계산"""
        try:
            if df is None or len(df) < period + 1:
                return 1.0
            
            current_vol = df["volume"].iloc[-1]
            avg_vol = df["volume"].iloc[-(period+1):-1].mean()
            
            if avg_vol <= 0:
                return 1.0
            
            return current_vol / avg_vol
        except:
            return 1.0

    def _check_volume_breakout(self, df) -> Dict:
        """거래량 폭발 체크 (v5.0.9: 비활성화됨)"""
        if not self.VOLUME_BREAKOUT_ENABLED:
            volume_ratio = self._calculate_volume_ratio(df, 20)
            return {
                "is_breakout": False,
                "volume_ratio": round(volume_ratio, 2),
                "bonus": 0,
                "rsi": 50,
            }
        
        try:
            if df is None or len(df) < 21:
                return {"is_breakout": False, "volume_ratio": 1.0, "bonus": 0}
            
            volume_ratio = self._calculate_volume_ratio(df, 20)
            
            # 🆕 v5.3.0: indicators 모듈의 rsi 사용
            r = rsi(df["close"], 14)
            current_rsi = r.iloc[-1]
            is_green = df["close"].iloc[-1] > df["open"].iloc[-1]
            price_rising = df["close"].iloc[-1] > df["close"].iloc[-2]
            
            is_breakout = (
                volume_ratio >= self.VOLUME_BREAKOUT_MULT and
                self.VOLUME_BREAKOUT_RSI_MIN <= current_rsi <= self.VOLUME_BREAKOUT_RSI_MAX and
                is_green and
                price_rising
            )
            
            bonus = self.VOLUME_BREAKOUT_BONUS if is_breakout else 0
            
            return {
                "is_breakout": is_breakout,
                "volume_ratio": round(volume_ratio, 2),
                "bonus": bonus,
                "rsi": round(current_rsi, 1) if not np.isnan(current_rsi) else 50,
            }
            
        except Exception as e:
            logger.error(f"[VOL BREAKOUT ERROR] {e}")
            return {"is_breakout": False, "volume_ratio": 1.0, "bonus": 0}

    def get_signal(self, symbol: str, df30, df15, df5) -> Dict:
        try:
            if df30 is None or len(df30) < 50:
                return {"decision": "hold", "strength_sum": 0, "detail": {}, "volume_ratio": 1.0}

            # 실시간 가격 적용
            if self.price_feed:
                price = getattr(self.price_feed, 'get_price', lambda x: None)(symbol)
                if price and df5 is not None:
                    df5 = df5.copy()
                    df5.iloc[-1, df5.columns.get_loc("close")] = price

            # MTF 신호
            s30 = self._tf_signal(df30)
            s15 = self._tf_signal(df15) if df15 is not None else {"strength": 0}
            s5 = self._tf_signal(df5) if df5 is not None else {"strength": 0}
            
            mtf_strength = s30["strength"] + s15["strength"] + s5["strength"]
            
            # 피봇 보너스
            pivot_bonus = 0
            pivot_signal = None
            
            if self.pivot_enabled:
                pivot_data = get_pivot_levels(df30, getattr(Config, 'PIVOT_TYPE', 'standard'))
                if pivot_data:
                    price = df30["close"].iloc[-1]
                    pivot_result = get_pivot_signal(price, pivot_data, 0.005)
                    pivot_signal = pivot_result
                    
                    if pivot_result.get("signal") == "buy":
                        pivot_bonus = int(pivot_result.get("confidence", 0.5) * 4)
                    elif pivot_result.get("signal") == "sell":
                        pivot_bonus = -int(pivot_result.get("confidence", 0.5) * 4)
            
            # 거래량 폭발 체크
            vol_breakout = self._check_volume_breakout(df30)
            volume_bonus = vol_breakout.get("bonus", 0)
            volume_ratio = vol_breakout.get("volume_ratio", 1.0)
            is_volume_breakout = vol_breakout.get("is_breakout", False)
            
            # 총 점수 계산
            total = mtf_strength + pivot_bonus + volume_bonus
            
            # 임계값 적용
            if total >= self.buy_threshold:
                decision = "buy"
            elif total <= self.sell_threshold:
                decision = "sell"
            else:
                decision = "hold"

            logger.info(
                f"[{symbol}] MTF={mtf_strength}, pivot={pivot_bonus:+d}, total={total} → {decision} (threshold={self.buy_threshold})"
            )

            return {
                "decision": decision,
                "strength_sum": total,
                "mtf_strength": mtf_strength,
                "pivot_bonus": pivot_bonus,
                "pivot_signal": pivot_signal,
                "volume_bonus": volume_bonus,
                "volume_ratio": volume_ratio,
                "is_volume_breakout": is_volume_breakout,
                "detail": {"30m": s30, "15m": s15, "5m": s5},
            }
        except Exception as e:
            logger.error(f"[Strategy ERROR] {symbol}: {e}")
            return {"decision": "hold", "strength_sum": 0, "detail": {}, "volume_ratio": 1.0}

    def _tf_signal(self, df) -> Dict:
        """
        🔧 v5.1.0b: 타임프레임 신호 (RSI 가중치 감소)
        🆕 v5.3.0: indicators 모듈 사용
        """
        try:
            close = df["close"]
            
            # 🆕 v5.3.0: indicators 모듈 함수 사용
            ema20_series = ema(close, 20)
            ema50_series = ema(close, 50)
            r = rsi(close, 14)
            stoch = stoch_rsi(close)
            macd_line, _, macd_hist = macd(close)
            bb_u, _, bb_l = bollinger(close)

            strength = 0

            # EMA (가중치 유지)
            if ema20_series.iloc[-1] > ema50_series.iloc[-1]:
                strength += 3 if ema20_series.iloc[-2] <= ema50_series.iloc[-2] else 1
            else:
                strength -= 3 if ema20_series.iloc[-2] >= ema50_series.iloc[-2] else 1

            # 🔧 v5.1.0b: RSI 가중치 감소 (참고용)
            rsi_val = r.iloc[-1]
            if rsi_val > 70:
                strength -= 1
            elif rsi_val > 60:
                strength += 0.5
            elif rsi_val < 30:
                strength += 1
            elif rsi_val < 40:
                strength -= 0.5

            # StochRSI (가중치 유지)
            if stoch.iloc[-1] > 0.8 and stoch.iloc[-2] <= 0.8:
                strength += 2
            elif stoch.iloc[-1] < 0.2 and stoch.iloc[-2] >= 0.2:
                strength += 2

            # MACD (가중치 유지)
            if macd_hist.iloc[-1] > 0 and macd_hist.iloc[-2] <= 0:
                strength += 3
            elif macd_hist.iloc[-1] < 0 and macd_hist.iloc[-2] >= 0:
                strength -= 3

            # Bollinger (가중치 유지)
            price = close.iloc[-1]
            if price < bb_l.iloc[-1]:
                strength += 2
            elif price > bb_u.iloc[-1]:
                strength -= 2

            return {"strength": int(strength)}
        except:
            return {"strength": 0}


def get_consensus_signal(strategy_signal: dict, ai_decision: dict):
    """전략 + AI 합의"""
    strat = strategy_signal.get("decision", "hold")
    strat_strength = strategy_signal.get("strength_sum", 0)
    ai = ai_decision.get("decision", "hold")
    ai_conf = ai_decision.get("confidence", 0.5)
    
    # 임계값 6 기준
    threshold = getattr(Config, 'SIGNAL_THRESHOLD', 6)

    if strat == "sell":
        return "sell"
    if strat == "buy":
        return "buy"
    # AI가 buy이고 strength가 임계값-3 이상이면 buy
    if ai == "buy" and strat_strength >= (threshold - 3) and ai_conf > 0.6:
        return "buy"
    return "hold"
