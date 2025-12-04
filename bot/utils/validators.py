# -*- coding: utf-8 -*-
"""
Phoenix v5.3.0 — 공통 검증 로직

데이터 검증 및 정규화
- 타입 안전 변환
- JSON 검증
- 심볼/가격 검증
"""

import json
import re
import math
from typing import Any, Dict, Optional, Set, Union, List, TypeVar
from dataclasses import dataclass

T = TypeVar('T')


# =========================================================
# 데이터 타입 검증/변환
# =========================================================

class DataValidator:
    """데이터 검증 및 안전 변환 유틸리티"""
    
    @staticmethod
    def safe_float(
        value: Any,
        default: float = 0.0,
        min_val: float = None,
        max_val: float = None,
        allow_nan: bool = False,
        allow_inf: bool = False,
    ) -> float:
        """
        안전한 float 변환
        
        Args:
            value: 변환할 값
            default: 변환 실패 시 기본값
            min_val: 최소값 (clamp)
            max_val: 최대값 (clamp)
            allow_nan: NaN 허용 여부
            allow_inf: Infinity 허용 여부
            
        Returns:
            변환된 float 값
        """
        if value is None:
            return default
        
        try:
            # 문자열 전처리
            if isinstance(value, str):
                value = value.strip()
                # % 및 , 제거
                value = value.replace("%", "").replace(",", "")
                if not value:
                    return default
            
            result = float(value)
            
            # NaN 체크
            if math.isnan(result) and not allow_nan:
                return default
            
            # Infinity 체크
            if math.isinf(result) and not allow_inf:
                return default
            
            # 범위 제한
            if min_val is not None:
                result = max(result, min_val)
            if max_val is not None:
                result = min(result, max_val)
            
            return result
            
        except (ValueError, TypeError):
            return default
    
    @staticmethod
    def safe_int(
        value: Any,
        default: int = 0,
        min_val: int = None,
        max_val: int = None,
    ) -> int:
        """
        안전한 int 변환
        
        Args:
            value: 변환할 값
            default: 변환 실패 시 기본값
            min_val: 최소값 (clamp)
            max_val: 최대값 (clamp)
            
        Returns:
            변환된 int 값
        """
        result = DataValidator.safe_float(value, float(default))
        result = int(result)
        
        if min_val is not None:
            result = max(result, min_val)
        if max_val is not None:
            result = min(result, max_val)
        
        return result
    
    @staticmethod
    def safe_string(
        value: Any,
        default: str = "",
        strip: bool = True,
        lowercase: bool = False,
        uppercase: bool = False,
        max_length: int = None,
        valid_set: Set[str] = None,
        regex_pattern: str = None,
    ) -> str:
        """
        안전한 string 변환
        
        Args:
            value: 변환할 값
            default: 변환 실패 시 기본값
            strip: 공백 제거 여부
            lowercase: 소문자 변환 여부
            uppercase: 대문자 변환 여부
            max_length: 최대 길이
            valid_set: 유효한 값 집합
            regex_pattern: 정규식 패턴 (매칭 검증)
            
        Returns:
            변환된 string 값
        """
        if value is None:
            return default
        
        try:
            result = str(value)
            
            if strip:
                result = result.strip()
            
            if lowercase:
                result = result.lower()
            elif uppercase:
                result = result.upper()
            
            if max_length and len(result) > max_length:
                result = result[:max_length]
            
            if valid_set and result not in valid_set:
                return default
            
            if regex_pattern and not re.match(regex_pattern, result):
                return default
            
            return result
            
        except Exception:
            return default
    
    @staticmethod
    def safe_bool(
        value: Any,
        default: bool = False,
    ) -> bool:
        """
        안전한 bool 변환
        
        Args:
            value: 변환할 값
            default: 변환 실패 시 기본값
            
        Returns:
            변환된 bool 값
        """
        if value is None:
            return default
        
        if isinstance(value, bool):
            return value
        
        if isinstance(value, str):
            return value.lower() in ("true", "1", "yes", "on", "y")
        
        if isinstance(value, (int, float)):
            return bool(value)
        
        return default
    
    @staticmethod
    def safe_dict(
        value: Any,
        default: Dict = None,
        required_keys: List[str] = None,
    ) -> Dict:
        """
        안전한 dict 변환/검증
        
        Args:
            value: 변환할 값
            default: 변환 실패 시 기본값
            required_keys: 필수 키 목록
            
        Returns:
            변환된 dict 값
        """
        if default is None:
            default = {}
        
        if value is None:
            return default.copy()
        
        if not isinstance(value, dict):
            return default.copy()
        
        if required_keys:
            for key in required_keys:
                if key not in value:
                    return default.copy()
        
        return value
    
    @staticmethod
    def safe_list(
        value: Any,
        default: List = None,
        min_length: int = None,
        max_length: int = None,
    ) -> List:
        """
        안전한 list 변환
        
        Args:
            value: 변환할 값
            default: 변환 실패 시 기본값
            min_length: 최소 길이
            max_length: 최대 길이
            
        Returns:
            변환된 list 값
        """
        if default is None:
            default = []
        
        if value is None:
            return default.copy()
        
        if not isinstance(value, (list, tuple)):
            return default.copy()
        
        result = list(value)
        
        if min_length and len(result) < min_length:
            return default.copy()
        
        if max_length and len(result) > max_length:
            result = result[:max_length]
        
        return result


# =========================================================
# JSON 검증
# =========================================================

class JSONValidator:
    """JSON 검증 유틸리티"""
    
    # JSON 추출 패턴
    JSON_BLOCK_PATTERN = r'```(?:json)?\s*([\s\S]*?)\s*```'
    BRACE_PATTERN = r'\{[\s\S]*\}'
    
    @staticmethod
    def extract_json(text: str, strict: bool = False) -> Optional[Dict]:
        """
        텍스트에서 JSON 추출
        
        Args:
            text: 원본 텍스트
            strict: 엄격 모드 (직접 파싱만 시도)
            
        Returns:
            추출된 JSON 딕셔너리 또는 None
        """
        if not text or not isinstance(text, str):
            return None
        
        text = text.strip()
        
        # 1. 직접 파싱 시도
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            pass
        
        if strict:
            return None
        
        # 2. 코드 블록에서 추출
        matches = re.findall(JSONValidator.JSON_BLOCK_PATTERN, text)
        for match in matches:
            try:
                return json.loads(match.strip())
            except json.JSONDecodeError:
                continue
        
        # 3. 중괄호 패턴에서 추출
        matches = re.findall(JSONValidator.BRACE_PATTERN, text)
        for match in matches:
            try:
                return json.loads(match)
            except json.JSONDecodeError:
                continue
        
        return None
    
    @staticmethod
    def validate_schema(
        data: Dict,
        schema: Dict[str, type],
        allow_extra: bool = True,
    ) -> tuple[bool, List[str]]:
        """
        간단한 스키마 검증
        
        Args:
            data: 검증할 데이터
            schema: 스키마 (필드명 -> 타입)
            allow_extra: 추가 필드 허용 여부
            
        Returns:
            (검증 성공 여부, 오류 메시지 목록)
        """
        errors = []
        
        if not isinstance(data, dict):
            return False, ["데이터가 딕셔너리가 아닙니다"]
        
        # 필수 필드 검증
        for key, expected_type in schema.items():
            if key not in data:
                errors.append(f"필수 필드 누락: {key}")
                continue
            
            value = data[key]
            
            # None 허용 체크
            if value is None:
                continue
            
            # 타입 검증
            if not isinstance(value, expected_type):
                errors.append(
                    f"타입 불일치: {key} (예상: {expected_type.__name__}, "
                    f"실제: {type(value).__name__})"
                )
        
        # 추가 필드 검증
        if not allow_extra:
            extra_keys = set(data.keys()) - set(schema.keys())
            if extra_keys:
                errors.append(f"허용되지 않은 필드: {extra_keys}")
        
        return len(errors) == 0, errors
    
    @staticmethod
    def safe_parse(
        text: str,
        default: Dict = None,
        required_keys: List[str] = None,
    ) -> Dict:
        """
        안전한 JSON 파싱
        
        Args:
            text: JSON 텍스트
            default: 파싱 실패 시 기본값
            required_keys: 필수 키 목록
            
        Returns:
            파싱된 딕셔너리
        """
        if default is None:
            default = {}
        
        result = JSONValidator.extract_json(text)
        
        if result is None:
            return default.copy()
        
        if required_keys:
            for key in required_keys:
                if key not in result:
                    return default.copy()
        
        return result


# =========================================================
# 심볼 검증
# =========================================================

class SymbolValidator:
    """심볼 검증 유틸리티"""
    
    @staticmethod
    def normalize(symbol: str, quote: str = "KRW") -> str:
        """
        심볼 정규화 (SOL → SOL/KRW)
        
        Args:
            symbol: 원본 심볼
            quote: 쿼트 통화
            
        Returns:
            정규화된 심볼
        """
        if not symbol:
            return ""
        
        symbol = symbol.upper().strip()
        
        # 하이픈을 슬래시로 변환
        symbol = symbol.replace("-", "/")
        
        # 이미 쿼트가 있으면 그대로
        if f"/{quote}" in symbol:
            return symbol
        
        # 다른 쿼트 제거
        for old_quote in ["USDT", "BTC", "ETH", "KRW"]:
            if symbol.endswith(f"/{old_quote}"):
                symbol = symbol.replace(f"/{old_quote}", "")
                break
        
        return f"{symbol}/{quote}"
    
    @staticmethod
    def extract_coin(symbol: str) -> str:
        """
        코인 추출 (SOL/KRW → SOL)
        
        Args:
            symbol: 심볼
            
        Returns:
            코인 이름
        """
        if not symbol:
            return ""
        
        symbol = symbol.upper().strip()
        
        # 슬래시 기준 분리
        if "/" in symbol:
            return symbol.split("/")[0]
        
        # 하이픈 기준 분리
        if "-" in symbol:
            return symbol.split("-")[0]
        
        # 알려진 쿼트 제거
        for quote in ["KRW", "USDT", "BTC", "ETH"]:
            if symbol.endswith(quote):
                return symbol[:-len(quote)]
        
        return symbol
    
    @staticmethod
    def is_valid(
        symbol: str,
        valid_pool: Set[str] = None,
        require_quote: str = "KRW",
    ) -> bool:
        """
        심볼 유효성 검증
        
        Args:
            symbol: 심볼
            valid_pool: 유효한 심볼 집합
            require_quote: 필수 쿼트 통화
            
        Returns:
            유효 여부
        """
        if not symbol:
            return False
        
        normalized = SymbolValidator.normalize(symbol)
        
        # 형식 검증
        if "/" not in normalized:
            return False
        
        # 쿼트 검증
        if require_quote and not normalized.endswith(f"/{require_quote}"):
            return False
        
        # 풀 검증
        if valid_pool:
            return normalized in valid_pool
        
        return True
    
    @staticmethod
    def format_for_display(symbol: str) -> str:
        """
        표시용 포맷 (SOL/KRW → SOL)
        """
        return SymbolValidator.extract_coin(symbol)


# =========================================================
# 가격 검증
# =========================================================

class PriceValidator:
    """가격 검증 유틸리티"""
    
    @staticmethod
    def is_valid_price(
        price: float,
        min_price: float = 0.0000001,
        max_price: float = 1_000_000_000,
    ) -> bool:
        """
        유효한 가격인지 검증
        
        Args:
            price: 가격
            min_price: 최소 가격
            max_price: 최대 가격
            
        Returns:
            유효 여부
        """
        if price is None:
            return False
        
        try:
            price = float(price)
        except (ValueError, TypeError):
            return False
        
        # NaN/Inf 체크
        if math.isnan(price) or math.isinf(price):
            return False
        
        # 범위 체크
        if price < min_price or price > max_price:
            return False
        
        return True
    
    @staticmethod
    def is_valid_quantity(
        quantity: float,
        min_qty: float = 0,
        max_qty: float = None,
    ) -> bool:
        """
        유효한 수량인지 검증
        
        Args:
            quantity: 수량
            min_qty: 최소 수량
            max_qty: 최대 수량
            
        Returns:
            유효 여부
        """
        if quantity is None:
            return False
        
        try:
            quantity = float(quantity)
        except (ValueError, TypeError):
            return False
        
        # NaN/Inf 체크
        if math.isnan(quantity) or math.isinf(quantity):
            return False
        
        # 범위 체크
        if quantity < min_qty:
            return False
        
        if max_qty is not None and quantity > max_qty:
            return False
        
        return True
    
    @staticmethod
    def validate_order(
        price: float,
        quantity: float,
        min_order_value: float = 5000,
    ) -> tuple[bool, str]:
        """
        주문 유효성 검증
        
        Args:
            price: 가격
            quantity: 수량
            min_order_value: 최소 주문 금액 (KRW)
            
        Returns:
            (유효 여부, 오류 메시지)
        """
        if not PriceValidator.is_valid_price(price):
            return False, f"잘못된 가격: {price}"
        
        if not PriceValidator.is_valid_quantity(quantity):
            return False, f"잘못된 수량: {quantity}"
        
        order_value = price * quantity
        
        if order_value < min_order_value:
            return False, f"최소 주문금액 미달: {order_value:,.0f} < {min_order_value:,.0f}"
        
        return True, ""
    
    @staticmethod
    def calculate_change_pct(
        current: float,
        previous: float,
    ) -> Optional[float]:
        """
        변화율 계산 (%)
        
        Args:
            current: 현재 값
            previous: 이전 값
            
        Returns:
            변화율 (%) 또는 None
        """
        if not PriceValidator.is_valid_price(current):
            return None
        
        if not PriceValidator.is_valid_price(previous):
            return None
        
        if previous == 0:
            return None
        
        return ((current - previous) / previous) * 100


# =========================================================
# 복합 검증기
# =========================================================

@dataclass
class ValidationResult:
    """검증 결과"""
    valid: bool
    errors: List[str]
    warnings: List[str] = None
    
    def __post_init__(self):
        if self.warnings is None:
            self.warnings = []
    
    def __bool__(self) -> bool:
        return self.valid
    
    def add_error(self, msg: str):
        self.errors.append(msg)
        self.valid = False
    
    def add_warning(self, msg: str):
        self.warnings.append(msg)


class TradeValidator:
    """거래 관련 종합 검증"""
    
    @staticmethod
    def validate_buy_signal(
        symbol: str,
        price: float,
        amount_krw: float,
        valid_pool: Set[str] = None,
        min_order: float = 5000,
        max_position_weight: float = 0.40,
        current_capital: float = 0,
    ) -> ValidationResult:
        """
        매수 신호 검증
        
        Args:
            symbol: 심볼
            price: 현재가
            amount_krw: 매수 금액 (KRW)
            valid_pool: 유효 코인 풀
            min_order: 최소 주문 금액
            max_position_weight: 최대 포지션 비중
            current_capital: 현재 총 자본
            
        Returns:
            ValidationResult
        """
        result = ValidationResult(valid=True, errors=[])
        
        # 심볼 검증
        if not SymbolValidator.is_valid(symbol, valid_pool):
            result.add_error(f"유효하지 않은 심볼: {symbol}")
        
        # 가격 검증
        if not PriceValidator.is_valid_price(price):
            result.add_error(f"유효하지 않은 가격: {price}")
        
        # 금액 검증
        if amount_krw < min_order:
            result.add_error(f"최소 주문금액 미달: {amount_krw:,.0f} < {min_order:,.0f}")
        
        # 비중 검증
        if current_capital > 0:
            weight = amount_krw / current_capital
            if weight > max_position_weight:
                result.add_error(
                    f"최대 비중 초과: {weight:.1%} > {max_position_weight:.1%}"
                )
        
        return result
    
    @staticmethod
    def validate_sell_signal(
        symbol: str,
        quantity: float,
        current_price: float,
        entry_price: float = None,
    ) -> ValidationResult:
        """
        매도 신호 검증
        
        Args:
            symbol: 심볼
            quantity: 매도 수량
            current_price: 현재가
            entry_price: 진입가 (P&L 계산용)
            
        Returns:
            ValidationResult
        """
        result = ValidationResult(valid=True, errors=[])
        
        # 심볼 검증
        if not symbol:
            result.add_error("심볼이 비어있습니다")
        
        # 수량 검증
        if not PriceValidator.is_valid_quantity(quantity, min_qty=0):
            result.add_error(f"유효하지 않은 수량: {quantity}")
        
        # 가격 검증
        if not PriceValidator.is_valid_price(current_price):
            result.add_error(f"유효하지 않은 현재가: {current_price}")
        
        # P&L 경고
        if entry_price and current_price:
            pnl_pct = ((current_price - entry_price) / entry_price) * 100
            if pnl_pct < -10:
                result.add_warning(f"큰 손실 매도: {pnl_pct:.1f}%")
        
        return result


# =========================================================
# 편의 함수
# =========================================================

# 자주 사용하는 검증 함수 별칭
safe_float = DataValidator.safe_float
safe_int = DataValidator.safe_int
safe_string = DataValidator.safe_string
safe_bool = DataValidator.safe_bool
safe_dict = DataValidator.safe_dict
safe_list = DataValidator.safe_list

extract_json = JSONValidator.extract_json
validate_json_schema = JSONValidator.validate_schema

normalize_symbol = SymbolValidator.normalize
extract_coin = SymbolValidator.extract_coin
is_valid_symbol = SymbolValidator.is_valid

is_valid_price = PriceValidator.is_valid_price
is_valid_quantity = PriceValidator.is_valid_quantity
