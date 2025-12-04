# -*- coding: utf-8 -*-
"""
Phoenix v5.3.0 — 커스텀 예외 클래스

에러 타입별 분류 및 처리
- 계층적 예외 구조
- 에러 코드 및 상세 정보
- 직렬화 지원
"""

from typing import Dict, Any, Optional
from dataclasses import dataclass, field


# =========================================================
# 기본 예외 클래스
# =========================================================

class PhoenixBaseException(Exception):
    """Phoenix 기본 예외"""
    
    def __init__(
        self, 
        message: str, 
        code: str = None, 
        details: Dict[str, Any] = None,
        recoverable: bool = True,
    ):
        """
        Args:
            message: 에러 메시지
            code: 에러 코드
            details: 추가 상세 정보
            recoverable: 복구 가능 여부
        """
        super().__init__(message)
        self.message = message
        self.code = code or "UNKNOWN"
        self.details = details or {}
        self.recoverable = recoverable
    
    def to_dict(self) -> Dict[str, Any]:
        """딕셔너리로 변환"""
        return {
            "error": self.__class__.__name__,
            "code": self.code,
            "message": self.message,
            "details": self.details,
            "recoverable": self.recoverable,
        }
    
    def __str__(self) -> str:
        return f"[{self.code}] {self.message}"
    
    def __repr__(self) -> str:
        return f"{self.__class__.__name__}(code={self.code!r}, message={self.message!r})"


# =========================================================
# API 관련 예외
# =========================================================

class APIException(PhoenixBaseException):
    """API 호출 예외 (기본)"""
    pass


class RateLimitException(APIException):
    """Rate Limit 초과"""
    
    def __init__(self, retry_after: int = 60):
        super().__init__(
            message=f"Rate limit 초과. {retry_after}초 후 재시도",
            code="RATE_LIMIT",
            details={"retry_after": retry_after},
            recoverable=True,
        )
        self.retry_after = retry_after


class ConnectionException(APIException):
    """연결 오류"""
    
    def __init__(self, endpoint: str = "", reason: str = ""):
        super().__init__(
            message=f"연결 실패: {endpoint} - {reason}",
            code="CONNECTION_ERROR",
            details={"endpoint": endpoint, "reason": reason},
            recoverable=True,
        )


class AuthenticationException(APIException):
    """인증 오류"""
    
    def __init__(self, reason: str = "Invalid API key"):
        super().__init__(
            message=f"인증 실패: {reason}",
            code="AUTH_ERROR",
            details={"reason": reason},
            recoverable=False,
        )


class InsufficientBalanceException(APIException):
    """잔고 부족"""
    
    def __init__(
        self, 
        required: float, 
        available: float, 
        currency: str = "KRW"
    ):
        super().__init__(
            message=f"잔고 부족 ({currency}): 필요 {required:,.0f}, 보유 {available:,.0f}",
            code="INSUFFICIENT_BALANCE",
            details={
                "required": required, 
                "available": available, 
                "currency": currency,
                "shortage": required - available,
            },
            recoverable=False,
        )
        self.required = required
        self.available = available
        self.currency = currency


class OrderFailedException(APIException):
    """주문 실패"""
    
    def __init__(
        self, 
        symbol: str, 
        side: str, 
        reason: str,
        order_id: str = None,
    ):
        super().__init__(
            message=f"주문 실패: {symbol} {side} - {reason}",
            code="ORDER_FAILED",
            details={
                "symbol": symbol, 
                "side": side, 
                "reason": reason,
                "order_id": order_id,
            },
            recoverable=True,
        )
        self.symbol = symbol
        self.side = side


class InvalidQuantityException(APIException):
    """수량 오류"""
    
    def __init__(
        self, 
        symbol: str, 
        quantity: float, 
        reason: str,
        min_qty: float = None,
        max_qty: float = None,
    ):
        details = {
            "symbol": symbol, 
            "quantity": quantity, 
            "reason": reason,
        }
        if min_qty is not None:
            details["min_qty"] = min_qty
        if max_qty is not None:
            details["max_qty"] = max_qty
            
        super().__init__(
            message=f"잘못된 수량 ({symbol}): {quantity} - {reason}",
            code="INVALID_QUANTITY",
            details=details,
            recoverable=False,
        )
        self.symbol = symbol
        self.quantity = quantity


class InvalidPriceException(APIException):
    """가격 오류"""
    
    def __init__(
        self, 
        symbol: str, 
        price: float, 
        reason: str,
    ):
        super().__init__(
            message=f"잘못된 가격 ({symbol}): {price} - {reason}",
            code="INVALID_PRICE",
            details={
                "symbol": symbol, 
                "price": price, 
                "reason": reason,
            },
            recoverable=False,
        )
        self.symbol = symbol
        self.price = price


# =========================================================
# 데이터 관련 예외
# =========================================================

class DataException(PhoenixBaseException):
    """데이터 처리 예외 (기본)"""
    pass


class OHLCVException(DataException):
    """OHLCV 데이터 오류"""
    
    def __init__(
        self, 
        symbol: str, 
        timeframe: str, 
        reason: str,
    ):
        super().__init__(
            message=f"OHLCV 오류 ({symbol} {timeframe}): {reason}",
            code="OHLCV_ERROR",
            details={
                "symbol": symbol, 
                "timeframe": timeframe, 
                "reason": reason,
            },
            recoverable=True,
        )
        self.symbol = symbol
        self.timeframe = timeframe


class IndicatorCalculationException(DataException):
    """지표 계산 오류"""
    
    def __init__(
        self, 
        indicator: str, 
        reason: str,
        symbol: str = None,
    ):
        details = {"indicator": indicator, "reason": reason}
        if symbol:
            details["symbol"] = symbol
            
        super().__init__(
            message=f"지표 계산 실패 ({indicator}): {reason}",
            code="INDICATOR_ERROR",
            details=details,
            recoverable=True,
        )
        self.indicator = indicator


class JSONParseException(DataException):
    """JSON 파싱 오류"""
    
    def __init__(
        self, 
        source: str = "unknown", 
        raw_data: str = None,
    ):
        super().__init__(
            message=f"JSON 파싱 실패: {source}",
            code="JSON_PARSE_ERROR",
            details={
                "source": source,
                "raw_data": raw_data[:200] if raw_data else None,
            },
            recoverable=True,
        )


class ValidationException(DataException):
    """데이터 검증 오류"""
    
    def __init__(
        self, 
        field: str, 
        value: Any, 
        reason: str,
    ):
        super().__init__(
            message=f"검증 실패 ({field}): {reason}",
            code="VALIDATION_ERROR",
            details={
                "field": field,
                "value": str(value)[:100] if value else None,
                "reason": reason,
            },
            recoverable=False,
        )


# =========================================================
# AI 관련 예외
# =========================================================

class AIException(PhoenixBaseException):
    """AI 분석 예외 (기본)"""
    pass


class AIResponseParseException(AIException):
    """AI 응답 파싱 실패"""
    
    def __init__(
        self, 
        raw_response: str = None,
        expected_format: str = "JSON",
    ):
        super().__init__(
            message="AI 응답 파싱 실패",
            code="AI_PARSE_ERROR",
            details={
                "raw_response": raw_response[:300] if raw_response else None,
                "expected_format": expected_format,
            },
            recoverable=True,
        )


class AITimeoutException(AIException):
    """AI 응답 타임아웃"""
    
    def __init__(self, timeout_sec: int):
        super().__init__(
            message=f"AI 응답 타임아웃 ({timeout_sec}초)",
            code="AI_TIMEOUT",
            details={"timeout_sec": timeout_sec},
            recoverable=True,
        )
        self.timeout_sec = timeout_sec


class AIQuotaExceededException(AIException):
    """AI API 할당량 초과"""
    
    def __init__(self, reason: str = ""):
        super().__init__(
            message=f"AI API 할당량 초과: {reason}",
            code="AI_QUOTA_EXCEEDED",
            details={"reason": reason},
            recoverable=False,
        )


class AIInvalidResponseException(AIException):
    """AI 응답 형식 오류"""
    
    def __init__(
        self, 
        missing_fields: list = None,
        invalid_fields: dict = None,
    ):
        super().__init__(
            message="AI 응답 형식 오류",
            code="AI_INVALID_RESPONSE",
            details={
                "missing_fields": missing_fields or [],
                "invalid_fields": invalid_fields or {},
            },
            recoverable=True,
        )


# =========================================================
# 포지션 관련 예외
# =========================================================

class PositionException(PhoenixBaseException):
    """포지션 관리 예외 (기본)"""
    pass


class PositionNotFound(PositionException):
    """포지션 없음"""
    
    def __init__(self, symbol: str):
        super().__init__(
            message=f"포지션 없음: {symbol}",
            code="POSITION_NOT_FOUND",
            details={"symbol": symbol},
            recoverable=True,
        )
        self.symbol = symbol


class PositionLimitExceeded(PositionException):
    """포지션 한도 초과"""
    
    def __init__(self, current: int, limit: int):
        super().__init__(
            message=f"포지션 한도 초과: {current}/{limit}",
            code="POSITION_LIMIT",
            details={"current": current, "limit": limit},
            recoverable=False,
        )
        self.current = current
        self.limit = limit


class PositionWeightExceeded(PositionException):
    """포지션 비중 초과"""
    
    def __init__(
        self, 
        symbol: str, 
        current_weight: float, 
        max_weight: float,
    ):
        super().__init__(
            message=f"포지션 비중 초과 ({symbol}): {current_weight:.1%} > {max_weight:.1%}",
            code="POSITION_WEIGHT_EXCEEDED",
            details={
                "symbol": symbol,
                "current_weight": current_weight,
                "max_weight": max_weight,
            },
            recoverable=False,
        )


class DCALimitExceeded(PositionException):
    """DCA 횟수 초과"""
    
    def __init__(
        self, 
        symbol: str, 
        current_count: int, 
        max_count: int,
    ):
        super().__init__(
            message=f"DCA 한도 초과 ({symbol}): {current_count}/{max_count}",
            code="DCA_LIMIT_EXCEEDED",
            details={
                "symbol": symbol,
                "current_count": current_count,
                "max_count": max_count,
            },
            recoverable=False,
        )


# =========================================================
# 리스크 관련 예외
# =========================================================

class RiskException(PhoenixBaseException):
    """리스크 관리 예외 (기본)"""
    pass


class DailyLossLimitException(RiskException):
    """일일 손실 한도 초과"""
    
    def __init__(self, current_loss: float, limit: float):
        super().__init__(
            message=f"일일 손실 한도 도달: {current_loss:.2%} (한도: {limit:.2%})",
            code="DAILY_LOSS_LIMIT",
            details={
                "current_loss": current_loss,
                "limit": limit,
            },
            recoverable=False,
        )
        self.current_loss = current_loss
        self.limit = limit


class DrawdownLimitException(RiskException):
    """드로우다운 한도 초과"""
    
    def __init__(self, current_dd: float, limit: float):
        super().__init__(
            message=f"드로우다운 한도 도달: {current_dd:.2%} (한도: {limit:.2%})",
            code="DRAWDOWN_LIMIT",
            details={
                "current_drawdown": current_dd,
                "limit": limit,
            },
            recoverable=False,
        )
        self.current_dd = current_dd
        self.limit = limit


class CircuitBreakerTriggered(RiskException):
    """서킷브레이커 발동"""
    
    def __init__(
        self, 
        reason: str, 
        resume_at: str = None,
    ):
        super().__init__(
            message=f"서킷브레이커 발동: {reason}",
            code="CIRCUIT_BREAKER",
            details={
                "reason": reason,
                "resume_at": resume_at,
            },
            recoverable=False,
        )


class MarketConditionException(RiskException):
    """시장 상황으로 인한 제한"""
    
    def __init__(
        self, 
        condition: str, 
        action_blocked: str,
    ):
        super().__init__(
            message=f"시장 상황 제한 ({condition}): {action_blocked} 불가",
            code="MARKET_CONDITION",
            details={
                "condition": condition,
                "action_blocked": action_blocked,
            },
            recoverable=True,
        )


# =========================================================
# 시스템 관련 예외
# =========================================================

class SystemException(PhoenixBaseException):
    """시스템 예외 (기본)"""
    pass


class ConfigurationException(SystemException):
    """설정 오류"""
    
    def __init__(self, config_key: str, reason: str):
        super().__init__(
            message=f"설정 오류 ({config_key}): {reason}",
            code="CONFIG_ERROR",
            details={
                "config_key": config_key,
                "reason": reason,
            },
            recoverable=False,
        )


class FileIOException(SystemException):
    """파일 I/O 오류"""
    
    def __init__(
        self, 
        filepath: str, 
        operation: str, 
        reason: str,
    ):
        super().__init__(
            message=f"파일 오류 ({operation}): {filepath} - {reason}",
            code="FILE_IO_ERROR",
            details={
                "filepath": filepath,
                "operation": operation,
                "reason": reason,
            },
            recoverable=True,
        )


class TelegramException(SystemException):
    """텔레그램 봇 오류"""
    
    def __init__(self, operation: str, reason: str):
        super().__init__(
            message=f"텔레그램 오류 ({operation}): {reason}",
            code="TELEGRAM_ERROR",
            details={
                "operation": operation,
                "reason": reason,
            },
            recoverable=True,
        )


# =========================================================
# 예외 유틸리티
# =========================================================

def is_recoverable(exception: Exception) -> bool:
    """복구 가능한 예외인지 확인"""
    if isinstance(exception, PhoenixBaseException):
        return exception.recoverable
    
    # 일반 예외는 타입으로 판단
    recoverable_types = (
        ConnectionError,
        TimeoutError,
        OSError,
    )
    return isinstance(exception, recoverable_types)


def get_error_code(exception: Exception) -> str:
    """예외의 에러 코드 추출"""
    if isinstance(exception, PhoenixBaseException):
        return exception.code
    return type(exception).__name__.upper()


def exception_to_dict(exception: Exception) -> Dict[str, Any]:
    """예외를 딕셔너리로 변환"""
    if isinstance(exception, PhoenixBaseException):
        return exception.to_dict()
    
    return {
        "error": type(exception).__name__,
        "code": get_error_code(exception),
        "message": str(exception),
        "details": {},
        "recoverable": is_recoverable(exception),
    }
