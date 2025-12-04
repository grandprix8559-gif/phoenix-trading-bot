# -*- coding: utf-8 -*-
"""
Phoenix v5.3.2 — Indicators Package

기술적 지표 모듈들을 포함합니다.

Modules:
- candle_patterns: 캔들 패턴 감지 모듈
"""

from bot.core.indicators.candle_patterns import (
    CandlePatternDetector,
    detect_patterns,
    get_pattern_summary,
    get_detector,
)

__all__ = [
    "CandlePatternDetector",
    "detect_patterns",
    "get_pattern_summary",
    "get_detector",
]

__version__ = "5.3.2"
