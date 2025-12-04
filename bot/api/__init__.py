# -*- coding: utf-8 -*-
"""
Phoenix v5.3.0 — API 모듈

빗썸 거래소 API 연동을 담당합니다.

🔥 v5.3.0 구조:
- bithumb_ccxt_api.py: CCXT 래퍼 (핵심)
- rate_limiter.py: Rate Limit 관리
- precision.py: 가격/수량 정밀도
- api_cache.py: 통합 API 캐시

사용 예시:
    from bot.api import get_api, check_rate_limit
    from bot.api import round_qty, round_to_tick
"""

# Rate Limiter
from bot.api.rate_limiter import (
    RateLimiter,
    retry_with_backoff,
    bithumb_rate_limiter,
    get_bithumb_rate_limiter,
    check_rate_limit,
    rate_limited,
)

# 정밀도
from bot.api.precision import (
    get_tick_size,
    round_to_tick,
    format_price,
    get_qty_precision,
    round_qty,
    format_qty,
    set_precision_fetcher,
    convert_symbol,
    extract_coin,
    prepare_buy_order,
    prepare_sell_order,
)

# API 캐시
from bot.api.api_cache import (
    APICacheManager,
    get_api_cache,
    get_cached_balance,
    set_cached_balance,
    invalidate_balance_cache,
    get_cached_ticker,
    set_cached_ticker,
    get_cache_stats,
    clear_all_api_cache,
)


def get_api():
    """BithumbAPI 인스턴스 반환"""
    from bot.api.bithumb_ccxt_api import get_api as _get_api
    return _get_api()


__version__ = "5.3.0"
__all__ = [
    "get_api",
    "RateLimiter", "retry_with_backoff", "check_rate_limit", "rate_limited",
    "get_tick_size", "round_to_tick", "get_qty_precision", "round_qty",
    "convert_symbol", "extract_coin", "set_precision_fetcher",
    "APICacheManager", "get_api_cache", "get_cache_stats",
]
