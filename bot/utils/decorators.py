# -*- coding: utf-8 -*-
"""
Phoenix v5.3.0 — 공통 데코레이터

재시도, 에러 핸들링, 로깅, 성능 측정 등
"""

import time
import functools
import threading
from typing import Callable, Any, Type, Tuple, Optional, TypeVar
from datetime import datetime

# 로거는 나중에 초기화 (순환 import 방지)
_logger = None

def _get_logger():
    global _logger
    if _logger is None:
        try:
            from bot.utils.logger import get_logger
            _logger = get_logger("Decorators")
        except ImportError:
            import logging
            _logger = logging.getLogger("Decorators")
    return _logger


T = TypeVar('T')
F = TypeVar('F', bound=Callable[..., Any])


def retry(
    max_attempts: int = 3,
    delay: float = 1.0,
    backoff: float = 2.0,
    max_delay: float = 60.0,
    exceptions: Tuple[Type[Exception], ...] = (Exception,),
    on_retry: Callable[[int, Exception], None] = None,
    on_failure: Callable[[Exception], Any] = None,
) -> Callable[[F], F]:
    """
    재시도 데코레이터
    
    Usage:
        @retry(max_attempts=3, delay=1.0, exceptions=(ConnectionError,))
        def fetch_data():
            return api.get_data()
    
    Args:
        max_attempts: 최대 시도 횟수
        delay: 초기 대기 시간 (초)
        backoff: 대기 시간 증가 배수
        max_delay: 최대 대기 시간 (초)
        exceptions: 재시도할 예외 타입들
        on_retry: 재시도 시 콜백 (attempt, exception)
        on_failure: 모든 시도 실패 시 콜백 (exception) -> 반환값
    """
    def decorator(func: F) -> F:
        @functools.wraps(func)
        def wrapper(*args, **kwargs) -> Any:
            logger = _get_logger()
            current_delay = delay
            last_exception = None
            
            for attempt in range(1, max_attempts + 1):
                try:
                    return func(*args, **kwargs)
                except exceptions as e:
                    last_exception = e
                    
                    if attempt < max_attempts:
                        if on_retry:
                            on_retry(attempt, e)
                        else:
                            logger.warning(
                                f"[{func.__name__}] 시도 {attempt}/{max_attempts} 실패: {e}. "
                                f"{current_delay:.1f}초 후 재시도..."
                            )
                        
                        time.sleep(current_delay)
                        current_delay = min(current_delay * backoff, max_delay)
            
            # 모든 시도 실패
            logger.error(
                f"[{func.__name__}] {max_attempts}회 시도 모두 실패: {last_exception}"
            )
            
            if on_failure:
                return on_failure(last_exception)
            
            raise last_exception
        
        return wrapper  # type: ignore
    
    return decorator


def safe_execute(
    default: Any = None,
    log_error: bool = True,
    notify: bool = False,
    reraise: bool = False,
    error_handler: Callable[[Exception], Any] = None,
) -> Callable[[F], F]:
    """
    안전 실행 데코레이터 (예외 발생 시 기본값 반환)
    
    Usage:
        @safe_execute(default=0, log_error=True)
        def risky_calculation():
            return 1 / 0
    
    Args:
        default: 예외 발생 시 반환할 기본값 (callable이면 호출)
        log_error: 에러 로깅 여부
        notify: 텔레그램 알림 여부 (미구현)
        reraise: 예외 재발생 여부
        error_handler: 커스텀 에러 핸들러
    """
    def decorator(func: F) -> F:
        @functools.wraps(func)
        def wrapper(*args, **kwargs) -> Any:
            try:
                return func(*args, **kwargs)
            except Exception as e:
                logger = _get_logger()
                
                if log_error:
                    # Phoenix 예외면 상세 정보 로깅
                    try:
                        from bot.utils.exceptions import PhoenixBaseException
                        if isinstance(e, PhoenixBaseException):
                            logger.error(f"[{func.__name__}] {e.code}: {e.message}")
                        else:
                            logger.error(f"[{func.__name__}] 오류: {e}")
                    except ImportError:
                        logger.error(f"[{func.__name__}] 오류: {e}")
                
                if error_handler:
                    return error_handler(e)
                
                if notify:
                    # TODO: 텔레그램 알림 연동
                    pass
                
                if reraise:
                    raise
                
                if callable(default):
                    return default()
                return default
        
        return wrapper  # type: ignore
    
    return decorator


def log_execution(
    log_args: bool = False,
    log_result: bool = False,
    log_time: bool = True,
    min_duration: float = 0.0,
) -> Callable[[F], F]:
    """
    실행 로깅 데코레이터
    
    Usage:
        @log_execution(log_time=True, min_duration=1.0)
        def slow_function():
            time.sleep(2)
    
    Args:
        log_args: 인자 로깅 여부
        log_result: 결과 로깅 여부
        log_time: 실행 시간 로깅 여부
        min_duration: 이 시간(초) 이상일 때만 로깅
    """
    def decorator(func: F) -> F:
        @functools.wraps(func)
        def wrapper(*args, **kwargs) -> Any:
            logger = _get_logger()
            func_name = func.__name__
            start = time.time()
            
            if log_args:
                # 민감 정보 마스킹
                safe_args = [str(a)[:50] for a in args]
                safe_kwargs = {k: str(v)[:50] for k, v in kwargs.items()}
                logger.debug(f"[{func_name}] 시작 - args={safe_args}, kwargs={safe_kwargs}")
            
            try:
                result = func(*args, **kwargs)
                elapsed = time.time() - start
                
                if log_time and elapsed >= min_duration:
                    if log_result:
                        result_str = str(result)[:100]
                        logger.debug(f"[{func_name}] 완료 ({elapsed:.3f}s) - result={result_str}")
                    else:
                        logger.debug(f"[{func_name}] 완료 ({elapsed:.3f}s)")
                
                return result
            except Exception as e:
                elapsed = time.time() - start
                logger.error(f"[{func_name}] 실패 ({elapsed:.3f}s) - {e}")
                raise
        
        return wrapper  # type: ignore
    
    return decorator


def throttle(min_interval: float = 1.0) -> Callable[[F], F]:
    """
    쓰로틀링 데코레이터 (최소 호출 간격 보장)
    
    Usage:
        @throttle(min_interval=0.5)
        def api_call():
            return requests.get(url)
    
    Args:
        min_interval: 최소 호출 간격 (초)
    """
    def decorator(func: F) -> F:
        last_called = [0.0]  # mutable container for closure
        lock = threading.Lock()
        
        @functools.wraps(func)
        def wrapper(*args, **kwargs) -> Any:
            with lock:
                now = time.time()
                elapsed = now - last_called[0]
                
                if elapsed < min_interval:
                    wait_time = min_interval - elapsed
                    time.sleep(wait_time)
                
                last_called[0] = time.time()
                return func(*args, **kwargs)
        
        # 마지막 호출 시간 리셋 헬퍼
        def reset():
            with lock:
                last_called[0] = 0.0
        
        wrapper.reset = reset
        return wrapper  # type: ignore
    
    return decorator


def debounce(wait: float = 1.0) -> Callable[[F], F]:
    """
    디바운스 데코레이터 (연속 호출 시 마지막만 실행)
    
    Usage:
        @debounce(wait=0.5)
        def on_input_change(value):
            process(value)
    
    Args:
        wait: 대기 시간 (초)
    """
    def decorator(func: F) -> F:
        timer = [None]  # mutable container
        lock = threading.Lock()
        
        @functools.wraps(func)
        def wrapper(*args, **kwargs) -> None:
            def call_func():
                with lock:
                    timer[0] = None
                func(*args, **kwargs)
            
            with lock:
                if timer[0] is not None:
                    timer[0].cancel()
                timer[0] = threading.Timer(wait, call_func)
                timer[0].start()
        
        def cancel():
            with lock:
                if timer[0] is not None:
                    timer[0].cancel()
                    timer[0] = None
        
        wrapper.cancel = cancel
        return wrapper  # type: ignore
    
    return decorator


def singleton(cls: Type[T]) -> Type[T]:
    """
    싱글톤 데코레이터
    
    Usage:
        @singleton
        class DatabaseConnection:
            def __init__(self):
                self.connect()
    """
    instances = {}
    lock = threading.Lock()
    
    @functools.wraps(cls)
    def get_instance(*args, **kwargs) -> T:
        with lock:
            if cls not in instances:
                instances[cls] = cls(*args, **kwargs)
            return instances[cls]
    
    # 인스턴스 리셋 헬퍼
    def reset():
        with lock:
            if cls in instances:
                del instances[cls]
    
    get_instance.reset = reset
    get_instance._instances = instances
    return get_instance  # type: ignore


def deprecated(reason: str = "", alternative: str = "") -> Callable[[F], F]:
    """
    사용 중단 경고 데코레이터
    
    Usage:
        @deprecated(reason="Old API", alternative="use new_function()")
        def old_function():
            pass
    """
    def decorator(func: F) -> F:
        @functools.wraps(func)
        def wrapper(*args, **kwargs) -> Any:
            logger = _get_logger()
            msg = f"[DEPRECATED] {func.__name__}()"
            if reason:
                msg += f" - {reason}"
            if alternative:
                msg += f". 대안: {alternative}"
            logger.warning(msg)
            return func(*args, **kwargs)
        
        return wrapper  # type: ignore
    
    return decorator


def timed(label: str = None) -> Callable[[F], F]:
    """
    실행 시간 측정 데코레이터
    
    Usage:
        @timed("data_fetch")
        def fetch_data():
            return api.get()
    
    Args:
        label: 측정 라벨 (기본: 함수명)
    """
    def decorator(func: F) -> F:
        func_label = label or func.__name__
        
        @functools.wraps(func)
        def wrapper(*args, **kwargs) -> Any:
            logger = _get_logger()
            start = time.time()
            
            try:
                result = func(*args, **kwargs)
                elapsed = time.time() - start
                logger.info(f"[TIMER] {func_label}: {elapsed:.3f}s")
                return result
            except Exception as e:
                elapsed = time.time() - start
                logger.info(f"[TIMER] {func_label}: {elapsed:.3f}s (실패)")
                raise
        
        return wrapper  # type: ignore
    
    return decorator


def run_once(func: F) -> F:
    """
    한 번만 실행 데코레이터
    
    Usage:
        @run_once
        def initialize():
            setup_database()
    """
    executed = [False]
    result = [None]
    lock = threading.Lock()
    
    @functools.wraps(func)
    def wrapper(*args, **kwargs) -> Any:
        with lock:
            if not executed[0]:
                result[0] = func(*args, **kwargs)
                executed[0] = True
            return result[0]
    
    def reset():
        with lock:
            executed[0] = False
            result[0] = None
    
    wrapper.reset = reset
    wrapper.executed = lambda: executed[0]
    return wrapper  # type: ignore


def synchronized(lock: threading.Lock = None) -> Callable[[F], F]:
    """
    동기화 데코레이터
    
    Usage:
        @synchronized()
        def thread_safe_operation():
            # critical section
            pass
    
    Args:
        lock: 사용할 Lock (기본: 새 Lock 생성)
    """
    _lock = lock or threading.Lock()
    
    def decorator(func: F) -> F:
        @functools.wraps(func)
        def wrapper(*args, **kwargs) -> Any:
            with _lock:
                return func(*args, **kwargs)
        
        wrapper.lock = _lock
        return wrapper  # type: ignore
    
    return decorator


def async_timeout(seconds: float) -> Callable[[F], F]:
    """
    동기 함수에 타임아웃 적용 (스레드 기반)
    
    Usage:
        @async_timeout(10.0)
        def long_running_task():
            # 10초 이상 걸리면 TimeoutError
            pass
    
    Args:
        seconds: 타임아웃 (초)
    """
    def decorator(func: F) -> F:
        @functools.wraps(func)
        def wrapper(*args, **kwargs) -> Any:
            result = [None]
            exception = [None]
            
            def target():
                try:
                    result[0] = func(*args, **kwargs)
                except Exception as e:
                    exception[0] = e
            
            thread = threading.Thread(target=target)
            thread.start()
            thread.join(timeout=seconds)
            
            if thread.is_alive():
                raise TimeoutError(f"{func.__name__} 타임아웃 ({seconds}초)")
            
            if exception[0]:
                raise exception[0]
            
            return result[0]
        
        return wrapper  # type: ignore
    
    return decorator


# =========================================================
# 조합 데코레이터
# =========================================================

def robust(
    max_attempts: int = 3,
    delay: float = 1.0,
    default: Any = None,
    log_error: bool = True,
) -> Callable[[F], F]:
    """
    견고한 실행 데코레이터 (retry + safe_execute 조합)
    
    Usage:
        @robust(max_attempts=3, default=None)
        def fetch_data():
            return api.get()
    """
    def decorator(func: F) -> F:
        @retry(max_attempts=max_attempts, delay=delay)
        @safe_execute(default=default, log_error=log_error)
        @functools.wraps(func)
        def wrapper(*args, **kwargs) -> Any:
            return func(*args, **kwargs)
        
        return wrapper  # type: ignore
    
    return decorator
