# -*- coding: utf-8 -*-
"""
Phoenix v5.3.0 — 유틸리티 모듈

공통 기능 제공:
- cache: 통합 캐시 관리
- exceptions: 커스텀 예외 클래스
- decorators: 공통 데코레이터
- validators: 데이터 검증
- error_handler: 중앙 에러 핸들러
- logger: 로깅 설정
- timezone: 시간대 처리
- retry: 재시도 로직 (레거시)
"""

# 캐시
from bot.utils.cache import (
    CacheManager,
    cached,
    price_cache,
    ticker_cache,
    balance_cache,
    ohlcv_cache,
    indicator_cache,
    ai_cache,
    btc_context_cache,
    markets_cache,
    get_all_cache_stats,
    clear_all_caches,
)

# 예외
from bot.utils.exceptions import (
    PhoenixBaseException,
    # API
    APIException,
    RateLimitException,
    ConnectionException,
    AuthenticationException,
    InsufficientBalanceException,
    OrderFailedException,
    InvalidQuantityException,
    InvalidPriceException,
    # Data
    DataException,
    OHLCVException,
    IndicatorCalculationException,
    JSONParseException,
    ValidationException,
    # AI
    AIException,
    AIResponseParseException,
    AITimeoutException,
    AIQuotaExceededException,
    AIInvalidResponseException,
    # Position
    PositionException,
    PositionNotFound,
    PositionLimitExceeded,
    PositionWeightExceeded,
    DCALimitExceeded,
    # Risk
    RiskException,
    DailyLossLimitException,
    DrawdownLimitException,
    CircuitBreakerTriggered,
    MarketConditionException,
    # System
    SystemException,
    ConfigurationException,
    FileIOException,
    TelegramException,
    # Utils
    is_recoverable,
    get_error_code,
    exception_to_dict,
)

# 데코레이터
from bot.utils.decorators import (
    retry,
    safe_execute,
    log_execution,
    throttle,
    debounce,
    singleton,
    deprecated,
    timed,
    run_once,
    synchronized,
    async_timeout,
    robust,
)

# 검증
from bot.utils.validators import (
    DataValidator,
    JSONValidator,
    SymbolValidator,
    PriceValidator,
    TradeValidator,
    ValidationResult,
    # 편의 함수
    safe_float,
    safe_int,
    safe_string,
    safe_bool,
    safe_dict,
    safe_list,
    extract_json,
    validate_json_schema,
    normalize_symbol,
    extract_coin,
    is_valid_symbol,
    is_valid_price,
    is_valid_quantity,
)

# 에러 핸들러
from bot.utils.error_handler import (
    ErrorHandler,
    ErrorRecord,
    ErrorSeverity,
    ErrorContext,
    error_handler,
    handle_error,
    log_and_notify,
    get_error_stats,
    set_error_notify_callback,
)

# 로거
from bot.utils.logger import get_logger

# 타임존
from bot.utils.timezone import now_kst, today_kst, timestamp_kst, KST

__all__ = [
    # Cache
    "CacheManager",
    "cached",
    "price_cache",
    "ticker_cache",
    "balance_cache",
    "ohlcv_cache",
    "indicator_cache",
    "ai_cache",
    "btc_context_cache",
    "markets_cache",
    "get_all_cache_stats",
    "clear_all_caches",
    
    # Exceptions
    "PhoenixBaseException",
    "APIException",
    "RateLimitException",
    "ConnectionException",
    "AuthenticationException",
    "InsufficientBalanceException",
    "OrderFailedException",
    "InvalidQuantityException",
    "InvalidPriceException",
    "DataException",
    "OHLCVException",
    "IndicatorCalculationException",
    "JSONParseException",
    "ValidationException",
    "AIException",
    "AIResponseParseException",
    "AITimeoutException",
    "AIQuotaExceededException",
    "AIInvalidResponseException",
    "PositionException",
    "PositionNotFound",
    "PositionLimitExceeded",
    "PositionWeightExceeded",
    "DCALimitExceeded",
    "RiskException",
    "DailyLossLimitException",
    "DrawdownLimitException",
    "CircuitBreakerTriggered",
    "MarketConditionException",
    "SystemException",
    "ConfigurationException",
    "FileIOException",
    "TelegramException",
    "is_recoverable",
    "get_error_code",
    "exception_to_dict",
    
    # Decorators
    "retry",
    "safe_execute",
    "log_execution",
    "throttle",
    "debounce",
    "singleton",
    "deprecated",
    "timed",
    "run_once",
    "synchronized",
    "async_timeout",
    "robust",
    
    # Validators
    "DataValidator",
    "JSONValidator",
    "SymbolValidator",
    "PriceValidator",
    "TradeValidator",
    "ValidationResult",
    "safe_float",
    "safe_int",
    "safe_string",
    "safe_bool",
    "safe_dict",
    "safe_list",
    "extract_json",
    "validate_json_schema",
    "normalize_symbol",
    "extract_coin",
    "is_valid_symbol",
    "is_valid_price",
    "is_valid_quantity",
    
    # Error Handler
    "ErrorHandler",
    "ErrorRecord",
    "ErrorSeverity",
    "ErrorContext",
    "error_handler",
    "handle_error",
    "log_and_notify",
    "get_error_stats",
    "set_error_notify_callback",
    
    # Logger
    "get_logger",
    "setup_logger",
    
    # Timezone
    "get_kst_now",
    "to_kst",
    "KST",
]
