# -*- coding: utf-8 -*-
"""
Phoenix v5.3.1b — AI 응답 파서 및 검증기

AI 응답의 JSON 추출, 스키마 검증, 정규화를 담당합니다.

🔥 v5.3.1b (2025-12-04):
- holding_period 기본값 개선: "unknown" → position_type 기반 기본값
- scalp → "수시간", swing → "1~3일"

🔥 v5.3.0:
- ai_decision.py에서 분리
- bot/utils/validators.py의 JSONValidator 활용
- 타입 힌트 강화
"""

import json
import re
from typing import Dict, Any, Optional, Set
from dataclasses import dataclass, field

from config import Config
from bot.utils.logger import get_logger
from bot.utils.validators import DataValidator, JSONValidator

logger = get_logger("AI.ResponseParser")


# =========================================================
# 상수 정의
# =========================================================

VALID_DECISIONS: Set[str] = {"buy", "hold", "sell"}
VALID_POSITION_TYPES: Set[str] = {"scalp", "swing"}
VALID_MARKET_CONDITIONS: Set[str] = {
    "strong_uptrend", "weak_uptrend", "sideways",
    "high_volatility", "weak_downtrend", "strong_downtrend"
}


@dataclass
class AIResponseDefaults:
    """AI 응답 기본값"""
    decision: str = "hold"
    confidence: float = 0.5
    market_condition: str = "sideways"
    position_type: str = "swing"
    holding_period: str = "unknown"
    tp: float = 0.03
    sl: float = 0.03
    tp_price: Optional[float] = None
    sl_price: Optional[float] = None
    position_weight: float = 0.2
    pivot_signal: Optional[str] = None
    long_term_aligned: Optional[bool] = None
    reason: str = ""
    risk_note: str = ""
    
    def to_dict(self) -> Dict[str, Any]:
        """딕셔너리로 변환"""
        return {
            "decision": self.decision,
            "confidence": self.confidence,
            "market_condition": self.market_condition,
            "position_type": self.position_type,
            "holding_period": self.holding_period,
            "tp": self.tp,
            "sl": self.sl,
            "tp_price": self.tp_price,
            "sl_price": self.sl_price,
            "position_weight": self.position_weight,
            "pivot_signal": self.pivot_signal,
            "long_term_aligned": self.long_term_aligned,
            "reason": self.reason,
            "risk_note": self.risk_note,
        }


@dataclass
class AIResponseLimits:
    """AI 응답 값 제한"""
    confidence_min: float = 0.0
    confidence_max: float = 1.0
    tp_min: float = 0.01
    tp_max: float = 0.15
    sl_min: float = 0.03  # Config에서 가져옴
    sl_max: float = 0.07  # Config에서 가져옴
    position_weight_min: float = 0.15
    position_weight_max: float = 0.35
    
    @classmethod
    def from_config(cls) -> 'AIResponseLimits':
        """Config에서 제한값 로드"""
        return cls(
            sl_min=getattr(Config, 'AI_SL_MIN', 0.03),
            sl_max=getattr(Config, 'AI_SL_MAX', 0.07),
        )


class AIResponseParser:
    """
    AI 응답 파서 및 검증기
    
    GPT 응답에서 JSON을 추출하고, 스키마를 검증하며,
    값을 정규화하여 안전하게 사용할 수 있도록 합니다.
    """
    
    def __init__(self):
        self.defaults = AIResponseDefaults()
        self.limits = AIResponseLimits.from_config()
    
    @staticmethod
    def extract_json(text: str) -> Optional[Dict]:
        """
        텍스트에서 JSON 추출
        
        시도 순서:
        1. 직접 JSON 파싱
        2. 코드 블록에서 추출
        3. 중괄호 패턴에서 추출
        
        Args:
            text: AI 응답 텍스트
            
        Returns:
            추출된 딕셔너리 또는 None
        """
        if not text:
            return None
        
        # 1. 직접 파싱 시도
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            pass
        
        # 2. 코드 블록에서 추출
        json_block_pattern = r'```(?:json)?\s*([\s\S]*?)\s*```'
        matches = re.findall(json_block_pattern, text)
        for match in matches:
            try:
                return json.loads(match)
            except json.JSONDecodeError:
                continue
        
        # 3. 중괄호 패턴에서 추출
        brace_pattern = r'\{[\s\S]*\}'
        matches = re.findall(brace_pattern, text)
        for match in matches:
            try:
                return json.loads(match)
            except json.JSONDecodeError:
                continue
        
        logger.warning("[Parser] JSON 추출 실패")
        return None
    
    @staticmethod
    def _clamp(value: float, min_val: float, max_val: float) -> float:
        """값을 범위 내로 제한"""
        return max(min_val, min(max_val, value))
    
    @staticmethod
    def _safe_float(value: Any, default: float, field_name: str = "") -> float:
        """안전한 float 변환"""
        if value is None:
            return default
        
        try:
            if isinstance(value, str):
                value = value.strip().replace("%", "")
                if not value:
                    return default
            
            result = float(value)
            
            # NaN, Inf 체크
            if result != result or result == float('inf') or result == float('-inf'):
                logger.debug(f"[Parser] {field_name}: 유효하지 않은 float → 기본값 {default}")
                return default
            
            return result
        except (ValueError, TypeError) as e:
            logger.debug(f"[Parser] {field_name}: float 변환 실패 ({value}) → 기본값 {default}")
            return default
    
    @staticmethod
    def _safe_string(
        value: Any, 
        default: str, 
        valid_set: Optional[Set[str]] = None,
        field_name: str = ""
    ) -> str:
        """안전한 string 변환"""
        if value is None:
            return default
        
        try:
            result = str(value).strip().lower()
            
            if valid_set and result not in valid_set:
                logger.debug(f"[Parser] {field_name}: '{result}'는 유효하지 않음 → 기본값 '{default}'")
                return default
            
            return result
        except Exception:
            return default
    
    def validate_and_normalize(
        self, 
        raw_data: Optional[Dict],
        market_condition_hint: str = "sideways"
    ) -> Dict[str, Any]:
        """
        AI 응답 검증 및 정규화
        
        Args:
            raw_data: AI 응답 딕셔너리
            market_condition_hint: 시장 상황 힌트 (기본값)
            
        Returns:
            정규화된 딕셔너리
        """
        if not raw_data or not isinstance(raw_data, dict):
            logger.warning("[Parser] 유효하지 않은 응답 데이터 → 기본값 사용")
            return self.defaults.to_dict()
        
        result = {}
        
        # decision
        result["decision"] = self._safe_string(
            raw_data.get("decision"),
            self.defaults.decision,
            VALID_DECISIONS,
            "decision"
        )
        
        # confidence
        conf = self._safe_float(
            raw_data.get("confidence"),
            self.defaults.confidence,
            "confidence"
        )
        result["confidence"] = self._clamp(
            conf,
            self.limits.confidence_min,
            self.limits.confidence_max
        )
        
        # market_condition
        result["market_condition"] = self._safe_string(
            raw_data.get("market_condition"),
            market_condition_hint,
            VALID_MARKET_CONDITIONS,
            "market_condition"
        )
        
        # position_type
        result["position_type"] = self._safe_string(
            raw_data.get("position_type"),
            self.defaults.position_type,
            VALID_POSITION_TYPES,
            "position_type"
        )
        
        # holding_period (🆕 v5.3.1b: position_type 기반 기본값)
        hp = raw_data.get("holding_period")
        if hp:
            result["holding_period"] = str(hp)
        else:
            # position_type에 따른 의미있는 기본값
            if result["position_type"] == "scalp":
                result["holding_period"] = "수시간"
            else:  # swing
                result["holding_period"] = "1~3일"
        
        # tp (퍼센트 → 소수점 변환 처리)
        tp = self._safe_float(raw_data.get("tp"), self.defaults.tp, "tp")
        if tp > 1:  # 퍼센트로 입력된 경우
            tp = tp / 100
        result["tp"] = self._clamp(tp, self.limits.tp_min, self.limits.tp_max)
        
        # sl (퍼센트 → 소수점 변환 처리)
        sl = self._safe_float(raw_data.get("sl"), self.defaults.sl, "sl")
        if sl > 1:  # 퍼센트로 입력된 경우
            sl = sl / 100
        result["sl"] = self._clamp(sl, self.limits.sl_min, self.limits.sl_max)
        
        # tp_price, sl_price
        tp_price = raw_data.get("tp_price")
        sl_price = raw_data.get("sl_price")
        result["tp_price"] = self._safe_float(tp_price, None, "tp_price") if tp_price else None
        result["sl_price"] = self._safe_float(sl_price, None, "sl_price") if sl_price else None
        
        # position_weight
        pw = self._safe_float(
            raw_data.get("position_weight"),
            self.defaults.position_weight,
            "position_weight"
        )
        if pw > 1:  # 퍼센트로 입력된 경우
            pw = pw / 100
        result["position_weight"] = self._clamp(
            pw,
            self.limits.position_weight_min,
            self.limits.position_weight_max
        )
        
        # pivot_signal
        ps = raw_data.get("pivot_signal")
        result["pivot_signal"] = str(ps) if ps else None
        
        # long_term_aligned
        lta = raw_data.get("long_term_aligned")
        result["long_term_aligned"] = lta if isinstance(lta, bool) else None
        
        # reason (최대 500자)
        reason = raw_data.get("reason")
        result["reason"] = str(reason)[:500] if reason else ""
        
        # risk_note (최대 200자)
        risk_note = raw_data.get("risk_note")
        result["risk_note"] = str(risk_note)[:200] if risk_note else ""
        
        return result
    
    def parse_response(
        self,
        raw_text: str,
        market_condition_hint: str = "sideways"
    ) -> Dict[str, Any]:
        """
        AI 응답 전체 파싱 (추출 + 검증 + 정규화)
        
        Args:
            raw_text: AI 응답 원본 텍스트
            market_condition_hint: 시장 상황 힌트
            
        Returns:
            정규화된 딕셔너리
        """
        # JSON 추출
        extracted = self.extract_json(raw_text)
        
        if extracted is None:
            logger.warning("[Parser] JSON 추출 실패 → 기본값 반환")
            return self.defaults.to_dict()
        
        # 검증 및 정규화
        result = self.validate_and_normalize(extracted, market_condition_hint)
        
        return result
    
    def get_defaults(self) -> Dict[str, Any]:
        """기본값 딕셔너리 반환"""
        return self.defaults.to_dict()


# =========================================================
# 싱글톤 인스턴스 및 편의 함수
# =========================================================

_parser: Optional[AIResponseParser] = None


def get_parser() -> AIResponseParser:
    """싱글톤 파서 인스턴스 반환"""
    global _parser
    if _parser is None:
        _parser = AIResponseParser()
    return _parser


def parse_ai_response(
    raw_text: str,
    market_condition_hint: str = "sideways"
) -> Dict[str, Any]:
    """
    AI 응답 파싱 (편의 함수)
    
    Args:
        raw_text: AI 응답 원본 텍스트
        market_condition_hint: 시장 상황 힌트
        
    Returns:
        정규화된 딕셔너리
    """
    return get_parser().parse_response(raw_text, market_condition_hint)


def extract_json_from_ai(text: str) -> Optional[Dict]:
    """JSON 추출 (편의 함수)"""
    return AIResponseParser.extract_json(text)


def get_ai_defaults() -> Dict[str, Any]:
    """기본값 반환 (편의 함수)"""
    return get_parser().get_defaults()


# =========================================================
# 호환성 유지 (기존 코드 지원)
# =========================================================

class AIResponseValidator:
    """
    기존 AIResponseValidator 호환 클래스
    
    ⚠️ Deprecated: AIResponseParser 사용 권장
    """
    
    VALID_DECISIONS = VALID_DECISIONS
    VALID_POSITION_TYPES = VALID_POSITION_TYPES
    VALID_MARKET_CONDITIONS = VALID_MARKET_CONDITIONS
    DEFAULTS = AIResponseDefaults().to_dict()
    
    @classmethod
    def get_limits(cls) -> Dict:
        limits = AIResponseLimits.from_config()
        return {
            "confidence": (limits.confidence_min, limits.confidence_max),
            "tp": (limits.tp_min, limits.tp_max),
            "sl": (limits.sl_min, limits.sl_max),
            "position_weight": (limits.position_weight_min, limits.position_weight_max),
        }
    
    @classmethod
    def safe_float(cls, value: Any, default: float, field_name: str = "") -> float:
        return AIResponseParser._safe_float(value, default, field_name)
    
    @classmethod
    def safe_string(cls, value: Any, default: str, valid_set: set = None, field_name: str = "") -> str:
        return AIResponseParser._safe_string(value, default, valid_set, field_name)
    
    @classmethod
    def clamp(cls, value: float, min_val: float, max_val: float) -> float:
        return AIResponseParser._clamp(value, min_val, max_val)
    
    @classmethod
    def validate_and_normalize(cls, raw_data: Dict, market_condition_hint: str = "sideways") -> Dict:
        return get_parser().validate_and_normalize(raw_data, market_condition_hint)
    
    @classmethod
    def extract_json_from_text(cls, text: str) -> Optional[Dict]:
        return AIResponseParser.extract_json(text)
