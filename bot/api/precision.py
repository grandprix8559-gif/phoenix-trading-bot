# -*- coding: utf-8 -*-
"""
Phoenix v5.3.0 — 가격/수량 정밀도 유틸리티

빗썸 거래소의 가격 및 수량 정밀도 처리를 담당합니다.

🔥 v5.3.0:
- bithumb_ccxt_api.py에서 분리
- 틱 사이즈, 수량 정밀도 함수
- 동적 정밀도 조회 지원
"""

import math
from typing import Dict, Optional, Union, Callable
from dataclasses import dataclass

from bot.utils.logger import get_logger

logger = get_logger("API.Precision")


# =========================================================
# 상수 정의
# =========================================================

# 수동 오버라이드 테이블 (빗썸 마켓 정보가 부정확한 경우)
COIN_QTY_PRECISION: Dict[str, int] = {
    # 예: "SPECIAL_COIN": 3,
}


# =========================================================
# 틱 사이즈 (가격 단위)
# =========================================================

@dataclass
class TickSizeRule:
    """틱 사이즈 규칙"""
    min_price: float
    tick_size: float


# 빗썸 호가 단위 규칙
BITHUMB_TICK_RULES = [
    TickSizeRule(1_000_000, 1000),    # 100만원 이상: 1,000원
    TickSizeRule(100_000, 100),       # 10만원 이상: 100원
    TickSizeRule(10_000, 10),         # 1만원 이상: 10원
    TickSizeRule(1_000, 1),           # 1,000원 이상: 1원
    TickSizeRule(100, 0.1),           # 100원 이상: 0.1원
    TickSizeRule(10, 0.01),           # 10원 이상: 0.01원
    TickSizeRule(0, 0.001),           # 10원 미만: 0.001원
]


def get_tick_size(price: float) -> float:
    """
    빗썸 가격대별 틱 사이즈 반환
    
    Args:
        price: 현재 가격
        
    Returns:
        틱 사이즈 (호가 단위)
    """
    if price <= 0:
        return 0.001
    
    for rule in BITHUMB_TICK_RULES:
        if price >= rule.min_price:
            return rule.tick_size
    
    return 0.001


def round_to_tick(
    price: float, 
    direction: str = "nearest"
) -> float:
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


def format_price(price: float) -> str:
    """
    가격을 읽기 좋은 형식으로 포맷
    
    Args:
        price: 가격
        
    Returns:
        포맷된 문자열
    """
    if price >= 1000:
        return f"{price:,.0f}"
    elif price >= 1:
        return f"{price:,.2f}"
    else:
        return f"{price:.4f}"


# =========================================================
# 수량 정밀도
# =========================================================

def get_qty_precision_by_price(price: float) -> int:
    """
    가격 기반 수량 정밀도 추정
    
    빗썸 수량 규칙 (추정):
    - 1천원 이상: 소수점 4자리
    - 100원 이상: 소수점 2자리 (KAIA, SHIB 등)
    - 10원 이상: 소수점 1자리
    - 10원 미만: 정수만 (BONK 등 초저가)
    
    Args:
        price: 코인 현재가
        
    Returns:
        허용 소수점 자릿수
    """
    if price >= 1000:
        return 4
    elif price >= 100:
        return 2
    elif price >= 10:
        return 1
    else:
        return 0


# 동적 정밀도 조회용 전역 참조
_precision_fetcher: Optional[object] = None


def set_precision_fetcher(api_instance: object) -> None:
    """
    API 인스턴스 설정 (main.py에서 호출)
    
    Args:
        api_instance: BithumbAPI 인스턴스 (동적 정밀도 조회용)
    """
    global _precision_fetcher
    _precision_fetcher = api_instance
    logger.info("[Precision] 동적 정밀도 조회기 설정 완료")


def get_qty_precision(
    symbol_or_price: Union[str, float],
    price: Optional[float] = None
) -> int:
    """
    동적 수량 정밀도 조회
    
    조회 순서:
    1. COIN_QTY_PRECISION 테이블 (수동 오버라이드)
    2. 빗썸 마켓 정보 (동적 조회)
    3. 가격 기반 폴백
    
    Args:
        symbol_or_price: 심볼 문자열 (예: "BTC/KRW", "BTC") 또는 가격
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
            logger.debug(f"[Precision] {coin} → {COIN_QTY_PRECISION[coin]} (수동 테이블)")
            return COIN_QTY_PRECISION[coin]
        
        # 2️⃣ 빗썸 마켓 정보에서 동적 조회
        if _precision_fetcher is not None:
            try:
                # API 인스턴스의 _load_markets_precision 호출
                if hasattr(_precision_fetcher, '_load_markets_precision'):
                    _precision_fetcher._load_markets_precision()
                
                if hasattr(_precision_fetcher, '_markets_precision_cache'):
                    cache = _precision_fetcher._markets_precision_cache
                    if coin in cache:
                        precision = cache[coin]
                        logger.debug(f"[Precision] {coin} → {precision} (동적 조회)")
                        return precision
            except Exception as e:
                logger.warning(f"[Precision] 동적 조회 실패: {e}")
        
        # 3️⃣ 가격 기반 폴백
        if price is not None and price > 0:
            fallback = get_qty_precision_by_price(price)
            logger.debug(f"[Precision] {coin} → {fallback} (가격 기반 폴백, price={price:.4f})")
            return fallback
        
        # 4️⃣ 최종 기본값 (보수적으로 4 사용)
        logger.warning(f"[Precision] {coin} 정밀도 미정의 → 기본값 4 사용")
        return 4
    
    # 숫자인 경우 (후방호환성 유지)
    elif isinstance(symbol_or_price, (int, float)):
        return get_qty_precision_by_price(symbol_or_price)
    
    return 4  # 안전한 기본값


def round_qty(
    qty: float,
    price_or_symbol: Union[str, float],
    direction: str = "down"
) -> float:
    """
    수량을 가격대/심볼에 맞게 반올림
    
    Args:
        qty: 원본 수량
        price_or_symbol: 코인 현재가 또는 심볼 (정밀도 결정용)
        direction: "down" (내림, 기본값), "up" (올림), "nearest" (반올림)
        
    Returns:
        정밀도에 맞춘 수량
    """
    precision = get_qty_precision(price_or_symbol)
    factor = 10 ** precision
    
    if direction == "down":
        return math.floor(qty * factor) / factor
    elif direction == "up":
        return math.ceil(qty * factor) / factor
    else:
        return round(qty, precision)


def format_qty(qty: float, symbol: str = "") -> str:
    """
    수량을 읽기 좋은 형식으로 포맷
    
    Args:
        qty: 수량
        symbol: 심볼 (정밀도 결정용)
        
    Returns:
        포맷된 문자열
    """
    if symbol:
        precision = get_qty_precision(symbol)
    else:
        precision = 4
    
    return f"{qty:.{precision}f}"


# =========================================================
# 심볼 유틸리티
# =========================================================

def convert_symbol(sym: str) -> str:
    """
    심볼 포맷 변환 (CCXT 형식으로)
    
    Args:
        sym: 원본 심볼 (SOL, SOL-KRW, sol/krw 등)
        
    Returns:
        정규화된 심볼 (SOL/KRW)
    """
    sym = sym.replace("-", "/").upper()
    if "/KRW" not in sym:
        sym = sym.split("/")[0] + "/KRW"
    return sym


def extract_coin(symbol: str) -> str:
    """
    심볼에서 코인 추출
    
    Args:
        symbol: 심볼 (SOL/KRW)
        
    Returns:
        코인 (SOL)
    """
    return symbol.replace("/KRW", "").replace("-KRW", "").upper()


# =========================================================
# 주문 검증
# =========================================================

def validate_order_params(
    symbol: str,
    price: float,
    qty: float,
    min_order_amount: float = 5000,
) -> tuple:
    """
    주문 파라미터 검증
    
    Args:
        symbol: 심볼
        price: 가격
        qty: 수량
        min_order_amount: 최소 주문 금액 (KRW)
        
    Returns:
        (유효 여부, 오류 메시지)
    """
    if price <= 0:
        return (False, f"가격 0 이하: {price}")
    
    if qty <= 0:
        return (False, f"수량 0 이하: {qty}")
    
    order_amount = price * qty
    if order_amount < min_order_amount:
        return (False, f"최소 주문금액 미달: {order_amount:,.0f} < {min_order_amount:,.0f}")
    
    return (True, "")


def prepare_buy_order(
    symbol: str,
    krw_amount: float,
    current_price: float,
    slippage: float = 0.0,
    min_order_amount: float = 5000,
) -> Dict:
    """
    매수 주문 파라미터 준비
    
    Args:
        symbol: 심볼
        krw_amount: 주문 금액 (KRW)
        current_price: 현재 가격
        slippage: 슬리피지 (0.003 = 0.3%)
        min_order_amount: 최소 주문 금액
        
    Returns:
        {
            "valid": bool,
            "symbol": str,
            "price": float,
            "qty": float,
            "precision": int,
            "error": str (오류 시)
        }
    """
    symbol = convert_symbol(symbol)
    
    if krw_amount < min_order_amount:
        return {
            "valid": False,
            "error": f"최소 주문 금액 미달: {krw_amount:,.0f} < {min_order_amount:,.0f}"
        }
    
    # 가격 계산 (슬리피지 적용, 올림)
    if slippage > 0:
        raw_price = current_price * (1 + slippage)
        price = round_to_tick(raw_price, direction="up")
    else:
        price = current_price
    
    # 수량 계산 (내림)
    raw_qty = krw_amount / price
    qty = round_qty(raw_qty, symbol, direction="down")
    precision = get_qty_precision(symbol, price)
    
    if qty <= 0:
        return {
            "valid": False,
            "error": f"수량 0 이하: {raw_qty} → {qty}"
        }
    
    return {
        "valid": True,
        "symbol": symbol,
        "price": price,
        "qty": qty,
        "precision": precision,
        "order_amount": price * qty,
    }


def prepare_sell_order(
    symbol: str,
    qty: float,
    current_price: float,
    slippage: float = 0.0,
) -> Dict:
    """
    매도 주문 파라미터 준비
    
    Args:
        symbol: 심볼
        qty: 매도 수량
        current_price: 현재 가격
        slippage: 슬리피지 (0.003 = 0.3%)
        
    Returns:
        {
            "valid": bool,
            "symbol": str,
            "price": float,
            "qty": float,
            "precision": int,
            "error": str (오류 시)
        }
    """
    symbol = convert_symbol(symbol)
    
    # 가격 계산 (슬리피지 적용, 내림)
    if slippage > 0:
        raw_price = current_price * (1 - slippage)
        price = round_to_tick(raw_price, direction="down")
    else:
        price = current_price
    
    # 수량 정밀도 적용 (내림)
    qty = round_qty(qty, symbol, direction="down")
    precision = get_qty_precision(symbol, price)
    
    if qty <= 0:
        return {
            "valid": False,
            "error": f"수량 0 이하: {qty}"
        }
    
    if price <= 0:
        return {
            "valid": False,
            "error": f"가격 0 이하: {price}"
        }
    
    return {
        "valid": True,
        "symbol": symbol,
        "price": price,
        "qty": qty,
        "precision": precision,
        "order_amount": price * qty,
    }
