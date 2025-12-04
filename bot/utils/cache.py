# -*- coding: utf-8 -*-
"""
Phoenix v5.3.0 — 통합 캐시 관리자

모든 캐시를 일관된 방식으로 관리
- 스레드 안전
- TTL 기반 만료
- 통계 추적
"""

import time
import threading
from typing import Any, Optional, Dict, Callable, TypeVar
from functools import wraps
from dataclasses import dataclass, field

T = TypeVar('T')


@dataclass
class CacheEntry:
    """캐시 엔트리"""
    value: Any
    expires_at: float
    created_at: float
    hits: int = 0


class CacheManager:
    """
    스레드 안전한 캐시 관리자
    
    Usage:
        cache = CacheManager(default_ttl=60)
        cache.set("key", value, ttl=30)
        value = cache.get("key")
    """
    
    def __init__(self, default_ttl: int = 60, name: str = "default"):
        """
        Args:
            default_ttl: 기본 TTL (초)
            name: 캐시 이름 (로깅/디버깅용)
        """
        self.default_ttl = default_ttl
        self.name = name
        self._cache: Dict[str, CacheEntry] = {}
        self._lock = threading.RLock()
        self._stats = {
            "hits": 0,
            "misses": 0,
            "sets": 0,
            "deletes": 0,
            "expirations": 0,
        }
    
    def get(self, key: str) -> Optional[Any]:
        """
        캐시에서 값 조회 (만료 체크)
        
        Args:
            key: 캐시 키
            
        Returns:
            캐시된 값 또는 None
        """
        with self._lock:
            if key not in self._cache:
                self._stats["misses"] += 1
                return None
            
            entry = self._cache[key]
            now = time.time()
            
            if now > entry.expires_at:
                del self._cache[key]
                self._stats["misses"] += 1
                self._stats["expirations"] += 1
                return None
            
            entry.hits += 1
            self._stats["hits"] += 1
            return entry.value
    
    def set(self, key: str, value: Any, ttl: int = None) -> None:
        """
        캐시에 값 저장
        
        Args:
            key: 캐시 키
            value: 저장할 값
            ttl: TTL (초), None이면 default_ttl 사용
        """
        with self._lock:
            now = time.time()
            self._cache[key] = CacheEntry(
                value=value,
                expires_at=now + (ttl if ttl is not None else self.default_ttl),
                created_at=now,
            )
            self._stats["sets"] += 1
    
    def delete(self, key: str) -> bool:
        """
        캐시에서 삭제
        
        Args:
            key: 캐시 키
            
        Returns:
            삭제 성공 여부
        """
        with self._lock:
            if key in self._cache:
                del self._cache[key]
                self._stats["deletes"] += 1
                return True
            return False
    
    def clear(self) -> int:
        """
        전체 캐시 삭제
        
        Returns:
            삭제된 항목 수
        """
        with self._lock:
            count = len(self._cache)
            self._cache.clear()
            return count
    
    def get_or_set(
        self, 
        key: str, 
        factory: Callable[[], T], 
        ttl: int = None
    ) -> T:
        """
        캐시 조회 또는 생성
        
        Args:
            key: 캐시 키
            factory: 값 생성 함수
            ttl: TTL (초)
            
        Returns:
            캐시된 값 또는 새로 생성된 값
        """
        value = self.get(key)
        if value is not None:
            return value
        
        value = factory()
        if value is not None:
            self.set(key, value, ttl)
        return value
    
    def exists(self, key: str) -> bool:
        """키 존재 여부 확인 (만료 체크 포함)"""
        return self.get(key) is not None
    
    def ttl_remaining(self, key: str) -> Optional[float]:
        """남은 TTL 조회 (초)"""
        with self._lock:
            if key not in self._cache:
                return None
            
            entry = self._cache[key]
            remaining = entry.expires_at - time.time()
            return max(0, remaining)
    
    def cleanup_expired(self) -> int:
        """만료된 항목 정리"""
        with self._lock:
            now = time.time()
            expired_keys = [
                k for k, v in self._cache.items() 
                if v.expires_at < now
            ]
            for key in expired_keys:
                del self._cache[key]
                self._stats["expirations"] += 1
            return len(expired_keys)
    
    def stats(self) -> Dict:
        """캐시 통계"""
        with self._lock:
            now = time.time()
            valid = sum(1 for e in self._cache.values() if e.expires_at > now)
            total_hits = sum(e.hits for e in self._cache.values())
            
            hit_rate = 0.0
            total_access = self._stats["hits"] + self._stats["misses"]
            if total_access > 0:
                hit_rate = self._stats["hits"] / total_access * 100
            
            return {
                "name": self.name,
                "total_entries": len(self._cache),
                "valid_entries": valid,
                "expired_entries": len(self._cache) - valid,
                "total_hits": total_hits,
                "hit_rate": f"{hit_rate:.1f}%",
                **self._stats,
            }
    
    def __len__(self) -> int:
        return len(self._cache)
    
    def __contains__(self, key: str) -> bool:
        return self.exists(key)


def cached(
    cache: CacheManager, 
    key_prefix: str = "", 
    ttl: int = None,
    key_builder: Callable = None,
):
    """
    캐시 데코레이터
    
    Usage:
        @cached(price_cache, "ticker", ttl=10)
        def get_ticker(symbol: str) -> dict:
            return api.fetch_ticker(symbol)
    
    Args:
        cache: CacheManager 인스턴스
        key_prefix: 캐시 키 접두사
        ttl: TTL (초)
        key_builder: 커스텀 키 생성 함수
    """
    def decorator(func: Callable):
        @wraps(func)
        def wrapper(*args, **kwargs):
            # 캐시 키 생성
            if key_builder:
                cache_key = key_builder(*args, **kwargs)
            else:
                key_parts = [key_prefix] if key_prefix else [func.__name__]
                key_parts.extend(str(arg) for arg in args if arg is not None)
                key_parts.extend(f"{k}={v}" for k, v in sorted(kwargs.items()))
                cache_key = ":".join(key_parts)
            
            # 캐시 조회 또는 실행
            return cache.get_or_set(
                cache_key,
                lambda: func(*args, **kwargs),
                ttl
            )
        
        # 캐시 무효화 헬퍼
        def invalidate(*args, **kwargs):
            if key_builder:
                cache_key = key_builder(*args, **kwargs)
            else:
                key_parts = [key_prefix] if key_prefix else [func.__name__]
                key_parts.extend(str(arg) for arg in args if arg is not None)
                key_parts.extend(f"{k}={v}" for k, v in sorted(kwargs.items()))
                cache_key = ":".join(key_parts)
            cache.delete(cache_key)
        
        wrapper.invalidate = invalidate
        wrapper.cache = cache
        return wrapper
    
    return decorator


# =========================================================
# 글로벌 캐시 인스턴스
# =========================================================

# 가격 데이터: 5초 TTL
price_cache = CacheManager(default_ttl=5, name="price")

# 티커 데이터: 5초 TTL
ticker_cache = CacheManager(default_ttl=5, name="ticker")

# 잔고 데이터: 10초 TTL
balance_cache = CacheManager(default_ttl=10, name="balance")

# OHLCV 데이터: 30초 TTL
ohlcv_cache = CacheManager(default_ttl=30, name="ohlcv")

# 기술적 지표: 60초 TTL
indicator_cache = CacheManager(default_ttl=60, name="indicator")

# AI 분석 결과: 180초 (3분) TTL
ai_cache = CacheManager(default_ttl=180, name="ai")

# BTC 컨텍스트: 60초 TTL
btc_context_cache = CacheManager(default_ttl=60, name="btc_context")

# 마켓 정보: 3600초 (1시간) TTL
markets_cache = CacheManager(default_ttl=3600, name="markets")


def get_all_cache_stats() -> Dict[str, Dict]:
    """모든 캐시 통계 조회"""
    return {
        "price": price_cache.stats(),
        "ticker": ticker_cache.stats(),
        "balance": balance_cache.stats(),
        "ohlcv": ohlcv_cache.stats(),
        "indicator": indicator_cache.stats(),
        "ai": ai_cache.stats(),
        "btc_context": btc_context_cache.stats(),
        "markets": markets_cache.stats(),
    }


def clear_all_caches() -> Dict[str, int]:
    """모든 캐시 초기화"""
    return {
        "price": price_cache.clear(),
        "ticker": ticker_cache.clear(),
        "balance": balance_cache.clear(),
        "ohlcv": ohlcv_cache.clear(),
        "indicator": indicator_cache.clear(),
        "ai": ai_cache.clear(),
        "btc_context": btc_context_cache.clear(),
        "markets": markets_cache.clear(),
    }
