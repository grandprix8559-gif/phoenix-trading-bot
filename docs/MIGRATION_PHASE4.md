# Phoenix v5.3.0 — Phase 4 마이그레이션 가이드

> **작성일:** 2025-12-04
> **Phase:** 4 - API 최적화
> **대상:** bithumb_ccxt_api.py, price_feed.py

---

## 1. 개요

Phase 4에서는 API 관련 코드를 모듈화하여 다음을 달성합니다:

| 목표 | 설명 |
|:---|:---|
| **코드 분리** | Rate Limiter, 정밀도, 캐시를 독립 모듈로 |
| **재사용성** | 다른 모듈에서 쉽게 임포트 가능 |
| **캐시 통합** | Phase 1 캐시 매니저와 연동 |
| **테스트 용이** | 개별 기능 단위 테스트 가능 |

---

## 2. 새로운 파일 구조

```
bot/api/
├── __init__.py           # 모듈 진입점 (익스포트)
├── bithumb_ccxt_api.py   # CCXT 래퍼 (기존, 수정 예정)
├── rate_limiter.py       # 🆕 Rate Limit 관리
├── precision.py          # 🆕 가격/수량 정밀도
└── api_cache.py          # 🆕 통합 API 캐시
```

---

## 3. 모듈별 설명

### 3.1 rate_limiter.py

Rate Limit 관리를 담당합니다.

**주요 클래스/함수:**
```python
# 클래스
RateLimiter              # Rate Limit 관리자
RateLimitStats           # 통계 데이터

# 함수
retry_with_backoff()     # 재시도 데코레이터
check_rate_limit()       # Rate Limit 체크 (편의 함수)
rate_limited()           # Rate Limit 적용 데코레이터

# 전역 인스턴스
bithumb_rate_limiter     # 빗썸용 Rate Limiter
```

**사용 예시:**
```python
from bot.api import check_rate_limit, retry_with_backoff

# 호출 전 Rate Limit 체크
check_rate_limit()

# 재시도 데코레이터
@retry_with_backoff(max_retries=3, base_delay=1.0)
def api_call():
    return exchange.fetch_ticker(symbol)
```

### 3.2 precision.py

가격 및 수량 정밀도 처리를 담당합니다.

**주요 함수:**
```python
# 틱 사이즈 (가격 단위)
get_tick_size(price)               # 틱 사이즈 조회
round_to_tick(price, direction)    # 틱 사이즈에 맞게 반올림

# 수량 정밀도
get_qty_precision(symbol, price)   # 수량 정밀도 조회
round_qty(qty, symbol, direction)  # 수량 정밀도 적용

# 심볼 유틸리티
convert_symbol(sym)                # 심볼 정규화 (SOL → SOL/KRW)
extract_coin(symbol)               # 코인 추출 (SOL/KRW → SOL)

# 주문 준비
prepare_buy_order(...)             # 매수 주문 파라미터 준비
prepare_sell_order(...)            # 매도 주문 파라미터 준비
```

**사용 예시:**
```python
from bot.api import round_qty, round_to_tick, convert_symbol

# 가격 정밀도
price = round_to_tick(97500.7, direction="up")  # → 97600

# 수량 정밀도
qty = round_qty(1.23456789, "SOL/KRW", direction="down")  # → 1.2345

# 심볼 정규화
symbol = convert_symbol("sol")  # → "SOL/KRW"
```

### 3.3 api_cache.py

API 응답 캐싱을 Phase 1 캐시 모듈과 통합합니다.

**주요 클래스/함수:**
```python
# 클래스
APICacheManager          # 통합 캐시 관리자
APICacheStats            # 캐시 통계

# 편의 함수
get_cached_balance()     # 잔고 캐시 조회
set_cached_balance()     # 잔고 캐시 저장
invalidate_balance_cache()  # 잔고 캐시 무효화
get_cached_ticker()      # 티커 캐시 조회
set_cached_ticker()      # 티커 캐시 저장
get_cache_stats()        # 캐시 통계 조회
```

**사용 예시:**
```python
from bot.api import (
    get_cached_balance, 
    set_cached_balance,
    invalidate_balance_cache,
    get_cache_stats
)

# 캐시된 잔고 조회
balance = get_cached_balance()
if balance is None:
    balance = exchange.fetch_balance()
    set_cached_balance(balance)

# 주문 후 캐시 무효화
invalidate_balance_cache()

# 통계 확인
stats = get_cache_stats()
print(f"캐시 적중률: {stats['hit_rate']}%")
```

---

## 4. 임포트 변경

### 4.1 기존 코드

```python
# ❌ 이전 (bithumb_ccxt_api.py에서 직접 임포트)
from bot.api.bithumb_ccxt_api import (
    RateLimiter,
    retry_with_backoff,
    get_tick_size,
    round_to_tick,
    get_qty_precision,
    round_qty,
    convert_symbol,
)
```

### 4.2 새로운 코드

```python
# ✅ 이후 (통합 모듈에서 임포트)
from bot.api import (
    # Rate Limiter
    RateLimiter,
    retry_with_backoff,
    check_rate_limit,
    
    # 정밀도
    get_tick_size,
    round_to_tick,
    get_qty_precision,
    round_qty,
    convert_symbol,
    
    # 캐시
    get_cached_balance,
    invalidate_balance_cache,
    get_cache_stats,
)
```

---

## 5. 영향받는 파일

### 5.1 직접 수정 필요

| 파일 | 변경 사항 |
|:---|:---|
| `bithumb_ccxt_api.py` | 새 모듈 활용, 중복 코드 제거 |
| `execution_engine.py` | 임포트 경로 변경 |
| `signal_bot.py` | 캐시 함수 사용 |

### 5.2 선택적 수정

| 파일 | 변경 사항 |
|:---|:---|
| `price_feed.py` | Phase 1 캐시 활용 |
| `position_sync.py` | 정밀도 함수 활용 |

---

## 6. bithumb_ccxt_api.py 수정 방법

### 방법 1: 점진적 마이그레이션 (권장)

기존 함수를 새 모듈로 위임합니다:

```python
# bithumb_ccxt_api.py 상단에 추가
from bot.api.rate_limiter import RateLimiter, retry_with_backoff
from bot.api.precision import (
    get_tick_size, round_to_tick, get_qty_precision, round_qty, convert_symbol
)
from bot.api.api_cache import (
    get_cached_balance, set_cached_balance, invalidate_balance_cache,
    get_cached_ticker, set_cached_ticker
)

# 기존 RateLimiter 클래스 정의 삭제
# 기존 get_tick_size(), round_to_tick() 등 삭제
```

### 방법 2: 완전 대체

새 모듈을 직접 사용하고 기존 코드 호환성 유지:

```python
# bithumb_ccxt_api.py
from bot.api import rate_limiter, precision, api_cache

class BithumbAPI:
    def __init__(self):
        # 기존 rate_limiter 대신 새 모듈 사용
        self.rate_limiter = rate_limiter.bithumb_rate_limiter
        
    def _check_rate_limit(self):
        rate_limiter.check_rate_limit()
```

---

## 7. 캐시 연동

### Phase 1 캐시 모듈과 연동

`api_cache.py`는 Phase 1의 `bot/utils/cache.py`를 활용합니다:

```python
# api_cache.py
from bot.utils.cache import (
    balance_cache,    # 잔고 캐시 (10초 TTL)
    ticker_cache,     # 티커 캐시 (5초 TTL)
    ohlcv_cache,      # OHLCV 캐시 (30초 TTL)
    markets_cache,    # 마켓 정보 캐시 (1시간 TTL)
)
```

---

## 8. 테스트 방법

### 8.1 Rate Limiter 테스트

```python
from bot.api import check_rate_limit, get_bithumb_rate_limiter

limiter = get_bithumb_rate_limiter()
print(limiter.get_stats())

# 호출 테스트
for i in range(10):
    check_rate_limit()
    print(f"Remaining: {limiter.get_remaining()}")
```

### 8.2 정밀도 테스트

```python
from bot.api import round_qty, round_to_tick, get_qty_precision

# 가격 테스트
assert round_to_tick(1234567, "up") == 1235000
assert round_to_tick(97.5, "down") == 97.5

# 수량 테스트
assert round_qty(1.23456789, "SOL/KRW", "down") == 1.2345
assert round_qty(0.001, "BONK/KRW", "down") == 0  # 초저가 코인
```

### 8.3 캐시 테스트

```python
from bot.api import (
    get_cached_balance, set_cached_balance, get_cache_stats
)

# 캐시 미스
assert get_cached_balance() is None

# 캐시 설정
set_cached_balance({"KRW": {"free": 1000000}})

# 캐시 히트
assert get_cached_balance() is not None

# 통계 확인
stats = get_cache_stats()
print(f"적중률: {stats['hit_rate']}%")
```

---

## 9. 주의사항

### 9.1 순환 참조 방지

`api/__init__.py`에서 `bithumb_ccxt_api.py`는 지연 임포트합니다:

```python
def get_api():
    from bot.api.bithumb_ccxt_api import get_api as _get_api
    return _get_api()
```

### 9.2 캐시 TTL 설정

| 캐시 | TTL | 설명 |
|:---|:---|:---|
| 잔고 | 10초 | 거래 후 무효화 필요 |
| 티커 | 5초 | 실시간 가격 |
| OHLCV | 30초 | 기술적 분석용 |
| 마켓 | 1시간 | 정밀도 정보 |

---

## 10. 중복 코드 제거 매핑

| 기존 위치 | 새 위치 | 줄 수 |
|:---|:---|:---|
| bithumb_ccxt_api.py:RateLimiter | api/rate_limiter.py | ~80줄 제거 |
| bithumb_ccxt_api.py:get_tick_size | api/precision.py | ~50줄 제거 |
| bithumb_ccxt_api.py:get_qty_precision | api/precision.py | ~70줄 제거 |
| bithumb_ccxt_api.py:round_qty | api/precision.py | ~20줄 제거 |
| bithumb_ccxt_api.py:retry_with_backoff | api/rate_limiter.py | ~40줄 제거 |
| **총계** | | **~260줄 제거 가능** |

---

## 11. 통계

### Phase 4 새 파일

| 파일 | 줄 수 | 역할 |
|:---|:---|:---|
| rate_limiter.py | 245줄 | Rate Limit 관리 |
| precision.py | 342줄 | 가격/수량 정밀도 |
| api_cache.py | 293줄 | 통합 API 캐시 |
| __init__.py | 65줄 | 모듈 진입점 |
| **총계** | **945줄** | |

### 전체 Phase 1~4

| Phase | 파일 수 | 줄 수 |
|:---|:---|:---|
| Phase 1 (기초 인프라) | 6개 | ~3,479줄 |
| Phase 2 (지표 통합) | 4개 | ~1,688줄 |
| Phase 3 (AI 모듈) | 6개 | ~2,101줄 |
| Phase 4 (API 최적화) | 4개 | ~945줄 |
| **전체** | **20개** | **~8,213줄** |

---

*작성자: Claude (AI Assistant)*  
*버전: v5.3.0 Phase 4*
