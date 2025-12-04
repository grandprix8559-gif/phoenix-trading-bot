# -*- coding: utf-8 -*-
"""
Phoenix v5.0.5 — Timezone Utility

KST 타임존 헬퍼
- datetime.now() 대신 now_kst() 사용
- pytz 없어도 동작 (UTC+9 수동 계산)
"""

from datetime import datetime, timedelta, timezone

# KST = UTC+9
KST = timezone(timedelta(hours=9))

try:
    import pytz
    KST_PYTZ = pytz.timezone('Asia/Seoul')
    USE_PYTZ = True
except ImportError:
    KST_PYTZ = None
    USE_PYTZ = False


def now_kst() -> datetime:
    """현재 KST 시간 반환"""
    if USE_PYTZ:
        return datetime.now(KST_PYTZ)
    return datetime.now(KST)


def today_kst() -> str:
    """오늘 날짜 문자열 (YYYY-MM-DD)"""
    return now_kst().strftime("%Y-%m-%d")


def timestamp_kst() -> str:
    """현재 시간 문자열 (YYYY-MM-DD HH:MM:SS)"""
    return now_kst().strftime("%Y-%m-%d %H:%M:%S")


def date_str_kst(fmt: str = "%Y%m%d") -> str:
    """포맷 지정 날짜 문자열"""
    return now_kst().strftime(fmt)
