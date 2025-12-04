# -*- coding: utf-8 -*-
"""
Phoenix v5.3.0 — CCXT Bithumb API (Phase A: OHLCV 캐시 추가)

🔥 v5.3.0 Phase A 변경:
- OHLCV 캐싱 추가 (ohlcv_cache 연동)
- fetch_ohlcv()에 캐시 적용 (TTL 30초)
- 캐시 통계에 OHLCV 추가

🔥 v5.3.0 기존 기능:
- bot.utils.cache 모듈 사용 (balance_cache, ticker_cache, markets_cache)
- 로컬 캐시 변수 → 통합 캐시 모듈로 전환
- 캐시 통계 기능

🔧 v5.1.1 기능 유지:
- 동적 수량 정밀도 조회 - 빗썸 마켓 정보에서 자동 조회
- COIN_QTY_PRECISION 테이블 → 오버라이드 전용
- set_precision_fetcher() 함수
- _load_markets_precision() 메서드

🔧 v5.1.0d 기능 유지:
- @retry_with_backoff 데코레이터
- CCXT 타임아웃 15초 설정
- 매도 실패 시 최대 5회 재시도 (지수 백오프)
"""

import ccxt
import pandas as pd
import time
import threading
import math
from collections import deque
from typing import Dict, Optional

from config import Config
from bot.utils.logger import get_logger

# 🆕 v5.3.0 Phase A: ohlcv_cache 추가
from bot.utils.cache import balance_cache, ticker_cache, markets_cache, ohlcv_cache

logger = get_logger("BithumbAPI")


# =========================================================
# 🔥 Rate Limiter 클래스
# =========================================================
class RateLimiter:
    """API 호출 Rate Limit 관리"""
    
    def __init__(self, max_calls: int = 500, per_seconds: int = 60):
        """
        Args:
            max_calls: 허용 호출 수
            per_seconds: 시간 윈도우 (초)
        """
        self.max_calls = max_calls
        self.per_seconds = per_seconds
        self.calls: deque = deque()
        self.lock = threading.Lock()
        
        # 통계
        self.total_calls = 0
        self.blocked_calls = 0
        self.rate_limit_hits = 0
    
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
            cutoff = now - self.per_seconds
            
            # 오래된 호출 제거
            while self.calls and self.calls[0] < cutoff:
                self.calls.popleft()
            
            # 호출 가능 여부 확인
            if len(self.calls) < self.max_calls:
                self.calls.append(now)
                self.total_calls += 1
                return True
            
            # Rate limit 도달
            self.rate_limit_hits += 1
        
        if not wait:
            self.blocked_calls += 1
            return False
        
        # 대기 후 재시도
        wait_time = self.calls[0] + self.per_seconds - time.time()
        if wait_time > 0:
            logger.warning(f"[RateLimit] 대기 중: {wait_time:.1f}초")
            time.sleep(wait_time + 0.1)
        
        return self.acquire(wait=False)
    
    def get_remaining(self) -> int:
        """남은 호출 가능 횟수"""
        with self.lock:
            now = time.time()
            cutoff = now - self.per_seconds
            while self.calls and self.calls[0] < cutoff:
                self.calls.popleft()
            return self.max_calls - len(self.calls)
    
    def get_stats(self) -> Dict:
        """통계 조회"""
        return {
            "total_calls": self.total_calls,
            "blocked_calls": self.blocked_calls,
            "rate_limit_hits": self.rate_limit_hits,
            "remaining": self.get_remaining(),
            "max_calls": self.max_calls,
            "per_seconds": self.per_seconds,
        }


# =========================================================
# 심볼 통일
# =========================================================
def convert_symbol(sym: str) -> str:
    """심볼 포맷 변환"""
    sym = sym.replace("-", "/").upper()
    if "/KRW" not in sym:
        sym = sym.split("/")[0] + "/KRW"
    return sym


# =========================================================
# 가격대별 틱 사이즈
# =========================================================
def get_tick_size(price: float) -> float:
    """
    빗썸 가격대별 틱 사이즈 반환
    
    빗썸 호가 단위:
    - 100만원 이상: 1,000원
    - 10만원 이상: 100원
    - 1만원 이상: 10원
    - 1,000원 이상: 1원
    - 100원 이상: 0.1원
    - 10원 이상: 0.01원
    - 10원 미만: 0.001원
    """
    if price >= 1_000_000:
        return 1000
    elif price >= 100_000:
        return 100
    elif price >= 10_000:
        return 10
    elif price >= 1_000:
        return 1
    elif price >= 100:
        return 0.1
    elif price >= 10:
        return 0.01
    else:
        return 0.001


def round_to_tick(price: float, direction: str = "nearest") -> float:
    """
    가격을 틱 사이즈에 맞게 반올림
    
    Args:
        price: 원본 가격
        direction: "nearest" (반올림), "up" (올림), "down" (내림)
    
    Returns:
        틱 사이즈에 맞춘 가격
    """
    if price <= 0:
        return 0
    
    tick = get_tick_size(price)
    
    if tick >= 1:
        # 정수 틱 사이즈
        if direction == "up":
            return math.ceil(price / tick) * tick
        elif direction == "down":
            return math.floor(price / tick) * tick
        else:
            return round(price / tick) * tick
    else:
        # 소수 틱 사이즈
        decimals = len(str(tick).split('.')[-1])
        if direction == "up":
            factor = 10 ** decimals
            return math.ceil(price * factor) / factor
        elif direction == "down":
            factor = 10 ** decimals
            return math.floor(price * factor) / factor
        else:
            return round(price, decimals)


# =========================================================
# 수동 오버라이드 테이블 (필요 시만 사용)
# =========================================================
COIN_QTY_PRECISION: Dict[str, int] = {
    # 🔥 v5.3.1d: 저가 코인 precision 수동 설정
    "MOODENG": 2,
    "FLOKI": 2,
    "BONK": 0,
    "PENGU": 2,
    # 빗썸 마켓 정보가 부정확한 경우 여기에 수동 추가
    # 예: "SPECIAL_COIN": 3,
}


# =========================================================
# 동적 정밀도 조회용 전역 참조
# =========================================================
_precision_fetcher = None


def set_precision_fetcher(api_instance):
    """
    API 인스턴스 설정 (main.py에서 호출)
    
    Args:
        api_instance: BithumbAPI 인스턴스
    """
    global _precision_fetcher
    _precision_fetcher = api_instance
    logger.info("[QTY_PRECISION] 동적 정밀도 조회기 설정 완료")


# =========================================================
# 가격 기반 정밀도 폴백 함수
# =========================================================
def _get_qty_precision_by_price(price: float) -> int:
    """
    가격 기반 수량 정밀도 추정 (폴백용)
    
    빗썸 수량 규칙 (추정):
    - 1만원 이상: 소수점 4자리
    - 1천원 이상: 소수점 4자리
    - 100원 이상: 소수점 2자리 (KAIA, SHIB 등)
    - 10원 이상: 소수점 1자리
    - 10원 미만: 정수만 (BONK 등 초저가)
    
    Args:
        price: 코인 현재가
        
    Returns:
        허용 소수점 자릿수
    """
    if price >= 1000:      # 1천원 이상
        return 4
    elif price >= 100:     # 100원 이상
        return 2
    elif price >= 10:      # 10원 이상
        return 1
    else:                  # 10원 미만
        return 0


# =========================================================
# 동적 수량 정밀도 조회 함수
# =========================================================
def get_qty_precision(symbol_or_price, price: float = None) -> int:
    """
    동적 수량 정밀도 조회
    
    조회 순서:
    1. COIN_QTY_PRECISION 테이블 (수동 오버라이드)
    2. 빗썸 마켓 정보 (동적 조회)
    3. 가격 기반 폴백
    
    Args:
        symbol_or_price: 심볼 문자열 (예: "BTC/KRW", "BTC") 또는 가격 (후방호환)
        price: 가격 (폴백용, 심볼 조회 시 사용)
        
    Returns:
        허용 소수점 자릿수
    """
    global _precision_fetcher
    
    # 심볼 문자열인 경우
    if isinstance(symbol_or_price, str):
        coin = symbol_or_price.replace("/KRW", "").replace("-KRW", "").upper()
        
        # 1️⃣ 수동 테이블 우선 (오버라이드용)
        if coin in COIN_QTY_PRECISION:
            logger.debug(f"[QTY_PRECISION] {coin} → {COIN_QTY_PRECISION[coin]} (수동 테이블)")
            return COIN_QTY_PRECISION[coin]
        
        # 2️⃣ 빗썸 마켓 정보에서 동적 조회
        if _precision_fetcher is not None:
            try:
                precision = _precision_fetcher.get_precision_for_coin(coin)
                if precision is not None:
                    logger.debug(f"[QTY_PRECISION] {coin} → {precision} (동적 조회)")
                    return precision
            except Exception as e:
                logger.warning(f"[QTY_PRECISION] 동적 조회 실패: {e}")
        
        # 3️⃣ 가격 기반 폴백
        if price is not None and price > 0:
            fallback = _get_qty_precision_by_price(price)
            logger.debug(f"[QTY_PRECISION] {coin} → {fallback} (가격 기반 폴백, price={price:.4f})")
            return fallback
        
        # 4️⃣ 최종 기본값 (보수적으로 4 사용)
        logger.warning(f"[QTY_PRECISION] {coin} 정밀도 미정의 → 기본값 4 사용")
        return 4
    
    # 숫자인 경우 (후방호환성 유지)
    elif isinstance(symbol_or_price, (int, float)):
        return _get_qty_precision_by_price(symbol_or_price)
    
    return 4  # 안전한 기본값


def round_qty(qty: float, price_or_symbol, direction: str = "down") -> float:
    """
    수량을 가격대/심볼에 맞게 반올림
    
    Args:
        qty: 원본 수량
        price_or_symbol: 코인 현재가 또는 심볼 (정밀도 결정용)
        direction: "down" (내림, 기본값), "up" (올림), "nearest" (반올림)
    
    Returns:
        정밀도에 맞춘 수량
    """
    # 심볼인 경우 정밀도 조회
    if isinstance(price_or_symbol, str):
        precision = get_qty_precision(price_or_symbol)
    else:
        # 가격인 경우 (후방호환)
        precision = get_qty_precision(price_or_symbol)
    
    factor = 10 ** precision
    
    if direction == "down":
        return math.floor(qty * factor) / factor
    elif direction == "up":
        return math.ceil(qty * factor) / factor
    else:
        return round(qty, precision)


# =========================================================
# Exponential Backoff Retry
# =========================================================
def retry_with_backoff(max_retries: int = 3, base_delay: float = 1.0, max_delay: float = 30.0):
    """
    Exponential Backoff Retry 데코레이터
    
    Args:
        max_retries: 최대 재시도 횟수
        base_delay: 초기 대기 시간 (초)
        max_delay: 최대 대기 시간 (초)
    """
    def decorator(func):
        def wrapper(*args, **kwargs):
            last_error = None
            delay = base_delay
            
            for attempt in range(max_retries + 1):
                try:
                    return func(*args, **kwargs)
                except Exception as e:
                    last_error = e
                    error_str = str(e).lower()
                    
                    # Rate limit 감지 (429 또는 관련 메시지)
                    is_rate_limit = any(x in error_str for x in [
                        "429", "rate limit", "too many", "access too frequent"
                    ])
                    
                    if attempt < max_retries:
                        if is_rate_limit:
                            # Rate limit: 더 긴 대기
                            wait = min(delay * 2, max_delay)
                            logger.warning(f"[Rate Limit] {func.__name__} - {wait:.1f}초 대기 후 재시도")
                        else:
                            wait = min(delay, max_delay)
                            logger.debug(f"[Retry {attempt+1}/{max_retries}] {func.__name__} - {wait:.1f}초 후 재시도")
                        
                        time.sleep(wait)
                        delay *= 2  # Exponential backoff
                    else:
                        logger.error(f"[Retry Failed] {func.__name__}: {e}")
            
            raise last_error
        return wrapper
    return decorator


# =========================================================
# BithumbAPI 클래스 (v5.3.0 Phase A: OHLCV 캐시 추가)
# =========================================================
class BithumbAPI:
    """빗썸 API 래퍼 (v5.3.0 Phase A - OHLCV 캐시 추가)"""
    
    # 캐시 TTL 설정 (캐시 모듈에서 사용)
    BALANCE_CACHE_TTL = 10      # 잔고 캐시 10초
    TICKER_CACHE_TTL = 5        # 티커 캐시 5초
    MARKETS_CACHE_TTL = 3600    # 마켓 정밀도 캐시 1시간
    OHLCV_CACHE_TTL = 30        # 🆕 OHLCV 캐시 30초
    
    def __init__(self):
        try:
            self.exchange = ccxt.bithumb({
                "apiKey": Config.BITHUMB_API_KEY,
                "secret": Config.BITHUMB_SECRET_KEY,
                "enableRateLimit": True,
                "timeout": 15000,  # 15초 타임아웃
            })
            
            # 🔥 v5.3.0: 로컬 캐시 제거, 캐시 모듈 사용
            # (balance_cache, ticker_cache, markets_cache, ohlcv_cache는 글로벌 모듈)
            self._markets_loaded = False
            
            # Rate Limiter (분당 500 호출 제한)
            self.rate_limiter = RateLimiter(max_calls=500, per_seconds=60)
            
            # 마켓 정보 로드
            self._load_markets()

            logger.info("[CCXT] 빗썸 API 초기화 완료 (v5.3.0 - Phase A OHLCV 캐시 추가)")

        except Exception as e:
            logger.error(f"[CCXT INIT ERROR] {e}")
            raise
    
    # ---------------------------------------------------------
    # 마켓 정보 로드
    # ---------------------------------------------------------
    def _load_markets(self):
        """마켓 정보를 시작 시 1회만 로드"""
        if self._markets_loaded:
            return
        try:
            self.exchange.load_markets()
            self._markets_loaded = True
            logger.info(f"[CCXT] 마켓 정보 로드 완료: {len(self.exchange.markets)}개")
        except Exception as e:
            logger.error(f"[MARKETS LOAD ERROR] {e}")

    # ---------------------------------------------------------
    # 🔥 v5.3.0: 마켓 정밀도 로드 (캐시 모듈 사용)
    # ---------------------------------------------------------
    def _load_markets_precision(self, force: bool = False):
        """
        빗썸 마켓 정보에서 수량 정밀도 로드 (캐시 모듈 사용)
        """
        # 캐시 확인
        if not force:
            cached = markets_cache.get("precision_map")
            if cached is not None:
                return cached
        
        precision_map = {}
        
        try:
            self._load_markets()
            
            for sym, market in self.exchange.markets.items():
                if "/KRW" not in sym:
                    continue
                    
                coin = sym.replace("/KRW", "")
                
                # precision.amount 우선
                precision = market.get("precision", {})
                amount_prec = precision.get("amount")
                
                if amount_prec is not None and amount_prec >= 0:
                    precision_map[coin] = int(amount_prec)
                else:
                    # 가격 기반 폴백
                    last_price = market.get("info", {}).get("closing_price")
                    if last_price:
                        try:
                            price = float(last_price)
                            precision_map[coin] = _get_qty_precision_by_price(price)
                        except:
                            precision_map[coin] = 4  # 기본값
                    else:
                        precision_map[coin] = 4
            
            # 캐시에 저장
            markets_cache.set("precision_map", precision_map, self.MARKETS_CACHE_TTL)
            
            logger.debug(f"[PRECISION] 마켓 정밀도 로드: {len(precision_map)}개")
            return precision_map
            
        except Exception as e:
            logger.error(f"[PRECISION LOAD ERROR] {e}")
            return precision_map
    
    def get_precision_for_coin(self, coin: str) -> Optional[int]:
        """특정 코인의 수량 정밀도 조회"""
        precision_map = self._load_markets_precision()
        return precision_map.get(coin.upper())
    
    def get_precision_cache(self) -> Dict[str, int]:
        """정밀도 캐시 전체 반환"""
        return self._load_markets_precision()
    
    # ---------------------------------------------------------
    # Rate Limit 체크
    # ---------------------------------------------------------
    def _check_rate_limit(self):
        """Rate limit 확인 및 대기"""
        self.rate_limiter.acquire(wait=True)

    # ---------------------------------------------------------
    # Balance (캐시 모듈 사용)
    # ---------------------------------------------------------
    def fetch_balance(self, force: bool = False) -> dict:
        """
        잔고 조회 (캐시 모듈 사용)
        
        Args:
            force: True면 캐시 무시
        """
        # 캐시 확인
        if not force:
            cached = balance_cache.get("balance")
            if cached is not None:
                return cached
        
        self._check_rate_limit()
        
        try:
            raw = self.exchange.fetch_balance()
            result = {}
            
            for currency, data in raw.items():
                if isinstance(data, dict) and data.get("total", 0) > 0:
                    result[currency] = {
                        "free": data.get("free", 0),
                        "used": data.get("used", 0),
                        "total": data.get("total", 0),
                    }
            
            # 캐시에 저장
            balance_cache.set("balance", result, self.BALANCE_CACHE_TTL)
            
            return result
            
        except Exception as e:
            logger.error(f"[BALANCE ERROR] {e}")
            return {}
    
    def invalidate_balance_cache(self):
        """잔고 캐시 무효화"""
        balance_cache.delete("balance")
    
    def get_krw_balance(self, force: bool = False) -> float:
        """KRW 잔고 조회"""
        bal = self.fetch_balance(force=force)
        return bal.get("KRW", {}).get("free", 0)

    # ---------------------------------------------------------
    # Ticker (캐시 모듈 사용)
    # ---------------------------------------------------------
    def fetch_ticker(self, symbol: str, force: bool = False) -> dict:
        """
        티커 조회 (캐시 모듈 사용)
        
        Args:
            symbol: 심볼 (예: "BTC/KRW")
            force: True면 캐시 무시
        """
        symbol = convert_symbol(symbol)
        cache_key = f"ticker:{symbol}"
        
        # 캐시 확인
        if not force:
            cached = ticker_cache.get(cache_key)
            if cached is not None:
                return cached
        
        self._check_rate_limit()
        
        try:
            ticker = self.exchange.fetch_ticker(symbol)
            
            # 캐시에 저장
            ticker_cache.set(cache_key, ticker, self.TICKER_CACHE_TTL)
            
            return ticker
            
        except Exception as e:
            logger.error(f"[TICKER ERROR] {symbol}: {e}")
            return {}

    # ---------------------------------------------------------
    # Market Buy (Retry + Rate Limit + 동적 정밀도)
    # ---------------------------------------------------------
    @retry_with_backoff(max_retries=3, base_delay=1.0)
    def create_market_buy(self, symbol: str, krw_amount: float):
        """시장가 매수"""
        symbol = convert_symbol(symbol)

        if krw_amount < Config.MIN_ORDER_AMOUNT:
            raise ValueError(f"[BUY ERROR] 최소 주문 금액 미만: {krw_amount}")

        self._check_rate_limit()
        
        ticker = self.fetch_ticker(symbol, force=True)
        last = float(ticker["last"])
        
        # 심볼 기반 동적 정밀도 조회
        raw_qty = krw_amount / last
        qty = round_qty(raw_qty, symbol, direction="down")
        precision = get_qty_precision(symbol, last)
        
        if qty <= 0:
            raise ValueError(f"[BUY ERROR] 수량 0 이하: {symbol} qty={qty}")

        logger.info(f"[BUY] {symbol}: KRW={krw_amount:,.0f}, last={last:,.4f}, qty={qty} (precision={precision})")

        order = self.exchange.create_order(
            symbol=symbol,
            type="market",
            side="buy",
            amount=qty,
        )
        
        self.invalidate_balance_cache()
        return order

    def create_market_buy_krw(self, symbol: str, krw_amount: float):
        """create_market_buy alias"""
        return self.create_market_buy(symbol, krw_amount)

    # ---------------------------------------------------------
    # Market Sell (Retry + Rate Limit + 동적 정밀도)
    # ---------------------------------------------------------
    @retry_with_backoff(max_retries=3, base_delay=1.0)
    def create_market_sell(self, symbol: str, qty: float):
        """시장가 매도"""
        symbol = convert_symbol(symbol)

        if qty <= 0:
            raise ValueError(f"[SELL ERROR] qty <= 0: {qty}")

        self._check_rate_limit()
        
        # 심볼 기반 동적 정밀도 조회
        ticker = self.fetch_ticker(symbol, force=True)
        last = float(ticker["last"])
        qty = round_qty(qty, symbol, direction="down")
        precision = get_qty_precision(symbol, last)
        
        if qty <= 0:
            raise ValueError(f"[SELL ERROR] 수량 0 이하 (반올림 후): {symbol} qty={qty}")
        
        logger.info(f"[SELL] {symbol}: qty={qty} (precision={precision})")

        order = self.exchange.create_order(
            symbol=symbol,
            type="market",
            side="sell",
            amount=qty
        )
        
        self.invalidate_balance_cache()
        return order

    # ---------------------------------------------------------
    # Limit Buy (재시도 로직 + 동적 정밀도)
    # ---------------------------------------------------------
    @retry_with_backoff(max_retries=5, base_delay=1.0, max_delay=16.0)
    def create_limit_buy(self, symbol: str, krw_amount: float, slippage: float = 0.003):
        """공격적 지정가 매수 (틱 사이즈 + 동적 정밀도 + 재시도)"""
        symbol = convert_symbol(symbol)
        
        self._check_rate_limit()
        
        ticker = self.fetch_ticker(symbol, force=True)
        current_price = ticker.get("last", 0)
        if current_price <= 0:
            raise ValueError(f"[LIMIT BUY] 가격 조회 실패: {symbol}")
        
        # 틱 사이즈에 맞게 올림 (매수는 높게)
        raw_price = current_price * (1 + slippage)
        limit_price = round_to_tick(raw_price, direction="up")
        
        # 심볼 기반 동적 정밀도 조회
        raw_qty = krw_amount / limit_price
        qty = round_qty(raw_qty, symbol, direction="down")
        precision = get_qty_precision(symbol, current_price)
        
        # 최소 수량 체크
        if qty <= 0:
            raise ValueError(f"[LIMIT BUY] 수량 0 이하: {symbol} qty={qty}")
        
        logger.info(f"[LIMIT BUY] {symbol} 현재가={current_price:,.4f} 지정가={limit_price:,.4f} 수량={qty} (precision={precision})")
        
        order = self.exchange.create_limit_buy_order(symbol, qty, limit_price)
        logger.info(f"[LIMIT BUY OK] {symbol} order_id={order.get('id', 'N/A')}")
        
        self.invalidate_balance_cache()
        return order

    # ---------------------------------------------------------
    # Limit Sell (재시도 로직 + 동적 정밀도)
    # ---------------------------------------------------------
    @retry_with_backoff(max_retries=5, base_delay=1.0, max_delay=16.0)
    def create_limit_sell(self, symbol: str, qty: float, slippage: float = 0.003):
        """공격적 지정가 매도 (틱 사이즈 + 동적 정밀도 + 재시도)"""
        symbol = convert_symbol(symbol)
        
        self._check_rate_limit()
        
        ticker = self.fetch_ticker(symbol, force=True)
        current_price = ticker.get("last", 0)
        if current_price <= 0:
            raise ValueError(f"[LIMIT SELL] 가격 조회 실패: {symbol}")
        
        # 틱 사이즈에 맞게 내림 (매도는 낮게)
        raw_price = current_price * (1 - slippage)
        limit_price = round_to_tick(raw_price, direction="down")
        
        # 최소 가격 체크
        if limit_price <= 0:
            raise ValueError(f"[LIMIT SELL] 가격 0 이하: {symbol} price={limit_price}")
        
        # 심볼 기반 동적 정밀도 조회
        qty = round_qty(qty, symbol, direction="down")
        precision = get_qty_precision(symbol, current_price)
        
        if qty <= 0:
            raise ValueError(f"[LIMIT SELL] 수량 0 이하: {symbol} qty={qty}")
        
        logger.info(f"[LIMIT SELL] {symbol} 현재가={current_price:,.4f} 지정가={limit_price:,.4f} 수량={qty} (precision={precision})")
        
        order = self.exchange.create_limit_sell_order(symbol, qty, limit_price)
        logger.info(f"[LIMIT SELL OK] {symbol} order_id={order.get('id', 'N/A')}")
        
        self.invalidate_balance_cache()
        return order

    # ---------------------------------------------------------
    # 실제 잔고 기반 안전 매도
    # ---------------------------------------------------------
    def create_limit_sell_safe(self, symbol: str, slippage: float = 0.003):
        """
        실제 보유량 기반 안전 매도
        
        - 매도 전 실제 잔고 조회
        - 보유량 전체 매도
        - 5회 재시도 (지수 백오프)
        """
        symbol = convert_symbol(symbol)
        coin = symbol.replace("/KRW", "")
        
        # 1. 실제 보유량 조회
        bal = self.fetch_balance(force=True)  # 캐시 무효화하고 조회
        actual_qty = bal.get(coin, {}).get("total", 0)
        
        if actual_qty <= 0:
            logger.warning(f"[LIMIT SELL SAFE] {symbol} 보유량 없음")
            return None
        
        logger.info(f"[LIMIT SELL SAFE] {symbol} 실제 보유량: {actual_qty}")
        
        # 2. 재시도 로직이 적용된 매도 실행
        return self.create_limit_sell(symbol, actual_qty, slippage)

    # ---------------------------------------------------------
    # 🆕 v5.3.0 Phase A: OHLCV (캐시 적용)
    # ---------------------------------------------------------
    def fetch_ohlcv(self, symbol, timeframe="30m", limit=200, force: bool = False):
        """
        OHLCV 조회 (v5.3.0 Phase A: 캐시 적용)
        
        Args:
            symbol: 심볼
            timeframe: 타임프레임 (기본 30m)
            limit: 캔들 수 (기본 200)
            force: True면 캐시 무시
            
        Returns:
            pd.DataFrame (timestamp, open, high, low, close, volume)
        """
        symbol = convert_symbol(symbol)
        cache_key = f"ohlcv:{symbol}:{timeframe}:{limit}"
        
        # 🆕 캐시 확인
        if not force:
            cached = ohlcv_cache.get(cache_key)
            if cached is not None:
                logger.debug(f"[OHLCV] {symbol} {timeframe} 캐시 히트")
                return cached
        
        self._check_rate_limit()
        
        try:
            raw = self.exchange.fetch_ohlcv(symbol, timeframe=timeframe, limit=limit)

            if not raw:
                return pd.DataFrame()

            df = pd.DataFrame(
                raw,
                columns=["timestamp", "open", "high", "low", "close", "volume"]
            )
            df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms")
            df = df.set_index("timestamp")
            
            # 🆕 캐시에 저장
            ohlcv_cache.set(cache_key, df, self.OHLCV_CACHE_TTL)
            logger.debug(f"[OHLCV] {symbol} {timeframe} 캐시 저장 (TTL={self.OHLCV_CACHE_TTL}s)")

            return df

        except Exception as e:
            logger.error(f"[OHLCV ERROR] {symbol} {e}")
            return pd.DataFrame()

    # ---------------------------------------------------------
    # Rate Limit 통계 조회
    # ---------------------------------------------------------
    def get_rate_limit_stats(self) -> Dict:
        """Rate limit 통계"""
        return self.rate_limiter.get_stats()
    
    def get_rate_limit_status(self) -> str:
        """텔레그램용 Rate limit 상태"""
        stats = self.rate_limiter.get_stats()
        return (
            f"📊 <b>Rate Limit 상태</b>\n\n"
            f"남은 호출: {stats['remaining']}/{stats['max_calls']}\n"
            f"총 호출: {stats['total_calls']:,}회\n"
            f"차단됨: {stats['blocked_calls']}회\n"
            f"Rate Limit 도달: {stats['rate_limit_hits']}회"
        )
    
    # ---------------------------------------------------------
    # 🆕 v5.3.0 Phase A: 캐시 통계 조회 (OHLCV 추가)
    # ---------------------------------------------------------
    def get_cache_stats(self) -> Dict:
        """캐시 통계 조회"""
        return {
            "balance_cache": balance_cache.stats(),
            "ticker_cache": ticker_cache.stats(),
            "markets_cache": markets_cache.stats(),
            "ohlcv_cache": ohlcv_cache.stats(),  # 🆕 추가
        }
    
    # ---------------------------------------------------------
    # 정밀도 상태 조회 (텔레그램용)
    # ---------------------------------------------------------
    def get_precision_status(self) -> str:
        """텔레그램용 정밀도 캐시 상태"""
        precision_map = self.get_precision_cache()
        cache_stats = markets_cache.stats()
        
        lines = ["📐 <b>수량 정밀도 캐시 (v5.3.0 Phase A)</b>\n"]
        
        # 캐시 통계
        lines.append(f"캐시 코인 수: {len(precision_map)}개")
        lines.append(f"캐시 히트율: {cache_stats.get('hit_rate', '0%')}")
        lines.append("")
        
        # 일부 코인 샘플
        sample_coins = list(precision_map.items())[:10]
        if sample_coins:
            lines.append("<b>샘플 (10개):</b>")
            for coin, precision in sample_coins:
                lines.append(f"  {coin}: {precision}자리")
        
        return "\n".join(lines)


# ---------------------------------------------------------
# Singleton
# ---------------------------------------------------------
_api_instance = None

def get_api():
    global _api_instance
    if _api_instance is None:
        _api_instance = BithumbAPI()
    return _api_instance
