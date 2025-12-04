# Phoenix v5.3.0 — Phase 3 AI 모듈 마이그레이션 가이드

> **작성일:** 2025-12-04
> **대상:** ai_decision.py (978줄) → AI 모듈 (6개 파일, 2,101줄)

---

## 📊 Phase 3 완료 요약

### 생성된 파일

| 파일 | 줄 수 | 역할 |
|:---|:---:|:---|
| `bot/core/ai/__init__.py` | 142 | 모듈 진입점, 호환성 함수 |
| `bot/core/ai/response_parser.py` | 434 | AI 응답 JSON 추출/검증/정규화 |
| `bot/core/ai/prompt_builder.py` | 382 | GPT 프롬프트 생성, TP/SL 가이드 |
| `bot/core/ai/long_term_analyzer.py` | 300 | 장기 추세 분석, 동적 SL 계산 |
| `bot/core/ai/sl_reason_generator.py` | 320 | SL 승인 근거 생성 |
| `bot/core/ai/decision_engine.py` | 523 | 핵심 AI 판단 로직 |
| **합계** | **2,101** | |

### 원본 vs 리팩토링

| 구분 | 원본 | 리팩토링 | 비고 |
|:---|:---:|:---:|:---|
| 파일 수 | 1 | 6 | 단일 책임 원칙 |
| 총 줄 수 | 978 | 2,101 | 문서화, 타입힌트 추가 |
| 평균 파일 크기 | 978줄 | 350줄 | 가독성 향상 |
| 테스트 용이성 | 낮음 | 높음 | 모듈 분리 |

---

## 🔄 마이그레이션 방법

### 방법 1: 점진적 마이그레이션 (권장)

기존 `ai_decision.py`를 유지하면서 새 모듈을 추가합니다.

```python
# 기존 코드 (유지)
from bot.core.ai_decision import AIDecisionEngine

# 새 코드에서는 새 모듈 사용
from bot.core.ai import AIDecisionEngine  # 동일한 인터페이스
```

### 방법 2: 전체 교체

`ai_decision.py`를 완전히 새 모듈로 대체합니다.

```bash
# 1. 백업
cp bot/core/ai_decision.py bot/core/ai_decision.py.bak

# 2. ai_decision.py를 래퍼로 변경
cat > bot/core/ai_decision.py << 'EOF'
# -*- coding: utf-8 -*-
"""
Phoenix v5.3.0 — AI Decision Wrapper

⚠️ Deprecated: bot.core.ai 모듈 사용 권장

이 파일은 하위 호환성을 위한 래퍼입니다.
"""

from bot.core.ai import (
    AIDecisionEngine,
    AIResponseValidator,
    analyze_long_term_trend,
    calculate_dynamic_sl,
    generate_sl_rationale,
    get_btc_market_mode,
)

__all__ = [
    "AIDecisionEngine",
    "AIResponseValidator",
]
EOF
```

---

## 📝 코드 변경 매핑

### 임포트 변경

```python
# ❌ 이전
from bot.core.ai_decision import AIDecisionEngine, AIResponseValidator

# ✅ 이후
from bot.core.ai import AIDecisionEngine, AIResponseValidator
```

### 개별 함수 임포트

```python
# ❌ 이전 (AIDecisionEngine 클래스 메서드)
result = AIDecisionEngine.analyze_long_term_trend(ind_daily, ind_weekly)
result = AIDecisionEngine.calculate_dynamic_sl(atr_pct, condition, trend)
result = AIDecisionEngine.generate_sl_rationale(symbol, pos, price, df30)

# ✅ 이후 (독립 함수로도 사용 가능)
from bot.core.ai import (
    analyze_long_term_trend,
    calculate_dynamic_sl,
    generate_sl_rationale,
)

result = analyze_long_term_trend(ind_daily, ind_weekly)
result = calculate_dynamic_sl(atr_pct, condition, trend)
result = generate_sl_rationale(symbol, pos, price, df30)
```

### 지표 계산 (Phase 2 모듈 활용)

```python
# ❌ 이전 (ai_decision.py 내부 메서드)
indicators = AIDecisionEngine.calculate_indicators(df)
condition = AIDecisionEngine.detect_market_condition(indicators)

# ✅ 이후 (Phase 2 indicators 모듈 사용)
from bot.core.indicators import calculate_indicators, detect_market_condition

indicators = calculate_indicators(df, symbol)
condition = detect_market_condition(indicators)
```

---

## 📁 파일별 상세

### 1. `response_parser.py`

**역할:** AI 응답의 JSON 추출, 검증, 정규화

```python
from bot.core.ai import parse_ai_response, extract_json_from_ai

# JSON 추출
data = extract_json_from_ai(raw_text)

# 전체 파싱 (추출 + 검증 + 정규화)
result = parse_ai_response(raw_text, market_condition_hint="sideways")

# 호환성 클래스 (Deprecated)
from bot.core.ai import AIResponseValidator
result = AIResponseValidator.validate_and_normalize(data)
```

### 2. `prompt_builder.py`

**역할:** GPT-4o-mini용 프롬프트 생성

```python
from bot.core.ai import build_prompt, get_tp_sl_guide, PromptBuilder

# TP/SL 가이드
guide = get_tp_sl_guide("strong_uptrend", atr_pct=3.0)

# 프롬프트 생성
prompt = build_prompt(
    symbol="SOL/KRW",
    indicators_30m=ind_30m,
    indicators_15m=ind_15m,
    indicators_5m=ind_5m,
    market_condition="weak_uptrend",
    long_term_trend=lt_trend,
    # ... 기타 파라미터
)
```

### 3. `long_term_analyzer.py`

**역할:** 일봉/주봉 장기 추세 분석, ATR 기반 동적 SL

```python
from bot.core.ai import (
    analyze_long_term_trend,
    calculate_dynamic_sl,
    should_avoid_entry,
    is_trend_aligned,
    LongTermTrend,
)

# 장기 추세 분석
trend = analyze_long_term_trend(ind_daily, ind_weekly)
# → {"trend": "bull", "recommendation": "매수", "weekly_momentum": "상승", ...}

# 동적 SL 계산
sl = calculate_dynamic_sl(atr_pct=3.5, market_condition="weak_uptrend", long_term_trend=trend)
# → 0.045 (4.5%)

# 진입 회피 판단
should_avoid, reason = should_avoid_entry(trend)
# → (True, "주봉 하락 추세 (매도)")
```

### 4. `sl_reason_generator.py`

**역할:** 손절 승인 요청 시 전략적 근거 생성

```python
from bot.core.ai import generate_sl_rationale, SLRationale

rationale = generate_sl_rationale(
    symbol="SOL/KRW",
    pos={"entry_price": 100000},
    current_price=97000,
    df30=df_30m,
)
# → {
#     "recommendation": "손절",
#     "confidence": 0.8,
#     "rationale": "손실 -3.0% (임계치 초과) | RSI 35 (참고) | EMA 하락 추세",
#     "support_level": 95000,
#     "recovery_chance": 0.3,
#     "risk_if_hold": "손실 확대 위험 높음",
# }
```

### 5. `decision_engine.py`

**역할:** 핵심 AI 판단 로직 (GPT 호출)

```python
from bot.core.ai import AIDecisionEngine, analyze_coin

# 클래스 메서드
result = AIDecisionEngine.analyze(
    symbol="SOL/KRW",
    df30=df_30m,
    df15=df_15m,
    df5=df_5m,
    btc_context=btc_ctx,
    df_daily=df_1d,
    df_weekly=df_1w,
)

# 편의 함수
result = analyze_coin("SOL/KRW", df_30m, df_15m, df_5m)

# 결과
# → {
#     "decision": "buy",
#     "confidence": 0.75,
#     "tp": 0.05,
#     "sl": 0.035,
#     "long_term_trend": {...},
#     "btc_mode": {...},
#     ...
# }
```

---

## ⚠️ 주의사항

### 1. Phase 2 의존성

AI 모듈은 Phase 2의 `indicators` 모듈을 사용합니다.

```python
# decision_engine.py 내부
from bot.core.indicators import calculate_indicators, detect_market_condition
```

반드시 Phase 1, 2를 먼저 적용하세요.

### 2. Config 의존성

다음 설정값을 사용합니다:

```python
# config.py에 필요한 설정
OPENAI_API_KEY = "..."
AI_SL_MIN = 0.03
AI_SL_MAX = 0.07
ATR_SL_MULTIPLIER_LOW = 2.0
ATR_SL_MULTIPLIER_MEDIUM = 1.8
ATR_SL_MULTIPLIER_HIGH = 1.5
ATR_SL_MULTIPLIER_EXTREME = 1.2
PIVOT_ENABLED = True
PIVOT_TYPE = "standard"
```

### 3. 호환성 유지

기존 `AIResponseValidator` 클래스는 호환성을 위해 유지됩니다:

```python
# 이전 코드도 여전히 작동
from bot.core.ai import AIResponseValidator
result = AIResponseValidator.validate_and_normalize(data)
```

---

## 📦 다운로드

- **Phase 3만:** `phoenix_v5_3_phase3_ai.tar.gz`
- **Phase 1+2+3:** `phoenix_v5_3_0_phase1_2_3.tar.gz`

---

## 🔍 다음 단계

### Phase 4: API 최적화 (예정)

- `bithumb_ccxt_api.py` 리팩토링
- `price_feed.py` 캐시 통합
- Rate Limiter 중앙화

### Phase 5: 통합 테스트 (예정)

- 단위 테스트 작성
- VPS 배포 및 검증

---

*작성: Claude (AI Assistant)*
*버전: v5.3.0 Phase 3 완료*
