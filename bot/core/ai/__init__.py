# -*- coding: utf-8 -*-
"""
Phoenix v5.3.0 — AI 모듈

GPT-4o-mini 기반 트레이딩 판단 시스템입니다.

🔥 v5.3.0 구조:
- decision_engine.py: 핵심 AI 판단 로직
- prompt_builder.py: GPT 프롬프트 생성
- response_parser.py: AI 응답 파싱/검증
- long_term_analyzer.py: 장기 추세 분석
- sl_reason_generator.py: SL 근거 생성

사용 예시:
    # 기본 분석
    from bot.core.ai import AIDecisionEngine
    result = AIDecisionEngine.analyze(symbol, df30, df15, df5)
    
    # 편의 함수
    from bot.core.ai import analyze_coin, get_ai_decision
    result = analyze_coin("SOL/KRW", df30, df15, df5)
    
    # 개별 모듈
    from bot.core.ai import parse_ai_response, build_prompt
    from bot.core.ai import analyze_long_term_trend, generate_sl_rationale
"""

# 핵심 클래스
from bot.core.ai.decision_engine import (
    AIDecisionEngine,
    BTCMarketMode,
    BTC_MARKET_MODES,
    get_btc_market_mode,
    analyze_coin,
    get_ai_decision,
)

# 응답 파서
from bot.core.ai.response_parser import (
    AIResponseParser,
    AIResponseDefaults,
    AIResponseLimits,
    AIResponseValidator,  # 호환성
    VALID_DECISIONS,
    VALID_POSITION_TYPES,
    VALID_MARKET_CONDITIONS,
    get_parser,
    parse_ai_response,
    extract_json_from_ai,
    get_ai_defaults,
)

# 프롬프트 빌더
from bot.core.ai.prompt_builder import (
    PromptBuilder,
    TPSLGuide,
    get_tp_sl_guide,
    build_prompt,
)

# 장기 추세 분석
from bot.core.ai.long_term_analyzer import (
    LongTermAnalyzer,
    LongTermTrend,
    analyze_long_term_trend,
    calculate_dynamic_sl,
    should_avoid_entry,
    is_trend_aligned,
)

# SL 근거 생성
from bot.core.ai.sl_reason_generator import (
    SLReasonGenerator,
    SLRationale,
    generate_sl_rationale,
)


# =========================================================
# 모듈 정보
# =========================================================

__all__ = [
    # 핵심 클래스
    "AIDecisionEngine",
    "BTCMarketMode",
    "BTC_MARKET_MODES",
    
    # 응답 파서
    "AIResponseParser",
    "AIResponseDefaults",
    "AIResponseLimits",
    "AIResponseValidator",  # 호환성
    "VALID_DECISIONS",
    "VALID_POSITION_TYPES",
    "VALID_MARKET_CONDITIONS",
    
    # 프롬프트 빌더
    "PromptBuilder",
    "TPSLGuide",
    
    # 장기 추세 분석
    "LongTermAnalyzer",
    "LongTermTrend",
    
    # SL 근거 생성
    "SLReasonGenerator",
    "SLRationale",
    
    # 편의 함수
    "get_btc_market_mode",
    "analyze_coin",
    "get_ai_decision",
    "get_parser",
    "parse_ai_response",
    "extract_json_from_ai",
    "get_ai_defaults",
    "get_tp_sl_guide",
    "build_prompt",
    "analyze_long_term_trend",
    "calculate_dynamic_sl",
    "should_avoid_entry",
    "is_trend_aligned",
    "generate_sl_rationale",
]

__version__ = "5.3.0"
__author__ = "Phoenix Trading Bot"


# =========================================================
# 호환성 지원 함수
# =========================================================

def get_default_response() -> dict:
    """기본 응답 반환 (호환성)"""
    return get_ai_defaults()


def validate_ai_response(raw_data: dict, market_condition_hint: str = "sideways") -> dict:
    """AI 응답 검증 (호환성)"""
    return get_parser().validate_and_normalize(raw_data, market_condition_hint)
