# -*- coding: utf-8 -*-
"""
Phoenix v5.1.0d — Retry Utilities (재시도 유틸리티)

🆕 v5.1.0d 신규:
- 지수 백오프 재시도 데코레이터
- API 클라이언트 래퍼
- 서킷브레이커 연동
"""

import time
import logging
from functools import wraps
from typing import Callable, Tuple, Type, Optional, Any

logger = logging.getLogger("Retry")


def retry_with_backoff(
    max_retries: int = 3,
    base_delay: float = 1.0,
    max_delay: float = 30.0,
    exceptions: Tuple[Type[Exception], ...] = (Exception,),
    on_retry: Optional[Callable] = None,
    on_success: Optional[Callable] = None
):
    """
    지수 백오프 재시도 데코레이터
    
    Args:
        max_retries: 최대 재시도 횟수
        base_delay: 기본 대기 시간 (초)
        max_delay: 최대 대기 시간 (초)
        exceptions: 재시도할 예외 타입들
        on_retry: 재시도 시 호출할 콜백 (circuit_breaker.record_api_failure 등)
        on_success: 성공 시 호출할 콜백 (circuit_breaker.record_api_success 등)
    
    사용 예:
        @retry_with_backoff(max_retries=3, base_delay=1.0)
        def get_price(symbol):
            return api.get_ticker(symbol)
    """
    def decorator(func: Callable) -> Callable:
        @wraps(func)
        def wrapper(*args, **kwargs) -> Any:
            last_exception = None
            
            for attempt in range(max_retries + 1):
                try:
                    result = func(*args, **kwargs)
                    
                    # 성공 콜백
                    if on_success:
                        try:
                            on_success()
                        except:
                            pass
                    
                    return result
                    
                except exceptions as e:
                    last_exception = e
                    
                    if attempt == max_retries:
                        logger.error(
                            f"[Retry] {func.__name__} 최종 실패 "
                            f"(시도: {attempt + 1}/{max_retries + 1}): {e}"
                        )
                        if on_retry:
                            try:
                                on_retry()
                            except:
                                pass
                        raise
                    
                    # 지수 백오프 계산
                    delay = min(base_delay * (2 ** attempt), max_delay)
                    
                    logger.warning(
                        f"[Retry] {func.__name__} 실패 "
                        f"(시도: {attempt + 1}/{max_retries + 1}): {e}, "
                        f"{delay:.1f}초 후 재시도"
                    )
                    
                    time.sleep(delay)
            
            raise last_exception
        
        return wrapper
    return decorator


class RetryableAPIClient:
    """
    재시도 로직이 내장된 API 클라이언트 래퍼
    
    사용 예:
        api = BithumbCcxtAPI()
        cb = CircuitBreaker()
        safe_api = RetryableAPIClient(api, cb)
        
        ticker = safe_api.fetch_ticker_safe("BTC/KRW")
    """
    
    def __init__(self, api_client, circuit_breaker=None):
        self.api = api_client
        self.cb = circuit_breaker
    
    def _on_failure(self):
        """실패 시 서킷브레이커에 기록"""
        if self.cb:
            self.cb.record_api_failure()
    
    def _on_success(self):
        """성공 시 서킷브레이커에 기록"""
        if self.cb:
            self.cb.record_api_success()
    
    def fetch_ticker_safe(self, symbol: str, max_retries: int = 3) -> Optional[dict]:
        """
        시세 조회 (재시도 적용)
        
        Args:
            symbol: 심볼 (예: "BTC/KRW")
            max_retries: 최대 재시도 횟수
            
        Returns:
            티커 정보 또는 None
        """
        last_error = None
        
        for attempt in range(max_retries + 1):
            try:
                result = self.api.fetch_ticker(symbol)
                self._on_success()
                return result
                
            except Exception as e:
                last_error = e
                
                if attempt == max_retries:
                    logger.error(f"[RetryAPI] fetch_ticker({symbol}) 최종 실패: {e}")
                    self._on_failure()
                    return None
                
                delay = min(1.0 * (2 ** attempt), 10.0)
                logger.warning(f"[RetryAPI] fetch_ticker({symbol}) 실패, {delay:.1f}초 후 재시도")
                time.sleep(delay)
        
        return None
    
    def fetch_balance_safe(self, max_retries: int = 3) -> Optional[dict]:
        """
        잔고 조회 (재시도 적용)
        
        Returns:
            잔고 정보 또는 None
        """
        last_error = None
        
        for attempt in range(max_retries + 1):
            try:
                result = self.api.fetch_balance()
                self._on_success()
                return result
                
            except Exception as e:
                last_error = e
                
                if attempt == max_retries:
                    logger.error(f"[RetryAPI] fetch_balance 최종 실패: {e}")
                    self._on_failure()
                    return None
                
                delay = min(1.0 * (2 ** attempt), 10.0)
                logger.warning(f"[RetryAPI] fetch_balance 실패, {delay:.1f}초 후 재시도")
                time.sleep(delay)
        
        return None
    
    def create_order_safe(
        self, 
        symbol: str, 
        side: str, 
        amount: float,
        price: float = None,
        max_retries: int = 2
    ) -> Optional[dict]:
        """
        주문 실행 (재시도 적용 - 더 보수적)
        
        Args:
            symbol: 심볼
            side: "buy" 또는 "sell"
            amount: 수량
            price: 가격 (시장가면 None)
            max_retries: 최대 재시도 횟수 (주문은 더 보수적)
            
        Returns:
            주문 결과 또는 None
        """
        last_error = None
        
        for attempt in range(max_retries + 1):
            try:
                if side == "buy":
                    if price:
                        result = self.api.create_limit_buy(symbol, amount, price)
                    else:
                        result = self.api.create_limit_buy(symbol, amount)
                else:
                    if price:
                        result = self.api.create_limit_sell(symbol, amount, price)
                    else:
                        result = self.api.create_limit_sell(symbol, amount)
                
                self._on_success()
                return result
                
            except Exception as e:
                last_error = e
                
                if attempt == max_retries:
                    logger.error(f"[RetryAPI] create_order({symbol}, {side}) 최종 실패: {e}")
                    self._on_failure()
                    return None
                
                # 주문 재시도는 짧은 딜레이
                delay = min(0.5 * (2 ** attempt), 5.0)
                logger.warning(f"[RetryAPI] create_order 실패, {delay:.1f}초 후 재시도")
                time.sleep(delay)
        
        return None
    
    def get_ohlcv_safe(
        self, 
        symbol: str, 
        timeframe: str = "5m",
        limit: int = 100,
        max_retries: int = 3
    ) -> Optional[Any]:
        """
        OHLCV 데이터 조회 (재시도 적용)
        
        Returns:
            OHLCV 데이터프레임 또는 None
        """
        last_error = None
        
        for attempt in range(max_retries + 1):
            try:
                result = self.api.get_ohlcv(symbol, timeframe, limit)
                self._on_success()
                return result
                
            except Exception as e:
                last_error = e
                
                if attempt == max_retries:
                    logger.error(f"[RetryAPI] get_ohlcv({symbol}) 최종 실패: {e}")
                    self._on_failure()
                    return None
                
                delay = min(1.0 * (2 ** attempt), 10.0)
                logger.warning(f"[RetryAPI] get_ohlcv({symbol}) 실패, {delay:.1f}초 후 재시도")
                time.sleep(delay)
        
        return None


def safe_api_call(func: Callable, *args, max_retries: int = 3, **kwargs) -> Optional[Any]:
    """
    범용 안전한 API 호출 함수
    
    사용 예:
        result = safe_api_call(api.fetch_ticker, "BTC/KRW", max_retries=3)
    """
    last_error = None
    
    for attempt in range(max_retries + 1):
        try:
            return func(*args, **kwargs)
        except Exception as e:
            last_error = e
            
            if attempt == max_retries:
                logger.error(f"[SafeCall] {func.__name__} 최종 실패: {e}")
                return None
            
            delay = min(1.0 * (2 ** attempt), 10.0)
            logger.warning(f"[SafeCall] {func.__name__} 실패, {delay:.1f}초 후 재시도")
            time.sleep(delay)
    
    return None
