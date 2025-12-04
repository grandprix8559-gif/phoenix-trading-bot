# -*- coding: utf-8 -*-
"""
Phoenix v5.3.0 — API 캐시 관리자

API 호출 최적화 및 캐싱

🔥 v5.3.0:
- Rate Limiter (분당 500회 제한)
- 용도별 캐시 (ticker, balance, ohlcv, order)
- API 호출 통계
- 스마트 캐싱 (TTL 자동 조정)
"""

import time
import threading
from typing import Dict, Optional, List, Any, Callable
from dataclasses import dataclass, field
from collections import deque

from bot.utils.logger import get_logger
from bot.utils.cache import CacheManager

logger = get_logger("APICache")


# =========================================================
# API 호출 통계
# =========================================================

@dataclass
class APICallStats:
    """API 호출 통계"""
    total_calls: int = 0
    cache_hits: int = 0
    cache_misses: int = 0
    failed_calls: int = 0
    saved_calls: int = 0
    
    @property
    def hit_rate(self) -> float:
        """캐시 히트율"""
        total = self.cache_hits + self.cache_misses
        return (self.cache_hits / total * 100) if total > 0 else 0
    
    def reset(self):
        """통계 초기화"""
        self.total_calls = 0
        self.cache_hits = 0
        self.cache_misses = 0
        self.failed_calls = 0
        self.saved_calls = 0


# =========================================================
# Rate Limiter
# =========================================================

class APIRateLimiter:
    """
    API Rate Limiter
    
    빗썸 API 제한: 분당 500회
    """
    
    def __init__(self, max_calls: int = 500, window_sec: int = 60):
        """
        Args:
            max_calls: 윈도우 내 최대 호출 수
            window_sec: 윈도우 크기 (초)
        """
        self.max_calls = max_calls
        self.window_sec = window_sec
        self.calls: deque = deque()
        self.lock = threading.Lock()
    
    def acquire(self) -> bool:
        """
        호출 가능 여부 확인 및 기록
        
        Returns:
            True: 호출 가능, False: Rate limit 초과
        """
        with self.lock:
            now = time.time()
            
            # 윈도우 밖의 호출 제거
            while self.calls and self.calls[0] < now - self.window_sec:
                self.calls.popleft()
            
            if len(self.calls) >= self.max_calls:
                return False
            
            self.calls.append(now)
            return True
    
    def wait_if_needed(self) -> float:
        """
        필요시 대기하고 대기 시간 반환
        
        Returns:
            대기 시간 (초), 대기 불필요 시 0
        """
        with self.lock:
            now = time.time()
            
            # 윈도우 밖의 호출 제거
            while self.calls and self.calls[0] < now - self.window_sec:
                self.calls.popleft()
            
            if len(self.calls) < self.max_calls:
                self.calls.append(now)
                return 0
            
            # 가장 오래된 호출이 윈도우를 벗어날 때까지 대기
            wait_time = self.calls[0] + self.window_sec - now + 0.1
            
            if wait_time > 0:
                logger.debug(f"[RateLimit] 대기 {wait_time:.1f}초...")
                time.sleep(wait_time)
            
            self.calls.append(time.time())
            return wait_time
    
    def remaining(self) -> int:
        """남은 호출 가능 횟수"""
        with self.lock:
            now = time.time()
            
            # 윈도우 밖의 호출 제거
            while self.calls and self.calls[0] < now - self.window_sec:
                self.calls.popleft()
            
            return max(0, self.max_calls - len(self.calls))
    
    def reset_time(self) -> float:
        """Rate limit 리셋까지 남은 시간 (초)"""
        with self.lock:
            if not self.calls:
                return 0
            
            now = time.time()
            oldest = self.calls[0]
            return max(0, oldest + self.window_sec - now)


# =========================================================
# 스마트 API 캐시
# =========================================================

class SmartAPICache:
    """
    스마트 API 캐시
    
    용도별 최적화된 TTL로 API 호출을 캐싱합니다.
    """
    
    # TTL 상수 (초)
    TICKER_TTL = 5
    BALANCE_TTL = 10
    OHLCV_TTL = 30
    ORDER_TTL = 60
    
    def __init__(self):
        self.stats = APICallStats()
        self.rate_limiter = APIRateLimiter()
        
        # 용도별 캐시 (TTL 최적화)
        self.ticker_cache = CacheManager(default_ttl=self.TICKER_TTL)     # 티커: 5초
        self.balance_cache = CacheManager(default_ttl=self.BALANCE_TTL)   # 잔고: 10초
        self.ohlcv_cache = CacheManager(default_ttl=self.OHLCV_TTL)       # OHLCV: 30초
        self.order_cache = CacheManager(default_ttl=self.ORDER_TTL)       # 주문내역: 60초
        
        logger.info("[APICache v5.3.0] 초기화 완료 (Rate limit: 500/min)")
    
    def get_ticker(self, symbol: str, fetcher: Callable[[str], Dict]) -> Optional[Dict]:
        """
        티커 조회 (캐시)
        
        Args:
            symbol: 심볼 (예: SOL/KRW)
            fetcher: 실제 API 호출 함수
            
        Returns:
            티커 데이터 또는 None
        """
        # 캐시 확인
        cached = self.ticker_cache.get(symbol)
        if cached is not None:
            self.stats.cache_hits += 1
            self.stats.saved_calls += 1
            return cached
        
        self.stats.cache_misses += 1
        
        # Rate limit 체크
        self.rate_limiter.wait_if_needed()
        
        try:
            self.stats.total_calls += 1
            result = fetcher(symbol)
            if result:
                self.ticker_cache.set(symbol, result)
            return result
        except Exception as e:
            self.stats.failed_calls += 1
            logger.error(f"[APICache] 티커 조회 실패 {symbol}: {e}")
            raise
    
    def get_balance(self, fetcher: Callable[[], Dict], force: bool = False) -> Optional[Dict]:
        """
        잔고 조회 (캐시)
        
        Args:
            fetcher: 실제 API 호출 함수
            force: 캐시 무시하고 강제 조회
            
        Returns:
            잔고 데이터 또는 None
        """
        if not force:
            cached = self.balance_cache.get("balance")
            if cached is not None:
                self.stats.cache_hits += 1
                self.stats.saved_calls += 1
                return cached
        
        self.stats.cache_misses += 1
        
        # Rate limit 체크
        self.rate_limiter.wait_if_needed()
        
        try:
            self.stats.total_calls += 1
            result = fetcher()
            if result:
                self.balance_cache.set("balance", result)
            return result
        except Exception as e:
            self.stats.failed_calls += 1
            logger.error(f"[APICache] 잔고 조회 실패: {e}")
            raise
    
    def get_ohlcv(
        self, 
        symbol: str, 
        timeframe: str, 
        fetcher: Callable[[str, str], Any],
    ) -> Optional[Any]:
        """
        OHLCV 조회 (캐시)
        
        Args:
            symbol: 심볼
            timeframe: 타임프레임 (예: 30m, 1h)
            fetcher: 실제 API 호출 함수
            
        Returns:
            OHLCV 데이터 또는 None
        """
        key = f"{symbol}:{timeframe}"
        
        cached = self.ohlcv_cache.get(key)
        if cached is not None:
            self.stats.cache_hits += 1
            self.stats.saved_calls += 1
            return cached
        
        self.stats.cache_misses += 1
        
        # Rate limit 체크
        self.rate_limiter.wait_if_needed()
        
        try:
            self.stats.total_calls += 1
            result = fetcher(symbol, timeframe)
            if result is not None:
                self.ohlcv_cache.set(key, result)
            return result
        except Exception as e:
            self.stats.failed_calls += 1
            logger.error(f"[APICache] OHLCV 조회 실패 {symbol} {timeframe}: {e}")
            raise
    
    def get_orders(
        self, 
        symbol: str, 
        fetcher: Callable[[str], List],
        force: bool = False,
    ) -> Optional[List]:
        """
        주문 내역 조회 (캐시)
        
        Args:
            symbol: 심볼
            fetcher: 실제 API 호출 함수
            force: 캐시 무시하고 강제 조회
            
        Returns:
            주문 내역 리스트 또는 None
        """
        key = f"orders:{symbol}"
        
        if not force:
            cached = self.order_cache.get(key)
            if cached is not None:
                self.stats.cache_hits += 1
                self.stats.saved_calls += 1
                return cached
        
        self.stats.cache_misses += 1
        
        # Rate limit 체크
        self.rate_limiter.wait_if_needed()
        
        try:
            self.stats.total_calls += 1
            result = fetcher(symbol)
            if result is not None:
                self.order_cache.set(key, result)
            return result
        except Exception as e:
            self.stats.failed_calls += 1
            logger.error(f"[APICache] 주문 조회 실패 {symbol}: {e}")
            raise
    
    def invalidate_balance(self):
        """잔고 캐시 무효화 (주문 후 호출)"""
        self.balance_cache.delete("balance")
        logger.debug("[APICache] 잔고 캐시 무효화됨")
    
    def invalidate_orders(self, symbol: str = None):
        """
        주문 캐시 무효화
        
        Args:
            symbol: 특정 심볼만 무효화 (None이면 전체)
        """
        if symbol:
            self.order_cache.delete(f"orders:{symbol}")
        else:
            self.order_cache.clear()
        logger.debug(f"[APICache] 주문 캐시 무효화됨: {symbol or '전체'}")
    
    def clear_all(self):
        """모든 캐시 초기화"""
        self.ticker_cache.clear()
        self.balance_cache.clear()
        self.ohlcv_cache.clear()
        self.order_cache.clear()
        logger.info("[APICache] 전체 캐시 초기화됨")
    
    def get_stats(self) -> Dict:
        """통계 조회"""
        return {
            "total_calls": self.stats.total_calls,
            "cache_hits": self.stats.cache_hits,
            "cache_misses": self.stats.cache_misses,
            "hit_rate": f"{self.stats.hit_rate:.1f}%",
            "saved_calls": self.stats.saved_calls,
            "failed_calls": self.stats.failed_calls,
            "rate_limit_remaining": self.rate_limiter.remaining(),
        }
    
    def get_stats_summary(self) -> str:
        """통계 요약 문자열"""
        s = self.stats
        return (
            f"API calls={s.total_calls}, "
            f"cache_hit={s.hit_rate:.1f}%, "
            f"saved={s.saved_calls}, "
            f"failed={s.failed_calls}"
        )


# =========================================================
# 글로벌 인스턴스
# =========================================================

api_cache = SmartAPICache()

# 🆕 호환성을 위한 alias
APICacheManager = SmartAPICache


# =========================================================
# 편의 함수
# =========================================================

def get_api_cache() -> SmartAPICache:
    """글로벌 API 캐시 인스턴스 반환"""
    return api_cache


def get_cache_stats() -> Dict:
    """캐시 통계 조회"""
    return api_cache.get_stats()


def get_api_stats() -> Dict:
    """API 캐시 통계 조회 (alias)"""
    return api_cache.get_stats()


def invalidate_balance_cache():
    """잔고 캐시 무효화"""
    api_cache.invalidate_balance()


# =========================================================
# 🆕 캐시 접근 함수 (호환성)
# =========================================================

def get_cached_balance() -> Optional[Dict]:
    """캐시된 잔고 조회"""
    return api_cache.balance_cache.get("balance")


def set_cached_balance(balance: Dict, ttl: int = None):
    """잔고 캐시 저장"""
    api_cache.balance_cache.set("balance", balance, ttl or api_cache.BALANCE_TTL)


def get_cached_ticker(symbol: str) -> Optional[Dict]:
    """캐시된 티커 조회"""
    return api_cache.ticker_cache.get(f"ticker:{symbol}")


def set_cached_ticker(symbol: str, ticker: Dict, ttl: int = None):
    """티커 캐시 저장"""
    api_cache.ticker_cache.set(f"ticker:{symbol}", ticker, ttl or api_cache.TICKER_TTL)


def clear_all_api_cache() -> Dict:
    """모든 API 캐시 초기화"""
    return {
        "balance": api_cache.balance_cache.clear(),
        "ticker": api_cache.ticker_cache.clear(),
        "ohlcv": api_cache.ohlcv_cache.clear(),
        "order": api_cache.order_cache.clear(),
    }
