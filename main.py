# -*- coding: utf-8 -*-
"""
Phoenix v5.3.1 — MAIN (빗썸 예측차트 통합)

🔥 v5.3.1 변경:
- 빗썸 예측차트 모듈 초기화 추가
- predictor.set_api() 연동

v5.2.0 변경:
- 단타모드(ScalpManager) 완전 삭제
- 1h/4h/일봉 → AI 연결
- 자본 100% 메인 전략
"""

import threading
import time

from config import Config
from bot.api.bithumb_ccxt_api import get_api, set_precision_fetcher
from bot.core.position_manager import PositionManager
from bot.core.risk_manager import RiskManager
from bot.core.execution_engine import ExecutionEngine
from bot.core.signal_bot import SignalBot
from bot.core.strategy_engine import StrategyEngine
from bot.core.portfolio_optimizer import PortfolioOptimizer
from bot.core.trade_logger import TradeLogger
# 🔥 v5.2.0: ScalpManager import 삭제
from bot.core.chart_engine import ChartEngine
from bot.core.circuit_breaker import CircuitBreaker
from bot.core.position_sync import PositionSyncManager
from bot.telegram.telegram_bot import TelegramBot
from bot.utils.logger import get_logger

logger = get_logger("MAIN")


def main():
    logger.info("=" * 60)
    logger.info("Phoenix v5.3.1 (빗썸 예측차트 통합) 시작")
    logger.info("=" * 60)

    # 1) API
    api = get_api()
    logger.info("[MAIN] Bithumb API 로딩 완료")
    
    # 동적 정밀도 조회기 설정
    set_precision_fetcher(api)
    logger.info("[MAIN] 동적 수량 정밀도 조회 설정 완료")
    
    # 🆕 v5.3.1: 빗썸 예측차트 모듈 초기화
    try:
        from bot.core.bithumb_predictor import get_predictor
        predictor = get_predictor()
        predictor.set_api(api)
        logger.info("[MAIN] 빗썸 예측차트 모듈 초기화 완료")
    except ImportError:
        logger.warning("[MAIN] bithumb_predictor 모듈 없음 - 비활성화")
    except Exception as e:
        logger.error(f"[MAIN] 빗썸 예측차트 초기화 실패: {e}")

    # 2) Price Feed
    price_store = None
    ws_feed = None
    
    try:
        from bot.price_feed import PriceStore, BithumbPriceFeed
        price_store = PriceStore()
        ws_feed = BithumbPriceFeed(Config.COIN_POOL, price_store, api=api)
        ws_feed.start()
        logger.info("[MAIN] WebSocket PriceFeed 시작됨")
        time.sleep(30)
    except ImportError:
        logger.warning("[MAIN] price_feed 모듈 없음 - REST 모드")
        price_store = None
        ws_feed = None

    # 3) Core Managers
    pm = PositionManager()
    rm = RiskManager(api=api, position_manager=pm, datalayer=price_store)
    trade_logger = TradeLogger()
    
    # 서킷브레이커 초기화
    circuit_breaker = CircuitBreaker({
        'max_consecutive_losses': 5,
        'max_daily_loss_pct': 3.0,
        'max_api_failures': 10,
        'cooldown_minutes': 30,
    })
    logger.info("[MAIN] CircuitBreaker 초기화 완료")
    
    # 포지션 동기화 매니저
    position_sync = PositionSyncManager(
        api_client=api,
        position_manager=pm,
        threshold_pct=5.0,
    )
    logger.info("[MAIN] PositionSyncManager 초기화 완료")

    # 4) Strategy & Portfolio
    strategy = StrategyEngine(price_store)
    pf_engine = PortfolioOptimizer(api)

    # 5) Execution Engine
    exe = ExecutionEngine(
        api, pm, rm, 
        price_feed=price_store,
        trade_logger=trade_logger,
        telegram_bot=None,
    )
    
    # 5-1) Chart Engine
    chart_engine = ChartEngine(api, pm, price_store)

    # 6) Telegram Bot
    telegram_bot = TelegramBot()
    
    # ExecutionEngine에 telegram_bot 주입
    exe.inject_modules(telegram_bot=telegram_bot)
    logger.info("[MAIN] ExecutionEngine에 trade_logger, telegram_bot 주입 완료")
    
    # 서킷브레이커/포지션동기화에 텔레그램 알림 콜백 설정
    circuit_breaker.set_alert_callback(telegram_bot.send_message_sync)
    position_sync.set_alert_callback(telegram_bot.send_message_sync)
    logger.info("[MAIN] 안정성 패치 알림 콜백 설정 완료")

    # 🔥 v5.2.0: ScalpManager 초기화 삭제됨 (단타모드 제거)

    # 7) Signal Bot (🔥 v5.2.0: scalp_manager 파라미터 삭제)
    signal_bot = SignalBot(
        api=api,
        exe=exe,
        pm=pm,
        rm=rm,
        pf_engine=pf_engine,
        price_feed=price_store,
        strategy=strategy,
        tb=telegram_bot,
        # scalp_manager 삭제됨
    )

    # 8) Telegram 모듈 주입 (🔥 v5.2.0: scalp_manager 삭제)
    telegram_bot.inject_modules(
        signal_bot=signal_bot,
        execution_engine=exe,
        pm=pm,
        rm=rm,
        trade_logger=trade_logger,
        price_feed=ws_feed,
        # scalp_manager 삭제됨
        chart=chart_engine,
        circuit_breaker=circuit_breaker,
        position_sync=position_sync,
    )

    # 9) Signal Loop Thread
    def run_signal():
        logger.info("[MAIN] SignalBot Loop 시작")
        while True:
            try:
                signal_bot.loop_once()
            except Exception as e:
                logger.error(f"[SignalBot ERROR] {e}", exc_info=True)
            time.sleep(Config.LOOP_SLEEP)

    t_signal = threading.Thread(target=run_signal, daemon=True)
    t_signal.start()

    # 10) Telegram Thread
    telegram_bot.run_in_thread()

    # 11) 메인 유지
    logger.info("[MAIN] 모든 컴포넌트 시작 완료")
    logger.info("=" * 60)
    
    try:
        while True:
            time.sleep(60)
    except KeyboardInterrupt:
        logger.info("[MAIN] 종료 요청")


if __name__ == "__main__":
    main()
