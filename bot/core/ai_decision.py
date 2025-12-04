# -*- coding: utf-8 -*-
"""
Phoenix v5.3.0 — AI Decision 호환 래퍼

기존 ai_decision.py 임포트 호환성 유지
실제 로직은 bot.core.ai.decision_engine 사용

🔥 v5.3.0 변경사항:
- 786줄 → 60줄 (래퍼 패턴)
- float 포맷팅 에러 수정됨
- Phase 2 indicators 모듈 사용
- 모듈화된 AI 서브모듈 사용

사용법 (기존과 동일):
    from bot.core.ai_decision import AIDecisionEngine
    
    result = AIDecisionEngine.analyze(symbol, df30, df15, df5, ...)
    btc_mode = AIDecisionEngine.get_btc_market_mode(btc_context)
    btc_ctx = AIDecisionEngine.get_btc_context(btc_df30)
"""

# decision_engine에서 모든 것을 임포트
from bot.core.ai.decision_engine import (
    # 메인 클래스
    AIDecisionEngine,
    
    # BTC 관련 함수
    get_btc_market_mode,
    BTCMarketMode,
    BTC_MARKET_MODES,
    
    # 헬퍼 함수
    _safe_float,
    
    # 편의 함수
    analyze_coin,
    get_ai_decision,
)

# 추가 편의 함수: get_btc_context를 모듈 레벨로 노출
def get_btc_context(btc_df30):
    """
    BTC 컨텍스트 생성 (편의 함수)
    
    Args:
        btc_df30: BTC 30분봉 DataFrame
        
    Returns:
        BTC 컨텍스트 딕셔너리
    """
    return AIDecisionEngine.get_btc_context(btc_df30)


# 모듈 공개 API
__all__ = [
    # 메인 클래스
    "AIDecisionEngine",
    
    # BTC 관련
    "get_btc_market_mode",
    "get_btc_context",
    "BTCMarketMode",
    "BTC_MARKET_MODES",
    
    # 편의 함수
    "analyze_coin",
    "get_ai_decision",
]
