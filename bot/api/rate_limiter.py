# -*- coding: utf-8 -*-
"""
Phoenix v5.3.0 — Rate Limiter

API 호출 제한 관리를 담당합니다.

🔥 v5.3.0:
- bithumb_ccxt_api.py에서 분리
- Phase 1 데코레이터 모듈과 연동
- 통계 기능 강화
"""

import time
import threading
from collections import deque
from typing import Dict, Optional, Callable
from functools import wraps
from dataclasses import dataclass, field

from bot.utils.logger import get_logger

logger = get_logger("API.RateLimiter")


# =========================================================
# 데이터 클래스
# =========================================================

@dataclass
class RateLimitStats:
    """Rate Limit 통계"""
    total_calls: int = 0
    blocked_calls: int = 0
    rate_limit_hits: int = 0
    wait_time_total: float = 0.0
    
    def to_dict(self) -> Dict:
        return {
            "total_calls": self.total_calls,
            "blocked_calls": self.blocked_calls,
            "rate_limit_hits": self.rate_limit_hits,
            "wait_time_total": round(self.wait_time_total, 2),
        }


# =========================================================
# Rate Limiter 클래스
# =========================================================

class RateLimiter:
    """
    API 호출 Rate Limit 관리
    
    슬라이딩 윈도우 방식으로 호출 빈도를 제한합니다.
    
    Args:
        max_calls: 허용 호출 수 (기본: 500)
        per_seconds: 시간 윈도우 (초, 기본: 60)
        name: 리미터 이름 (로깅용)
    """
    
    def __init__(
        self, 
        max_calls: int = 500, 
        per_seconds: int = 60,
        name: str = "default"
    ):
        self.max_calls = max_calls
        self.per_seconds = per_seconds
        self.name = name
        
        self.calls: deque = deque()
        self.lock = threading.Lock()
        self.stats = RateLimitStats()
    
    def _cleanup_old_calls(self, now: float) -> None:
        """오래된 호출 기록 제거"""
        cutoff = now - self.per_seconds
        while self.calls and self.calls[0] < cutoff:
            self.calls.popleft()
    
    def acquire(self, wait: bool = True) -> bool:
        """
        호출 허용 여부 확인
        
        Args:
            wait: True면 허용될 때까지 대기
            
        Returns:
            True: 호출 허용
            False: 호출 차단 (wait=False일 때)
        """
        with self.lock:
            now = time.time()
            self._cleanup_old_calls(now)
            
            # 호출 가능
            if len(self.calls) < self.max_calls:
                self.calls.append(now)
                self.stats.total_calls += 1
                return True
            
            # Rate limit 도달
            self.stats.rate_limit_hits += 1
        
        if not wait:
            self.stats.blocked_calls += 1
            return False
        
        # 대기 후 재시도
        wait_time = self.calls[0] + self.per_seconds - time.time()
        if wait_time > 0:
            logger.warning(f"[RateLimit:{self.name}] 대기 중: {wait_time:.1f}초")
            self.stats.wait_time_total += wait_time
            time.sleep(wait_time + 0.1)
        
        return self.acquire(wait=False)
    
    def get_remaining(self) -> int:
        """남은 호출 가능 횟수"""
        with self.lock:
            now = time.time()
            self._cleanup_old_calls(now)
            return self.max_calls - len(self.calls)
    
    def get_usage_percent(self) -> float:
        """사용률 (%)"""
        remaining = self.get_remaining()
        used = self.max_calls - remaining
        return (used / self.max_calls) * 100 if self.max_calls > 0 else 0
    
    def get_stats(self) -> Dict:
        """통계 조회"""
        stats = self.stats.to_dict()
        stats.update({
            "remaining": self.get_remaining(),
            "max_calls": self.max_calls,
            "per_seconds": self.per_seconds,
            "usage_percent": round(self.get_usage_percent(), 1),
            "name": self.name,
        })
        return stats
    
    def reset_stats(self) -> None:
        """통계 초기화"""
        self.stats = RateLimitStats()
    
    def get_status_text(self) -> str:
        """텔레그램용 상태 텍스트"""
        stats = self.get_stats()
        return (
            f"📊 <b>Rate Limit 상태 ({self.name})</b>\n\n"
            f"남은 호출: {stats['remaining']}/{stats['max_calls']}\n"
            f"사용률: {stats['usage_percent']:.1f}%\n"
            f"총 호출: {stats['total_calls']:,}회\n"
            f"차단됨: {stats['blocked_calls']}회\n"
            f"Rate Limit 도달: {stats['rate_limit_hits']}회\n"
            f"총 대기 시간: {stats['wait_time_total']:.1f}초"
        )


# =========================================================
# Retry 데코레이터 (Rate Limit 인식)
# =========================================================

def retry_with_backoff(
    max_retries: int = 3,
    base_delay: float = 1.0,
    max_delay: float = 30.0,
    rate_limit_multiplier: float = 2.0,
):
    """
    Exponential Backoff Retry 데코레이터
    
    Rate limit 감지 시 더 긴 대기 시간 적용
    
    Args:
        max_retries: 최대 재시도 횟수
        base_delay: 초기 대기 시간 (초)
        max_delay: 최대 대기 시간 (초)
        rate_limit_multiplier: Rate limit 시 대기 시간 배수
    """
    def decorator(func: Callable):
        @wraps(func)
        def wrapper(*args, **kwargs):
            last_error = None
            delay = base_delay
            
            for attempt in range(max_retries + 1):
                try:
                    return func(*args, **kwargs)
                except Exception as e:
                    last_error = e
                    error_str = str(e).lower()
                    
                    # Rate limit 감지
                    is_rate_limit = any(x in error_str for x in [
                        "429", "rate limit", "too many", 
                        "access too frequent", "exceeded"
                    ])
                    
                    if attempt < max_retries:
                        if is_rate_limit:
                            wait = min(delay * rate_limit_multiplier, max_delay)
                            logger.warning(
                                f"[Rate Limit] {func.__name__} - "
                                f"{wait:.1f}초 대기 후 재시도 ({attempt+1}/{max_retries})"
                            )
                        else:
                            wait = min(delay, max_delay)
                            logger.debug(
                                f"[Retry {attempt+1}/{max_retries}] {func.__name__} - "
                                f"{wait:.1f}초 후 재시도: {e}"
                            )
                        
                        time.sleep(wait)
                        delay *= 2  # Exponential backoff
                    else:
                        logger.error(f"[Retry Failed] {func.__name__}: {e}")
            
            raise last_error
        return wrapper
    return decorator


# =========================================================
# 글로벌 Rate Limiter
# =========================================================

# 빗썸 API용 (분당 500 호출)
bithumb_rate_limiter = RateLimiter(
    max_calls=500,
    per_seconds=60,
    name="bithumb"
)


def get_bithumb_rate_limiter() -> RateLimiter:
    """빗썸 Rate Limiter 반환"""
    return bithumb_rate_limiter


def check_rate_limit(wait: bool = True) -> bool:
    """빗썸 Rate Limit 체크 (편의 함수)"""
    return bithumb_rate_limiter.acquire(wait)


# =========================================================
# Rate Limited 데코레이터
# =========================================================

def rate_limited(limiter: Optional[RateLimiter] = None):
    """
    Rate Limit 적용 데코레이터
    
    Args:
        limiter: 사용할 RateLimiter (None이면 빗썸 기본값)
    """
    def decorator(func: Callable):
        @wraps(func)
        def wrapper(*args, **kwargs):
            rl = limiter or bithumb_rate_limiter
            rl.acquire(wait=True)
            return func(*args, **kwargs)
        return wrapper
    return decorator
