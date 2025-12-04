# -*- coding: utf-8 -*-
"""
Phoenix v5.3.0 — 중앙 에러 핸들러

모든 에러를 중앙에서 관리하고 알림

🔥 v5.3.0:
- 에러 기록 및 히스토리 관리
- 텔레그램 알림 통합
- 에러 타입별 통계
- 쿨다운 적용 (같은 에러 반복 알림 방지)
"""

import traceback
import threading
from typing import Optional, Callable, Dict, List, Any
from datetime import datetime
from dataclasses import dataclass, field
from collections import deque
from enum import Enum

from bot.utils.logger import get_logger

logger = get_logger("ErrorHandler")


# =========================================================
# 에러 심각도
# =========================================================

class ErrorSeverity(Enum):
    """에러 심각도"""
    DEBUG = "debug"
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"


# =========================================================
# 에러 컨텍스트
# =========================================================

@dataclass
class ErrorContext:
    """에러 컨텍스트 정보"""
    module: str = ""
    function: str = ""
    symbol: str = ""
    action: str = ""
    extra: Dict = field(default_factory=dict)
    
    def __str__(self) -> str:
        parts = []
        if self.module:
            parts.append(self.module)
        if self.function:
            parts.append(self.function)
        if self.symbol:
            parts.append(self.symbol)
        if self.action:
            parts.append(self.action)
        return ".".join(parts) if parts else "unknown"
    
    def to_dict(self) -> Dict:
        return {
            "module": self.module,
            "function": self.function,
            "symbol": self.symbol,
            "action": self.action,
            "extra": self.extra,
        }


# =========================================================
# 에러 기록
# =========================================================

@dataclass
class ErrorRecord:
    """에러 기록"""
    timestamp: datetime
    error_type: str
    code: str
    message: str
    details: Dict
    stack_trace: str
    severity: ErrorSeverity = ErrorSeverity.ERROR
    context: str = ""
    notified: bool = False
    
    def to_dict(self) -> Dict:
        return {
            "timestamp": self.timestamp.isoformat(),
            "error_type": self.error_type,
            "code": self.code,
            "message": self.message,
            "details": self.details,
            "severity": self.severity.value,
            "context": self.context,
            "notified": self.notified,
        }


# =========================================================
# Phoenix 기본 예외
# =========================================================

class PhoenixBaseException(Exception):
    """Phoenix 기본 예외"""
    
    def __init__(self, message: str, code: str = None, details: dict = None):
        super().__init__(message)
        self.message = message
        self.code = code or "UNKNOWN"
        self.details = details or {}
    
    def to_dict(self) -> dict:
        return {
            "error": self.__class__.__name__,
            "code": self.code,
            "message": self.message,
            "details": self.details,
        }


# API 관련 예외
class APIException(PhoenixBaseException):
    """API 호출 예외"""
    pass


class RateLimitException(APIException):
    """Rate Limit 초과"""
    def __init__(self, retry_after: int = 60):
        super().__init__(
            f"Rate limit exceeded. Retry after {retry_after}s",
            code="RATE_LIMIT",
            details={"retry_after": retry_after}
        )


class InsufficientBalanceException(APIException):
    """잔고 부족"""
    def __init__(self, required: float, available: float, currency: str = "KRW"):
        super().__init__(
            f"Insufficient {currency}: need {required:,.0f}, have {available:,.0f}",
            code="INSUFFICIENT_BALANCE",
            details={"required": required, "available": available, "currency": currency}
        )


class OrderFailedException(APIException):
    """주문 실패"""
    def __init__(self, symbol: str, side: str, reason: str):
        super().__init__(
            f"Order failed: {symbol} {side} - {reason}",
            code="ORDER_FAILED",
            details={"symbol": symbol, "side": side, "reason": reason}
        )


# 데이터 관련 예외
class DataException(PhoenixBaseException):
    """데이터 처리 예외"""
    pass


class OHLCVException(DataException):
    """OHLCV 데이터 오류"""
    def __init__(self, symbol: str, timeframe: str, reason: str):
        super().__init__(
            f"OHLCV error for {symbol} {timeframe}: {reason}",
            code="OHLCV_ERROR",
            details={"symbol": symbol, "timeframe": timeframe, "reason": reason}
        )


# AI 관련 예외
class AIException(PhoenixBaseException):
    """AI 분석 예외"""
    pass


class AIResponseParseException(AIException):
    """AI 응답 파싱 실패"""
    def __init__(self, raw_response: str = None):
        super().__init__(
            "Failed to parse AI response",
            code="AI_PARSE_ERROR",
            details={"raw_response": raw_response[:200] if raw_response else None}
        )


# 포지션 관련 예외
class PositionException(PhoenixBaseException):
    """포지션 관리 예외"""
    pass


class PositionNotFound(PositionException):
    """포지션 없음"""
    def __init__(self, symbol: str):
        super().__init__(
            f"Position not found: {symbol}",
            code="POSITION_NOT_FOUND",
            details={"symbol": symbol}
        )


# 리스크 관련 예외
class RiskException(PhoenixBaseException):
    """리스크 관리 예외"""
    pass


class DailyLossLimitException(RiskException):
    """일일 손실 한도 초과"""
    def __init__(self, current_loss: float, limit: float):
        super().__init__(
            f"Daily loss limit reached: {current_loss:.2%} (limit: {limit:.2%})",
            code="DAILY_LOSS_LIMIT",
            details={"current_loss": current_loss, "limit": limit}
        )


# =========================================================
# 중앙 에러 핸들러
# =========================================================

class ErrorHandler:
    """
    중앙 에러 핸들러 (싱글톤)
    
    모든 에러를 중앙에서 관리하고 알림합니다.
    """
    
    _instance = None
    _lock = threading.Lock()
    
    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialized = False
        return cls._instance
    
    def __init__(self):
        if self._initialized:
            return
        
        self.error_history: deque = deque(maxlen=100)
        self.notify_callback: Optional[Callable[[str], None]] = None
        self.error_counts: Dict[str, int] = {}
        self.last_notified: Dict[str, float] = {}
        self.notify_cooldown: int = 300  # 같은 에러 알림 쿨다운 (5분)
        
        self._initialized = True
        logger.info("[ErrorHandler v5.3.0] 초기화 완료")
    
    def set_notify_callback(self, callback: Callable[[str], None]):
        """
        알림 콜백 설정 (텔레그램 등)
        
        Args:
            callback: 메시지를 받아 전송하는 함수
        """
        self.notify_callback = callback
        logger.info("[ErrorHandler] 알림 콜백 설정됨")
    
    def handle(
        self,
        error: Exception,
        context: str = "",
        severity: ErrorSeverity = ErrorSeverity.ERROR,
        notify: bool = True,
        reraise: bool = False,
    ) -> Optional[ErrorRecord]:
        """
        에러 처리
        
        Args:
            error: 발생한 예외
            context: 에러 컨텍스트 (어디서 발생했는지)
            severity: 에러 심각도
            notify: 알림 발송 여부
            reraise: 예외 재발생 여부
            
        Returns:
            에러 기록 또는 None
        """
        now = datetime.now()
        
        # 에러 정보 추출
        if isinstance(error, PhoenixBaseException):
            error_type = error.__class__.__name__
            code = error.code
            message = error.message
            details = error.details
        else:
            error_type = error.__class__.__name__
            code = "UNKNOWN"
            message = str(error)
            details = {}
        
        stack_trace = traceback.format_exc()
        
        # 기록 생성
        record = ErrorRecord(
            timestamp=now,
            error_type=error_type,
            code=code,
            message=message,
            details=details,
            stack_trace=stack_trace,
            severity=severity,
            context=context,
        )
        
        self.error_history.append(record)
        
        # 카운트 증가
        key = f"{error_type}:{code}"
        self.error_counts[key] = self.error_counts.get(key, 0) + 1
        
        # 로깅
        log_msg = f"[{context}] {error_type}({code}): {message}"
        
        if severity == ErrorSeverity.CRITICAL:
            logger.critical(log_msg)
        elif severity == ErrorSeverity.ERROR:
            logger.error(log_msg)
        elif severity == ErrorSeverity.WARNING:
            logger.warning(log_msg)
        else:
            logger.info(log_msg)
        
        logger.debug(f"Stack trace:\n{stack_trace}")
        
        # 알림 (쿨다운 체크)
        if notify and self.notify_callback and severity in [ErrorSeverity.ERROR, ErrorSeverity.CRITICAL]:
            last_time = self.last_notified.get(key, 0)
            if now.timestamp() - last_time >= self.notify_cooldown:
                self._send_notification(record, context)
                self.last_notified[key] = now.timestamp()
                record.notified = True
        
        if reraise:
            raise error
        
        return record
    
    def _send_notification(self, record: ErrorRecord, context: str):
        """알림 발송"""
        if not self.notify_callback:
            return
        
        try:
            severity_emoji = {
                ErrorSeverity.CRITICAL: "🚨",
                ErrorSeverity.ERROR: "❌",
                ErrorSeverity.WARNING: "⚠️",
                ErrorSeverity.INFO: "ℹ️",
                ErrorSeverity.DEBUG: "🔍",
            }
            
            emoji = severity_emoji.get(record.severity, "❌")
            
            msg = (
                f"{emoji} <b>에러 발생</b>\n\n"
                f"<b>컨텍스트:</b> {context}\n"
                f"<b>타입:</b> {record.error_type}\n"
                f"<b>코드:</b> {record.code}\n"
                f"<b>메시지:</b> {record.message}\n"
                f"<b>시간:</b> {record.timestamp.strftime('%H:%M:%S')}"
            )
            
            if record.details:
                details_str = ", ".join(f"{k}={v}" for k, v in record.details.items())
                msg += f"\n<b>상세:</b> {details_str}"
            
            self.notify_callback(msg)
        except Exception as e:
            logger.error(f"알림 발송 실패: {e}")
    
    def get_stats(self) -> Dict:
        """에러 통계"""
        return {
            "total_errors": len(self.error_history),
            "error_counts": dict(self.error_counts),
            "recent_errors": [
                {
                    "type": r.error_type,
                    "code": r.code,
                    "message": r.message[:100],
                    "time": r.timestamp.strftime("%H:%M:%S"),
                    "context": r.context,
                }
                for r in list(self.error_history)[-10:]
            ],
        }
    
    def get_summary(self) -> str:
        """통계 요약 문자열"""
        total = len(self.error_history)
        if total == 0:
            return "에러 없음"
        
        # 최근 1시간 에러 수
        now = datetime.now()
        recent = sum(
            1 for r in self.error_history 
            if (now - r.timestamp).total_seconds() < 3600
        )
        
        return f"총 {total}건 (최근 1시간: {recent}건)"
    
    def clear(self):
        """에러 기록 초기화"""
        self.error_history.clear()
        self.error_counts.clear()
        self.last_notified.clear()
        logger.info("[ErrorHandler] 에러 기록 초기화됨")


# =========================================================
# 글로벌 인스턴스
# =========================================================

error_handler = ErrorHandler()


# =========================================================
# 편의 함수
# =========================================================

def handle_error(
    error: Exception,
    context: str = "",
    notify: bool = True,
    reraise: bool = False,
) -> Optional[ErrorRecord]:
    """에러 처리 (편의 함수)"""
    return error_handler.handle(error, context, notify=notify, reraise=reraise)


def get_error_stats() -> Dict:
    """에러 통계 조회"""
    return error_handler.get_stats()


def set_error_notify_callback(callback: Callable[[str], None]):
    """알림 콜백 설정"""
    error_handler.set_notify_callback(callback)


def log_and_notify(
    message: str,
    severity: ErrorSeverity = ErrorSeverity.ERROR,
    context: str = "",
    notify: bool = True,
):
    """
    로그 및 알림 발송 (에러 없이)
    
    Args:
        message: 메시지
        severity: 심각도
        context: 컨텍스트
        notify: 알림 발송 여부
    """
    # 로깅
    if severity == ErrorSeverity.CRITICAL:
        logger.critical(f"[{context}] {message}")
    elif severity == ErrorSeverity.ERROR:
        logger.error(f"[{context}] {message}")
    elif severity == ErrorSeverity.WARNING:
        logger.warning(f"[{context}] {message}")
    else:
        logger.info(f"[{context}] {message}")
    
    # 알림
    if notify and error_handler.notify_callback and severity in [ErrorSeverity.ERROR, ErrorSeverity.CRITICAL]:
        try:
            severity_emoji = {
                ErrorSeverity.CRITICAL: "🚨",
                ErrorSeverity.ERROR: "❌",
                ErrorSeverity.WARNING: "⚠️",
            }
            emoji = severity_emoji.get(severity, "ℹ️")
            error_handler.notify_callback(f"{emoji} [{context}] {message}")
        except Exception as e:
            logger.error(f"알림 발송 실패: {e}")
