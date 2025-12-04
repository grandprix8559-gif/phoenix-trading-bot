# -*- coding: utf-8 -*-
"""
Phoenix v5.3.2 — AI 프롬프트 빌더 (캔들 패턴 통합)

GPT-4o-mini용 프롬프트 생성을 담당합니다.

🔥 v5.3.2 추가:
- 캔들 패턴 정보 섹션 추가
- candle_patterns 파라미터 지원

v5.3.1 추가:
- 빗썸 예측차트 정보 섹션 추가
- bithumb_prediction 파라미터 지원

v5.3.0b 수정:
- _safe_float() 헬퍼 함수 추가
- 모든 float 포맷팅에 _safe_float() 적용
"""

from typing import Dict, Optional, Any, List
from dataclasses import dataclass

from config import Config
from bot.utils.logger import get_logger

logger = get_logger("AI.PromptBuilder")


# =========================================================
# 헬퍼 함수
# =========================================================

def _safe_float(value: Any, default: float = 0.0) -> float:
    """
    안전한 float 변환
    
    문자열, None 등을 안전하게 float으로 변환합니다.
    
    Args:
        value: 변환할 값
        default: 변환 실패 시 기본값
        
    Returns:
        float 값
    """
    if value is None:
        return default
    
    try:
        if isinstance(value, str):
            # % 제거
            value = value.strip().replace("%", "").replace(",", "")
            if not value:
                return default
        
        result = float(value)
        
        # NaN/Inf 체크
        if result != result or result == float('inf') or result == float('-inf'):
            return default
        
        return result
    except (ValueError, TypeError):
        return default


def _safe_int(value: Any, default: int = 0) -> int:
    """안전한 int 변환"""
    return int(_safe_float(value, float(default)))


# =========================================================
# TP/SL 가이드
# =========================================================

@dataclass
class TPSLGuide:
    """TP/SL 가이드"""
    tp_min: float
    tp_max: float
    sl_min: float
    sl_max: float
    
    def to_dict(self) -> Dict[str, float]:
        return {
            "tp_min": self.tp_min,
            "tp_max": self.tp_max,
            "sl_min": self.sl_min,
            "sl_max": self.sl_max,
        }


def get_tp_sl_guide(market_condition: str, atr_pct: float = 2.0) -> Dict[str, float]:
    """
    시장 상황별 TP/SL 가이드 반환
    
    Args:
        market_condition: 시장 상황
        atr_pct: ATR 퍼센트
        
    Returns:
        TP/SL 가이드 딕셔너리
    """
    sl_min = getattr(Config, 'AI_SL_MIN', 0.03)
    sl_max = getattr(Config, 'AI_SL_MAX', 0.07)
    
    guides = {
        "strong_uptrend": TPSLGuide(0.05, 0.10, max(0.03, sl_min), 0.05),
        "weak_uptrend": TPSLGuide(0.03, 0.05, max(0.03, sl_min), 0.04),
        "sideways": TPSLGuide(0.015, 0.03, sl_min, 0.04),
        "high_volatility": TPSLGuide(0.02, 0.04, sl_min, 0.06),
        "weak_downtrend": TPSLGuide(0.02, 0.03, sl_min, 0.05),
        "strong_downtrend": TPSLGuide(0.015, 0.025, sl_min, sl_max),
    }
    
    guide = guides.get(market_condition, guides["sideways"])
    result = guide.to_dict()
    
    # ATR 기반 조정
    atr_pct = _safe_float(atr_pct, 2.0)
    if atr_pct > 4:
        for k in result:
            result[k] *= 1.3
    elif atr_pct < 2:
        for k in result:
            result[k] *= 0.9
    
    # 최소/최대 SL 보장
    result["sl_min"] = max(result["sl_min"], sl_min)
    result["sl_max"] = min(result["sl_max"], sl_max)
    
    return result


# =========================================================
# 프롬프트 빌더
# =========================================================

class PromptBuilder:
    """
    GPT-4o-mini용 프롬프트 빌더
    
    다양한 지표와 컨텍스트를 받아서 최적화된 프롬프트를 생성합니다.
    """
    
    @staticmethod
    def _format_pivot(pivot_data: Optional[Dict]) -> str:
        """피봇 포인트 섹션 포맷"""
        if not pivot_data:
            return ""
        
        p = _safe_float(pivot_data.get('P', 0), 0)
        r1 = _safe_float(pivot_data.get('R1', 0), 0)
        r2 = _safe_float(pivot_data.get('R2', 0), 0)
        s1 = _safe_float(pivot_data.get('S1', 0), 0)
        s2 = _safe_float(pivot_data.get('S2', 0), 0)
        
        return f"""
━━━━━━━━━━━━━━━━━━━━━━
📍 피봇 포인트
━━━━━━━━━━━━━━━━━━━━━━
P: {p:,.0f}
R1: {r1:,.0f}, R2: {r2:,.0f}
S1: {s1:,.0f}, S2: {s2:,.0f}
"""
    
    @staticmethod
    def _format_btc_context(btc_context: Optional[Dict]) -> str:
        """BTC 컨텍스트 섹션 포맷"""
        if not btc_context:
            return ""
        
        # 🔥 v5.3.0b: _safe_float 적용
        change_24h = _safe_float(btc_context.get('change_24h', 0), 0)
        rsi = _safe_float(btc_context.get('rsi', 50), 50)
        
        return f"""
━━━━━━━━━━━━━━━━━━━━━━
₿ BTC 상황
━━━━━━━━━━━━━━━━━━━━━━
추세: {btc_context.get('trend', 'unknown')}
24h 변화: {change_24h:+.1f}%
RSI: {rsi:.0f}
"""
    
    @staticmethod
    def _format_bithumb_prediction(bithumb_prediction: Optional[str]) -> str:
        """
        🆕 v5.3.1: 빗썸 예측차트 섹션 포맷
        
        정확도 70%+ 코인만 표시됨
        """
        if not bithumb_prediction:
            return ""
        
        return f"""
━━━━━━━━━━━━━━━━━━━━━━
🔮 빗썸 AI 예측차트 (참고용)
━━━━━━━━━━━━━━━━━━━━━━
{bithumb_prediction}
⚠️ 정확도 70% 이상 코인만 표시됨
⚠️ 보조지표로만 활용 (맹신 금지)
"""
    
    @staticmethod
    def _format_candle_patterns(candle_patterns: Optional[str]) -> str:
        """
        🆕 v5.3.2: 캔들 패턴 섹션 포맷
        
        감지된 캔들 패턴 정보를 AI 프롬프트에 포함
        """
        if not candle_patterns:
            return ""
        
        return f"""
━━━━━━━━━━━━━━━━━━━━━━
🕯️ 캔들 패턴 (30분봉)
━━━━━━━━━━━━━━━━━━━━━━
{candle_patterns}
⚠️ 보조지표로만 참고 (단독 판단 금지)
"""
    
    @staticmethod
    def _format_portfolio_context(portfolio_context: Optional[Dict]) -> str:
        """포트폴리오 컨텍스트 섹션 포맷"""
        if not portfolio_context:
            return ""
        
        position_count = _safe_int(portfolio_context.get('position_count', 0), 0)
        available_krw = _safe_float(portfolio_context.get('available_krw', 0), 0)
        
        return f"""
[포트폴리오] 포지션: {position_count}개, 가용: {available_krw:,.0f} KRW
"""
    
    @staticmethod
    def _format_performance_context(performance_context: Optional[Dict]) -> str:
        """성과 컨텍스트 섹션 포맷"""
        if not performance_context:
            return ""
        
        # 🔥 v5.3.0b: _safe_float 적용
        daily_pnl = _safe_float(performance_context.get('daily_pnl_pct', 0), 0)
        loss_streak = _safe_int(performance_context.get('loss_streak', 0), 0)
        
        return f"""
[성과] 일일 손익: {daily_pnl:+.2f}%, 연속 손실: {loss_streak}회
"""
    
    @classmethod
    def build_trading_prompt(
        cls,
        symbol: str,
        indicators_30m: Optional[Dict] = None,
        indicators_15m: Optional[Dict] = None,
        indicators_5m: Optional[Dict] = None,
        indicators_1h: Optional[Dict] = None,
        indicators_4h: Optional[Dict] = None,
        indicators_daily: Optional[Dict] = None,
        indicators_weekly: Optional[Dict] = None,
        market_condition: str = "sideways",
        long_term_trend: Optional[Dict] = None,
        recommended_sl: Optional[float] = None,
        pivot_data: Optional[Dict] = None,
        btc_context: Optional[Dict] = None,
        portfolio_context: Optional[Dict] = None,
        performance_context: Optional[Dict] = None,
        tp_sl_guide: Optional[Dict] = None,
        bithumb_prediction: Optional[str] = None,  # v5.3.1
        candle_patterns: Optional[str] = None,     # 🆕 v5.3.2
    ) -> str:
        """
        매매 판단용 프롬프트 생성
        
        Args:
            symbol: 심볼 (예: SOL/KRW)
            indicators_*: 각 타임프레임별 지표
            market_condition: 시장 상황
            long_term_trend: 장기 추세 분석 결과
            recommended_sl: 권장 SL
            pivot_data: 피봇 포인트 데이터
            btc_context: BTC 컨텍스트
            portfolio_context: 포트폴리오 컨텍스트
            performance_context: 성과 컨텍스트
            tp_sl_guide: TP/SL 가이드
            bithumb_prediction: v5.3.1 빗썸 예측차트 정보
            candle_patterns: 🆕 v5.3.2 캔들 패턴 정보
            
        Returns:
            프롬프트 문자열
        """
        # 기본값 처리
        ind_30m = indicators_30m or {}
        ind_15m = indicators_15m or {}
        ind_5m = indicators_5m or {}
        ind_1h = indicators_1h or {}
        ind_4h = indicators_4h or {}
        ind_daily = indicators_daily or {}
        ind_weekly = indicators_weekly or {}
        
        lt_trend = long_term_trend or {
            "trend": "neutral",
            "recommendation": "관망",
            "weekly_momentum": "횡보",
            "daily_momentum": "횡보"
        }
        
        # SL 범위
        sl_min = getattr(Config, 'AI_SL_MIN', 0.03)
        sl_max = getattr(Config, 'AI_SL_MAX', 0.07)
        
        # 🔥 v5.3.0b: _safe_float 적용
        rec_sl = _safe_float(recommended_sl, sl_min)
        current_price = _safe_float(ind_30m.get("current_price", 0), 0)
        atr_pct = _safe_float(ind_30m.get("atr_pct", 2), 2)
        
        # 섹션 포맷
        pivot_str = cls._format_pivot(pivot_data)
        btc_str = cls._format_btc_context(btc_context)
        portfolio_str = cls._format_portfolio_context(portfolio_context)
        perf_str = cls._format_performance_context(performance_context)
        pred_str = cls._format_bithumb_prediction(bithumb_prediction)  # v5.3.1
        candle_str = cls._format_candle_patterns(candle_patterns)       # 🆕 v5.3.2
        
        # 프롬프트 생성
        prompt = f"""
당신은 암호화폐 트레이딩 전문가입니다. 장기 추세를 중시하며 보수적으로 판단합니다.

[코인] {symbol}
[현재가] {current_price:,.0f} KRW

━━━━━━━━━━━━━━━━━━━━━━
📊 장기 추세 (가장 중요)
━━━━━━━━━━━━━━━━━━━━━━
[주봉 분석]
• EMA 상태: {ind_weekly.get('ema_status', 'N/A')}
• RSI: {ind_weekly.get('rsi', 'N/A')}
• ADX: {ind_weekly.get('adx', 'N/A')}
• 추세 판단: {lt_trend['weekly_momentum']}

[일봉 분석]
• EMA 상태: {ind_daily.get('ema_status', 'N/A')}
• RSI: {ind_daily.get('rsi', 'N/A')}
• 24h 변화: {ind_daily.get('change_24h', 'N/A')}%
• 추세 판단: {lt_trend['daily_momentum']}

⚠️ 장기 추세: {lt_trend['trend']} ({lt_trend['recommendation']})
⚠️ 일봉/주봉 방향이 다르면 진입을 피하세요.

━━━━━━━━━━━━━━━━━━━━━━
📈 중단기 지표
━━━━━━━━━━━━━━━━━━━━━━
[4시간봉] EMA: {ind_4h.get('ema_status', 'N/A')}, RSI: {ind_4h.get('rsi', 'N/A')} (참고)
[1시간봉] EMA: {ind_1h.get('ema_status', 'N/A')}, RSI: {ind_1h.get('rsi', 'N/A')} (참고)
[30분봉] EMA: {ind_30m.get('ema_status', 'N/A')}, RSI: {ind_30m.get('rsi', 'N/A')}, ADX: {ind_30m.get('adx', 'N/A')}
[15분봉] EMA: {ind_15m.get('ema_status', 'N/A')}, RSI: {ind_15m.get('rsi', 'N/A')}

━━━━━━━━━━━━━━━━━━━━━━
⚡ 변동성 & SL 가이드
━━━━━━━━━━━━━━━━━━━━━━
• ATR%: {atr_pct:.2f}%
• 권장 SL: {rec_sl*100:.1f}% (ATR 기반)
• SL 범위: {sl_min*100:.0f}% ~ {sl_max*100:.0f}%

⚠️ 중요: SL은 ATR의 1.5~2배로 설정하세요.
⚠️ 변동성이 높으면 SL을 넓게 설정하세요.
⚠️ SL이 너무 좁으면 정상 변동에도 손절됩니다.

{pivot_str}
{btc_str}
{pred_str}
{candle_str}
{portfolio_str}
{perf_str}

━━━━━━━━━━━━━━━━━━━━━━
📋 판단 가이드라인
━━━━━━━━━━━━━━━━━━━━━━
1. 주봉 상승 + 일봉 상승 = 적극 매수 가능
2. 주봉 상승 + 일봉 하락 = 관망 또는 소극적 매수
3. 주봉 하락 = 매수 금지, 관망 권장
4. SL은 최소 {sl_min*100:.0f}% 이상으로 설정
5. 고변동성 구간에서는 SL을 더 넓게 설정
6. 빗썸 예측차트는 보조지표로만 참고 (맹신 금지)
7. 캔들 패턴은 진입/청산 타이밍 참고용 (단독 판단 금지)

다음 JSON 형식으로 응답:
{{
  "decision": "buy" / "hold" / "sell",
  "confidence": 0.0~1.0,
  "market_condition": "strong_uptrend/weak_uptrend/sideways/high_volatility/weak_downtrend/strong_downtrend",
  "position_type": "swing",
  "holding_period": "1~3일" / "3~7일" / "1주+",
  "tp": 0.03~0.10 (소수점),
  "sl": {sl_min}~{sl_max} (ATR 기반, 최소 {sl_min}),
  "tp_price": 목표가 (숫자),
  "sl_price": 손절가 (숫자),
  "position_weight": 0.15~0.35,
  "long_term_aligned": true/false (장기추세 일치여부),
  "reason": "상세한 판단 이유",
  "risk_note": "주의사항"
}}

반드시 JSON만 응답. 설명 금지.
"""
        return prompt
    
    @classmethod
    def build_signal_prompt(
        cls,
        symbol: str,
        indicators: Dict,
        market_condition: str,
        btc_context: Optional[Dict] = None,
    ) -> str:
        """
        간단한 신호 분석용 프롬프트 생성
        
        Args:
            symbol: 심볼
            indicators: 지표 딕셔너리
            market_condition: 시장 상황
            btc_context: BTC 컨텍스트
            
        Returns:
            프롬프트 문자열
        """
        btc_str = ""
        if btc_context:
            # 🔥 v5.3.0b: _safe_float 적용
            btc_change = _safe_float(btc_context.get('change_24h', 0), 0)
            btc_str = f"BTC: {btc_context.get('trend', 'unknown')} ({btc_change:+.1f}%)"
        
        prompt = f"""
암호화폐 {symbol} 간단 분석:

[지표]
RSI: {indicators.get('rsi', 'N/A')}
EMA: {indicators.get('ema_status', 'N/A')}
ADX: {indicators.get('adx', 'N/A')}
ATR%: {indicators.get('atr_pct', 'N/A')}%
{btc_str}

시장 상황: {market_condition}

JSON으로 응답:
{{
  "signal": "buy" / "hold" / "sell",
  "strength": 0.0~1.0,
  "reason": "간단한 이유"
}}
"""
        return prompt


# =========================================================
# 편의 함수
# =========================================================

def build_prompt(
    symbol: str,
    indicators_30m: Optional[Dict] = None,
    indicators_15m: Optional[Dict] = None,
    indicators_5m: Optional[Dict] = None,
    market_condition: str = "sideways",
    tp_sl_guide: Optional[Dict] = None,
    pivot_data: Optional[Dict] = None,
    portfolio_context: Optional[Dict] = None,
    btc_context: Optional[Dict] = None,
    performance_context: Optional[Dict] = None,
    indicators_1h: Optional[Dict] = None,
    indicators_4h: Optional[Dict] = None,
    indicators_daily: Optional[Dict] = None,
    indicators_weekly: Optional[Dict] = None,
    long_term_trend: Optional[Dict] = None,
    recommended_sl: Optional[float] = None,
    bithumb_prediction: Optional[str] = None,  # v5.3.1
    candle_patterns: Optional[str] = None,     # 🆕 v5.3.2
) -> str:
    """
    프롬프트 빌드 (편의 함수, 기존 코드 호환)
    
    기존 AIDecisionEngine.build_prompt()와 동일한 시그니처
    🆕 v5.3.2: candle_patterns 파라미터 추가
    """
    return PromptBuilder.build_trading_prompt(
        symbol=symbol,
        indicators_30m=indicators_30m,
        indicators_15m=indicators_15m,
        indicators_5m=indicators_5m,
        indicators_1h=indicators_1h,
        indicators_4h=indicators_4h,
        indicators_daily=indicators_daily,
        indicators_weekly=indicators_weekly,
        market_condition=market_condition,
        long_term_trend=long_term_trend,
        recommended_sl=recommended_sl,
        pivot_data=pivot_data,
        btc_context=btc_context,
        portfolio_context=portfolio_context,
        performance_context=performance_context,
        tp_sl_guide=tp_sl_guide,
        bithumb_prediction=bithumb_prediction,  # v5.3.1
        candle_patterns=candle_patterns,        # 🆕 v5.3.2
    )
