# -*- coding: utf-8 -*-
"""
Phoenix v5.3.2 — AI 판단 엔진 (캔들 패턴 통합)

GPT-4o-mini 기반 트레이딩 판단의 핵심 로직입니다.

🔥 v5.3.2 추가:
- 캔들 패턴 감지 모듈 통합
- AI 프롬프트에 캔들 패턴 정보 추가

v5.3.1 추가:
- 빗썸 예측차트 통합 (정확도 70%+ 코인만 활용)
- BTC 예측으로 시장 분위기 보조 분석
- AI 프롬프트에 예측 정보 추가

v5.3.0 수정:
- float 포맷팅 에러 수정 (str → float 변환)
- _safe_float() 헬퍼 함수 추가
"""

import pandas as pd
from openai import OpenAI
from typing import Dict, Optional, Any
from dataclasses import dataclass

from config import Config
from bot.utils.logger import get_logger
from bot.utils.decorators import retry, safe_execute
from bot.utils.cache import ai_cache

# AI 서브모듈
from bot.core.ai.response_parser import AIResponseParser, get_parser
from bot.core.ai.prompt_builder import PromptBuilder, get_tp_sl_guide, build_prompt
from bot.core.ai.long_term_analyzer import (
    LongTermAnalyzer, 
    analyze_long_term_trend,
    calculate_dynamic_sl,
    should_avoid_entry,
)
from bot.core.ai.sl_reason_generator import SLReasonGenerator, generate_sl_rationale

# 🆕 v5.3.1: 빗썸 예측차트 모듈
try:
    from bot.core.bithumb_predictor import (
        get_predictor,
        get_prediction,
        get_btc_prediction,
        get_prediction_for_ai,
        BithumbPredictor,
    )
    PREDICTOR_AVAILABLE = True
except ImportError:
    PREDICTOR_AVAILABLE = False

# 🆕 v5.3.2: 캔들 패턴 모듈
try:
    from bot.core.indicators.candle_patterns import (
        get_pattern_summary,
        detect_patterns,
        get_detector,
    )
    CANDLE_PATTERNS_AVAILABLE = True
except ImportError:
    CANDLE_PATTERNS_AVAILABLE = False

logger = get_logger("AI.DecisionEngine")


# =========================================================
# 헬퍼 함수
# =========================================================

def _safe_float(value: Any, default: float = 0.0) -> float:
    """안전한 float 변환"""
    if value is None:
        return default
    try:
        if isinstance(value, str):
            value = value.strip().replace("%", "").replace(",", "")
            if not value:
                return default
        result = float(value)
        if result != result or result == float('inf') or result == float('-inf'):
            return default
        return result
    except (ValueError, TypeError):
        return default


# =========================================================
# BTC 마켓 모드
# =========================================================

@dataclass
class BTCMarketMode:
    """BTC 마켓 모드"""
    mode: str
    label: str
    position_mult: float
    tp_mult: float
    strength_adjust: int
    min_change: float
    btc_change_24h: float = 0.0
    
    def to_dict(self) -> Dict:
        return {
            "mode": self.mode, "label": self.label,
            "position_mult": self.position_mult, "tp_mult": self.tp_mult,
            "strength_adjust": self.strength_adjust, "min_change": self.min_change,
            "btc_change_24h": self.btc_change_24h,
        }


BTC_MARKET_MODES = {
    "bull_strong": BTCMarketMode("bull_strong", "🚀 강세장", 1.3, 1.2, 2, 5.0),
    "bull": BTCMarketMode("bull", "📈 상승장", 1.15, 1.1, 1, 2.0),
    "neutral": BTCMarketMode("neutral", "➡️ 횡보", 1.0, 1.0, 0, -2.0),
    "bear": BTCMarketMode("bear", "📉 약세장", 0.8, 0.9, -1, -3.0),
    "bear_strong": BTCMarketMode("bear_strong", "🔻 급락장", 0.0, 0.0, -99, -999),
}


def get_btc_market_mode(btc_context: Optional[Dict] = None) -> Dict:
    """BTC 상태별 거래 모드 반환"""
    if not btc_context:
        return BTC_MARKET_MODES["neutral"].to_dict()
    
    change_24h = _safe_float(btc_context.get("change_24h", 0), 0)
    
    if change_24h >= 5.0:
        mode = BTC_MARKET_MODES["bull_strong"]
    elif change_24h >= 2.0:
        mode = BTC_MARKET_MODES["bull"]
    elif change_24h >= -2.0:
        mode = BTC_MARKET_MODES["neutral"]
    elif change_24h >= -3.0:
        mode = BTC_MARKET_MODES["bear"]
    else:
        mode = BTC_MARKET_MODES["bear_strong"]
    
    result = mode.to_dict()
    result["btc_change_24h"] = change_24h
    
    logger.info(
        f"[BTC MODE] {result['label']} (BTC {change_24h:+.1f}%) → "
        f"pos×{result['position_mult']}, tp×{result['tp_mult']}, str{result['strength_adjust']:+d}"
    )
    return result


# =========================================================
# AI 판단 엔진
# =========================================================

class AIDecisionEngine:
    """GPT-4o-mini 기반 AI 판단 엔진 (🆕 v5.3.2: 캔들 패턴 통합)"""
    
    MODEL = "gpt-4o-mini"
    TEMPERATURE = 0.2
    MAX_TOKENS = 800
    BTC_MARKET_MODES = {k: v.to_dict() for k, v in BTC_MARKET_MODES.items()}
    
    def __init__(self):
        self.parser = get_parser()
        self.client: Optional[OpenAI] = None
        self.predictor: Optional[BithumbPredictor] = None
        
        # v5.3.1: 빗썸 예측차트 모듈
        if PREDICTOR_AVAILABLE:
            self.predictor = get_predictor()
            logger.info("[AI Engine v5.3.2] 빗썸 예측차트 모듈 연동됨")
        
        # 🆕 v5.3.2: 캔들 패턴 모듈
        if CANDLE_PATTERNS_AVAILABLE:
            logger.info("[AI Engine v5.3.2] 캔들 패턴 모듈 연동됨")
    
    def set_api(self, api):
        """API 인스턴스 설정 (빗썸 예측차트용)"""
        if self.predictor:
            self.predictor.set_api(api)
    
    def _get_client(self) -> OpenAI:
        if self.client is None:
            if not Config.OPENAI_API_KEY:
                raise ValueError("OpenAI API key not configured")
            self.client = OpenAI(api_key=Config.OPENAI_API_KEY)
        return self.client
    
    @classmethod
    def get_btc_market_mode(cls, btc_context: Optional[Dict] = None) -> Dict:
        return get_btc_market_mode(btc_context)
    
    @staticmethod
    def calculate_indicators(df: pd.DataFrame) -> Dict:
        try:
            from bot.core.indicators import calculate_indicators
            return calculate_indicators(df)
        except ImportError:
            return {}
    
    @staticmethod
    def detect_market_condition(indicators: Dict) -> str:
        try:
            from bot.core.indicators import detect_market_condition
            return detect_market_condition(indicators)
        except ImportError:
            return "sideways"
    
    @staticmethod
    def analyze_long_term_trend(ind_daily: Dict, ind_weekly: Dict) -> Dict:
        return analyze_long_term_trend(ind_daily, ind_weekly)
    
    @staticmethod
    def calculate_dynamic_sl(atr_pct: float, market_condition: str, long_term_trend: Dict) -> float:
        return calculate_dynamic_sl(atr_pct, market_condition, long_term_trend)
    
    @staticmethod
    def get_tp_sl_guide(market_condition: str, atr_pct: float) -> Dict:
        return get_tp_sl_guide(market_condition, atr_pct)
    
    @classmethod
    def get_btc_context(cls, btc_df30: pd.DataFrame) -> Dict:
        """BTC 컨텍스트 생성 (v5.3.1: 예측차트 통합)"""
        try:
            from bot.core.indicators import calculate_indicators
            indicators = calculate_indicators(btc_df30, "BTC/KRW")
            
            if not indicators:
                return {"trend": "unknown", "change_24h": 0, "rsi": 50}
            
            change_24h = _safe_float(indicators.get("change_24h", 0), 0)
            
            if change_24h >= 3:
                trend = "급등 중 🚀"
            elif change_24h >= 1:
                trend = "상승 중 📈"
            elif change_24h <= -3:
                trend = "급락 중 🔻"
            elif change_24h <= -1:
                trend = "하락 중 📉"
            else:
                trend = "횡보 중 ➡️"
            
            result = {
                "trend": trend,
                "ema_status": indicators.get("ema_status", "unknown"),
                "change_24h": change_24h,
                "rsi": _safe_float(indicators.get("rsi", 50), 50),
                "price_vs_ema20_pct": _safe_float(indicators.get("price_vs_ema20_pct", 0), 0),
            }
            
            # v5.3.1: BTC 예측차트 정보 추가
            if PREDICTOR_AVAILABLE:
                try:
                    btc_pred = get_btc_prediction("1h")
                    if btc_pred and btc_pred.is_reliable:
                        result["prediction"] = {
                            "up_prob": btc_pred.up_probability,
                            "down_prob": btc_pred.down_probability,
                            "signal": btc_pred.signal,
                            "market_bias": btc_pred.market_bias,
                            "accuracy": btc_pred.accuracy,
                        }
                        result["prediction_prompt"] = btc_pred.to_ai_prompt()
                except Exception as e:
                    logger.debug(f"[BTC Pred] 조회 실패: {e}")
            
            return result
        except Exception as e:
            logger.error(f"[BTC Context Error] {e}")
            return {"trend": "unknown", "change_24h": 0, "rsi": 50}
    
    @classmethod
    def generate_sl_rationale(cls, symbol: str, pos: Dict, current_price: float,
                               df30: pd.DataFrame = None) -> Dict:
        return generate_sl_rationale(symbol, pos, current_price, df30)
    
    @classmethod
    def analyze(
        cls, symbol: str, df30: pd.DataFrame, df15: pd.DataFrame, df5: pd.DataFrame,
        portfolio_context: Optional[Dict] = None, btc_context: Optional[Dict] = None,
        performance_context: Optional[Dict] = None, df1h: Optional[pd.DataFrame] = None,
        df4h: Optional[pd.DataFrame] = None, df_daily: Optional[pd.DataFrame] = None,
        df_weekly: Optional[pd.DataFrame] = None,
    ) -> Dict:
        """AI 분석 수행 (🆕 v5.3.2: 캔들 패턴 통합)"""
        default_response = {
            "decision": "hold", "confidence": 0.5, "market_condition": "unknown",
            "position_type": "swing", "holding_period": "unknown",
            "tp": 0.03, "sl": 0.03, "tp_price": None, "sl_price": None,
            "position_weight": 0.2, "pivot_signal": None, "long_term_aligned": None,
            "reason": "분석 불가", "risk_note": "API 오류",
        }
        
        if not Config.OPENAI_API_KEY:
            default_response["reason"] = "OpenAI API key not configured"
            return default_response
        
        try:
            from bot.core.indicators import calculate_indicators, detect_market_condition
            
            indicators_30m = calculate_indicators(df30, symbol)
            indicators_15m = calculate_indicators(df15, symbol)
            indicators_5m = calculate_indicators(df5, symbol)
            indicators_1h = calculate_indicators(df1h, symbol) if df1h is not None and len(df1h) >= 20 else {}
            indicators_4h = calculate_indicators(df4h, symbol) if df4h is not None and len(df4h) >= 20 else {}
            indicators_daily = calculate_indicators(df_daily, symbol) if df_daily is not None and len(df_daily) >= 10 else {}
            indicators_weekly = calculate_indicators(df_weekly, symbol) if df_weekly is not None and len(df_weekly) >= 5 else {}
            
            if not indicators_30m:
                default_response["reason"] = "지표 계산 실패"
                return default_response
            
            market_condition = detect_market_condition(indicators_30m)
            long_term_trend = analyze_long_term_trend(indicators_daily, indicators_weekly)
            atr_pct = _safe_float(indicators_30m.get("atr_pct", 2), 2)
            recommended_sl = calculate_dynamic_sl(atr_pct, market_condition, long_term_trend)
            tp_sl_guide = get_tp_sl_guide(market_condition, atr_pct)
            
            pivot_data = None
            if getattr(Config, 'PIVOT_ENABLED', True):
                try:
                    from bot.core.pivot_calculator import get_pivot_levels
                    pivot_data = get_pivot_levels(df30, getattr(Config, 'PIVOT_TYPE', 'standard'))
                except ImportError:
                    pass
            
            btc_change = _safe_float(btc_context.get("change_24h", 0), 0) if btc_context else 0
            btc_mode = get_btc_market_mode(btc_context)
            
            # v5.3.1: 빗썸 예측차트 조회
            bithumb_prediction = ""
            if PREDICTOR_AVAILABLE:
                try:
                    bithumb_prediction = get_prediction_for_ai(symbol, "1h", include_btc=True)
                    if bithumb_prediction:
                        logger.debug(f"[AI] {symbol} 빗썸예측: {bithumb_prediction}")
                except Exception as e:
                    logger.debug(f"[AI] {symbol} 빗썸예측 조회 실패: {e}")
            
            # 🆕 v5.3.2: 캔들 패턴 감지
            candle_patterns = ""
            if CANDLE_PATTERNS_AVAILABLE:
                try:
                    candle_patterns = get_pattern_summary(df30)
                    if candle_patterns:
                        logger.debug(f"[AI] {symbol} 캔들패턴: {candle_patterns}")
                except Exception as e:
                    logger.debug(f"[AI] {symbol} 캔들패턴 감지 실패: {e}")
            
            # 조기 차단 조건
            if market_condition == "strong_downtrend":
                return {**default_response, "decision": "hold", "confidence": 0.9,
                        "market_condition": market_condition, "reason": "강한 하락장 - 매수 금지",
                        "pivot_data": pivot_data, "btc_mode": btc_mode,
                        "long_term_trend": long_term_trend, "bithumb_prediction": bithumb_prediction,
                        "candle_patterns": candle_patterns}
            
            if long_term_trend["trend"] in ["bear", "strong_bear"]:
                return {**default_response, "decision": "hold", "confidence": 0.85,
                        "market_condition": market_condition,
                        "reason": f"주봉 하락 추세 ({long_term_trend['recommendation']})",
                        "pivot_data": pivot_data, "btc_mode": btc_mode,
                        "long_term_trend": long_term_trend, "bithumb_prediction": bithumb_prediction,
                        "candle_patterns": candle_patterns}
            
            if btc_change <= -3:
                return {**default_response, "decision": "hold", "confidence": 0.85,
                        "market_condition": market_condition, "reason": f"BTC 급락 {btc_change:.1f}%",
                        "pivot_data": pivot_data, "btc_mode": btc_mode,
                        "long_term_trend": long_term_trend, "bithumb_prediction": bithumb_prediction,
                        "candle_patterns": candle_patterns}
            
            # 프롬프트 생성 (🆕 v5.3.2: 캔들 패턴 포함)
            prompt = build_prompt(
                symbol=symbol, indicators_30m=indicators_30m, indicators_15m=indicators_15m,
                indicators_5m=indicators_5m, market_condition=market_condition,
                tp_sl_guide=tp_sl_guide, pivot_data=pivot_data, portfolio_context=portfolio_context,
                btc_context=btc_context, performance_context=performance_context,
                indicators_1h=indicators_1h, indicators_4h=indicators_4h,
                indicators_daily=indicators_daily, indicators_weekly=indicators_weekly,
                long_term_trend=long_term_trend, recommended_sl=recommended_sl,
                bithumb_prediction=bithumb_prediction,
                candle_patterns=candle_patterns,  # 🆕 v5.3.2
            )
            
            client = OpenAI(api_key=Config.OPENAI_API_KEY)
            response = client.chat.completions.create(
                model=cls.MODEL, response_format={"type": "json_object"},
                messages=[
                    {"role": "system", "content": (
                        "You are a professional crypto trading AI. "
                        "Always respond in valid JSON format only. "
                        "RSI/ADX are reference indicators only. "
                        "Focus on long-term trend for decision making. "
                        "Consider Bithumb prediction chart as supplementary indicator. "
                        "Consider candle patterns as timing reference only."  # 🆕 v5.3.2
                    )},
                    {"role": "user", "content": prompt},
                ],
                temperature=cls.TEMPERATURE, max_tokens=cls.MAX_TOKENS,
            )
            
            raw_content = response.choices[0].message.content
            parser = get_parser()
            result = parser.parse_response(raw_content, market_condition)
            
            result["confidence"] = _safe_float(result.get("confidence", 0.5), 0.5)
            result["tp"] = _safe_float(result.get("tp", 0.03), 0.03)
            result["sl"] = _safe_float(result.get("sl", 0.03), 0.03)
            result["position_weight"] = _safe_float(result.get("position_weight", 0.2), 0.2)
            
            sl_min = getattr(Config, 'AI_SL_MIN', 0.03)
            if result["sl"] < sl_min:
                result["sl"] = sl_min
            
            if pivot_data:
                result["pivot_data"] = pivot_data
            result["btc_mode"] = btc_mode
            result["long_term_trend"] = long_term_trend
            result["recommended_sl"] = recommended_sl
            result["bithumb_prediction"] = bithumb_prediction
            result["candle_patterns"] = candle_patterns  # 🆕 v5.3.2
            result["indicators_1h"] = indicators_1h
            result["indicators_4h"] = indicators_4h
            result["indicators_daily"] = indicators_daily
            result["indicators_weekly"] = indicators_weekly
            
            if result["market_condition"] == "strong_downtrend" and result["decision"] == "buy":
                result["decision"] = "hold"
                result["risk_note"] = "강한 하락장 - AI buy 차단됨"
            
            # 로그 출력 (v5.3.2: 캔들 패턴 포함)
            pred_info = ", pred=활성" if bithumb_prediction else ""
            candle_info = f", candle={candle_patterns[:20]}..." if candle_patterns else ""
            logger.info(
                f"[AI-mini v5.3.2] {symbol} → {result['decision']} "
                f"(conf={result['confidence']:.2f}, tp={result['tp']:.2%}, sl={result['sl']:.2%}, "
                f"rec_sl={_safe_float(recommended_sl, 0.03):.2%}, "
                f"lt={long_term_trend.get('trend', 'N/A')}{pred_info}{candle_info})"
            )
            
            return result
            
        except Exception as e:
            logger.error(f"[AI Engine Error] {symbol}: {e}")
            default_response["reason"] = f"error: {str(e)}"
            return default_response
    
    @classmethod
    def analyze_simple(cls, symbol, df30, df15, df5) -> Dict:
        return cls.analyze(symbol, df30, df15, df5)


# =========================================================
# 편의 함수
# =========================================================

def analyze_coin(symbol: str, df30: pd.DataFrame, df15: pd.DataFrame,
                 df5: pd.DataFrame, **kwargs) -> Dict:
    return AIDecisionEngine.analyze(symbol, df30, df15, df5, **kwargs)


def get_ai_decision(symbol: str, df30: pd.DataFrame, df15: pd.DataFrame,
                    df5: pd.DataFrame, **kwargs) -> Dict:
    return AIDecisionEngine.analyze(symbol, df30, df15, df5, **kwargs)
