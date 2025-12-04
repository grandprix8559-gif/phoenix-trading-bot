# -*- coding: utf-8 -*-
"""
Phoenix v5.3.1d — Config (10만원 테스트용)

🔥 v5.3.1d 변경사항 (10만원 테스트):
- BASE_CAPITAL: 15,000,000 → 100,000
- MAX_ACTIVE_COINS: 4 → 2
- MIN_POSITION_WEIGHT: 0.15 → 0.35
- MAX_POSITION_WEIGHT: 0.35 → 0.50
- POSITION_WEIGHT_CAP: 0.40 → 0.55
- MAX_DCA_COUNT: 3 → 2
- MAX_OPEN_POSITIONS: 4 → 2

🔥 v5.2.3 변경사항:
- 포트폴리오 20종 재구성 (틱비율 0.5% 미만 최적화)
- BTC 제외, 고변동성 + 고수익 코인 중심
- SHIB/PEPE/BONK 제거 (틱비율 과다)
- AVAX/ADA/OP/VIRTUAL/FLOKI/XLM/IMX 추가

🔧 v5.2.2 기능 유지:
- SL 최소: 3%, 최대: 7%
- ATR 기반 SL 배수 설정
- 단타모드 삭제, 자본 100% 메인 전략
"""

import os
from dotenv import load_dotenv

load_dotenv()


# =========================================================
# 🔥 v5.2.3: COIN CATEGORIES (수익률 최적화)
# =========================================================
COIN_CATEGORIES = {
    "major": ["ETH", "XRP", "SOL", "DOGE"],
    "layer1": ["SUI", "AVAX", "ADA", "SEI"],
    "defi": ["LINK", "ENA", "ONDO", "OP"],
    "ai": ["WLD", "VIRTUAL"],
    "meme": ["PENGU", "MOODENG", "FLOKI"],
    "alt": ["HBAR", "XLM", "IMX"],
}


class Config:
    """Phoenix v5.2.3 설정"""

    # =========================================================
    # OpenAI GPT-4o-mini
    # =========================================================
    OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
    OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini")

    # =========================================================
    # Trading Mode: AUTO / SEMI
    # =========================================================
    MODE = os.getenv("MODE", "SEMI").upper()

    # =========================================================
    # CAPITAL SETTINGS (🔥 10만원 테스트용)
    # =========================================================
    BASE_CAPITAL = float(os.getenv("BASE_CAPITAL", 100_000))
    USE_REALTIME_CAPITAL = os.getenv("USE_REALTIME_CAPITAL", "true").lower() == "true"
    CAPITAL_SAFETY_MARGIN = float(os.getenv("CAPITAL_SAFETY_MARGIN", 0.95))
    MIN_ORDER_AMOUNT = int(os.getenv("MIN_ORDER_AMOUNT", 5000))
    TOTAL_CAPITAL = float(os.getenv("TOTAL_CAPITAL", 100_000))

    # =========================================================
    # 자본 100% 메인 전략 (단타 삭제)
    # =========================================================
    MAIN_CAPITAL_RATIO = float(os.getenv("MAIN_CAPITAL_RATIO", 1.0))

    # =========================================================
    # Portfolio Settings (🔥 10만원 테스트용: 2포지션 집중)
    # =========================================================
    MAX_ACTIVE_COINS = int(os.getenv("MAX_ACTIVE_COINS", 2))
    MIN_POSITION_WEIGHT = float(os.getenv("MIN_POSITION_WEIGHT", 0.35))
    MAX_POSITION_WEIGHT = float(os.getenv("MAX_POSITION_WEIGHT", 0.50))
    POSITION_WEIGHT_CAP = float(os.getenv("POSITION_WEIGHT_CAP", 0.55))
    MAX_DCA_COUNT = int(os.getenv("MAX_DCA_COUNT", 2))

    # =========================================================
    # 🔥 v5.2.3: COIN POOL - 20종 (수익률 최적화)
    # =========================================================
    COIN_POOL = [
        # 메이저 (4종) - BTC 제외, 높은 유동성
        "ETH/KRW", "XRP/KRW", "SOL/KRW", "DOGE/KRW",
        
        # L1 (4종) - 생태계 성장, 변동성
        "SUI/KRW", "AVAX/KRW", "ADA/KRW", "SEI/KRW",
        
        # DeFi/인프라 (4종) - 테마 수혜
        "LINK/KRW", "ENA/KRW", "ONDO/KRW", "OP/KRW",
        
        # AI (2종) - 2024~2025 최강 내러티브
        "WLD/KRW", "VIRTUAL/KRW",
        
        # 밈코인 (3종) - 고변동성, 틱비율 0.5% 미만
        "PENGU/KRW", "MOODENG/KRW", "FLOKI/KRW",
        
        # 기타 (3종) - 다각화
        "HBAR/KRW", "XLM/KRW", "IMX/KRW",
    ]
    
    PF_REFRESH_SEC = int(os.getenv("PF_REFRESH_SEC", 60 * 60 * 24))
    BTC_SPIKE_THRESHOLD = float(os.getenv("BTC_SPIKE_THRESHOLD", 0.03))
    ATR_REBALANCE_THRESHOLD = float(os.getenv("ATR_REBALANCE_THRESHOLD", 0.50))

    # =========================================================
    # PIVOT POINT SETTINGS
    # =========================================================
    PIVOT_ENABLED = os.getenv("PIVOT_ENABLED", "true").lower() == "true"
    PIVOT_TYPE = os.getenv("PIVOT_TYPE", "standard")
    PIVOT_ENTRY_TOLERANCE = float(os.getenv("PIVOT_ENTRY_TOLERANCE", 0.005))
    PIVOT_TP_SL_ENABLED = os.getenv("PIVOT_TP_SL_ENABLED", "true").lower() == "true"

    # =========================================================
    # DYNAMIC ENTRY SETTINGS (동적 분할 진입)
    # =========================================================
    DYNAMIC_ENTRY_ENABLED = os.getenv("DYNAMIC_ENTRY_ENABLED", "true").lower() == "true"
    
    # 장기 추세별 1차 진입 비율
    ENTRY_RATIO_STRONG_UP = float(os.getenv("ENTRY_RATIO_STRONG_UP", 0.60))
    ENTRY_RATIO_WEAK_UP = float(os.getenv("ENTRY_RATIO_WEAK_UP", 0.40))
    ENTRY_RATIO_SIDEWAYS = float(os.getenv("ENTRY_RATIO_SIDEWAYS", 0.30))
    ENTRY_RATIO_WEAK_DOWN = float(os.getenv("ENTRY_RATIO_WEAK_DOWN", 0.25))
    ENTRY_RATIO_STRONG_DOWN = float(os.getenv("ENTRY_RATIO_STRONG_DOWN", 0.20))
    
    # ATR 등급별 분할 간격
    ATR_INTERVAL_LOW = float(os.getenv("ATR_INTERVAL_LOW", 0.02))
    ATR_INTERVAL_MEDIUM = float(os.getenv("ATR_INTERVAL_MEDIUM", 0.04))
    ATR_INTERVAL_HIGH = float(os.getenv("ATR_INTERVAL_HIGH", 0.07))
    ATR_INTERVAL_EXTREME = float(os.getenv("ATR_INTERVAL_EXTREME", 0.10))

    # =========================================================
    # SL HOLD SETTINGS (SL 홀드)
    # =========================================================
    SL_HOLD_HOURS = int(os.getenv("SL_HOLD_HOURS", 4))

    # =========================================================
    # v5.2.2: AI SL 범위 + ATR 배수
    # =========================================================
    AI_SL_MIN = float(os.getenv("AI_SL_MIN", 0.03))
    AI_SL_MAX = float(os.getenv("AI_SL_MAX", 0.07))
    
    # ATR 기반 SL 배수
    ATR_SL_MULTIPLIER_LOW = float(os.getenv("ATR_SL_MULTIPLIER_LOW", 2.0))
    ATR_SL_MULTIPLIER_MEDIUM = float(os.getenv("ATR_SL_MULTIPLIER_MEDIUM", 1.8))
    ATR_SL_MULTIPLIER_HIGH = float(os.getenv("ATR_SL_MULTIPLIER_HIGH", 1.5))
    ATR_SL_MULTIPLIER_EXTREME = float(os.getenv("ATR_SL_MULTIPLIER_EXTREME", 1.2))

    # =========================================================
    # SIGNAL THRESHOLD (임계값)
    # =========================================================
    SIGNAL_THRESHOLD = int(os.getenv("SIGNAL_THRESHOLD", 5))

    # =========================================================
    # APPROVAL SETTINGS
    # =========================================================
    APPROVAL_TIMEOUT_SEC = int(os.getenv("APPROVAL_TIMEOUT_SEC", 600))
    APPROVAL_PRICE_CHANGE_LIMIT = float(os.getenv("APPROVAL_PRICE_CHANGE_LIMIT", 0.02))

    # =========================================================
    # RISK SETTINGS (🔥 10만원 테스트용)
    # =========================================================
    MAX_OPEN_POSITIONS = int(os.getenv("MAX_OPEN_POSITIONS", 2))
    MAX_POSITION_SIZE = float(os.getenv("MAX_POSITION_SIZE", 0.18))
    DAILY_LOSS_LIMIT = float(os.getenv("DAILY_LOSS_LIMIT", 0.05))
    DRAWDOWN_LIMIT = float(os.getenv("DRAWDOWN_LIMIT", 0.10))
    AGGRESSIVE_MODE = os.getenv("AGGRESSIVE_MODE", "false").lower() == "true"
    BASE_TRADE_RISK_RATIO = float(os.getenv("BASE_TRADE_RISK_RATIO", 0.08))

    # =========================================================
    # AUTO EXIT SETTINGS
    # =========================================================
    AUTO_TP_ENABLED = os.getenv("AUTO_TP_ENABLED", "true").lower() == "true"
    AUTO_SL_ENABLED = os.getenv("AUTO_SL_ENABLED", "false").lower() == "true"

    # =========================================================
    # MARKET CONDITION SETTINGS
    # =========================================================
    MARKET_SETTINGS = {
        "strong_uptrend": {
            "position_type": "swing",
            "holding_days": "3~7",
            "tp_range": (0.05, 0.10),
            "sl_range": (0.03, 0.05),
        },
        "weak_uptrend": {
            "position_type": "swing",
            "holding_days": "1~3",
            "tp_range": (0.03, 0.05),
            "sl_range": (0.03, 0.04),
        },
        "sideways": {
            "position_type": "swing",
            "holding_days": "수시간~1일",
            "tp_range": (0.015, 0.03),
            "sl_range": (0.03, 0.04),
        },
        "high_volatility": {
            "position_type": "swing",
            "holding_days": "수시간~1일",
            "tp_range": (0.015, 0.025),
            "sl_range": (0.04, 0.06),
        },
        "weak_downtrend": {
            "position_type": "swing",
            "holding_days": "수시간~1일",
            "tp_range": (0.02, 0.03),
            "sl_range": (0.03, 0.05),
        },
        "strong_downtrend": {
            "position_type": "avoid",
            "holding_days": "-",
            "tp_range": (0.015, 0.025),
            "sl_range": (0.04, 0.06),
        },
    }

    # =========================================================
    # LOOP & TIMING
    # =========================================================
    LOOP_SLEEP = int(os.getenv("LOOP_SLEEP", 5))

    # =========================================================
    # API Keys (Bithumb)
    # =========================================================
    BITHUMB_API_KEY = os.getenv("BITHUMB_API_KEY")
    BITHUMB_SECRET_KEY = os.getenv("BITHUMB_SECRET_KEY")

    # =========================================================
    # Telegram
    # =========================================================
    TELEGRAM_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
    TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

    # =========================================================
    # DATA & LOGGING
    # =========================================================
    DATA_DIR = os.getenv("DATA_DIR", "data")
    LOG_DIR = os.getenv("LOG_DIR", "logs")
    TRADE_LOG_RETENTION_DAYS = int(os.getenv("TRADE_LOG_RETENTION_DAYS", 90))


# =========================================================
# Helper Functions
# =========================================================
def convert_symbol(coin: str) -> str:
    """심볼 포맷 변환 (SOL → SOL/KRW)"""
    coin = coin.upper().replace("/", "-")
    if "KRW" not in coin:
        coin = coin + "-KRW"
    return coin.replace("-", "/")


def get_market_settings(market_condition: str) -> dict:
    """시장 상황별 설정 조회"""
    return Config.MARKET_SETTINGS.get(
        market_condition, 
        Config.MARKET_SETTINGS["sideways"]
    )


def get_main_capital() -> float:
    """메인 전략 자본금 (100%)"""
    return Config.BASE_CAPITAL * Config.MAIN_CAPITAL_RATIO


def get_entry_ratio_by_trend(trend: str) -> float:
    """장기 추세별 1차 진입 비율"""
    ratios = {
        "strong_uptrend": Config.ENTRY_RATIO_STRONG_UP,
        "weak_uptrend": Config.ENTRY_RATIO_WEAK_UP,
        "sideways": Config.ENTRY_RATIO_SIDEWAYS,
        "weak_downtrend": Config.ENTRY_RATIO_WEAK_DOWN,
        "strong_downtrend": Config.ENTRY_RATIO_STRONG_DOWN,
    }
    return ratios.get(trend, Config.ENTRY_RATIO_SIDEWAYS)


def get_dca_interval_by_atr(atr_grade: str) -> float:
    """ATR 등급별 분할 진입 간격"""
    intervals = {
        "low": Config.ATR_INTERVAL_LOW,
        "medium": Config.ATR_INTERVAL_MEDIUM,
        "high": Config.ATR_INTERVAL_HIGH,
        "extreme": Config.ATR_INTERVAL_EXTREME,
    }
    return intervals.get(atr_grade, Config.ATR_INTERVAL_MEDIUM)


def get_atr_sl_multiplier(atr_pct: float) -> float:
    """ATR% 기반 SL 배수 반환"""
    if atr_pct <= 2:
        return Config.ATR_SL_MULTIPLIER_LOW
    elif atr_pct <= 4:
        return Config.ATR_SL_MULTIPLIER_MEDIUM
    elif atr_pct <= 6:
        return Config.ATR_SL_MULTIPLIER_HIGH
    else:
        return Config.ATR_SL_MULTIPLIER_EXTREME


def get_coins_by_category(category: str) -> list:
    """카테고리별 코인 목록 반환"""
    return COIN_CATEGORIES.get(category, [])


def get_all_categories() -> dict:
    """전체 카테고리 정보 반환"""
    return COIN_CATEGORIES.copy()
