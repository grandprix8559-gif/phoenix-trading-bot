# -*- coding: utf-8 -*-
"""
Phoenix v5.3.0 — SignalBot (Phase 1 캐시 모듈 적용)

🔥 v5.3.0 변경:
- bot.utils.cache 모듈 사용 (ai_cache, btc_context_cache)
- 자체 캐시 로직 제거 → 통합 캐시 사용
- 캐시 TTL 자동 관리

🔧 v5.2.2 기능 유지:
- 주봉(1w) 데이터 AI에 전달
- long_term_trend 결과 로깅
- 1h/4h/일봉 데이터 → AI 전달
"""

import time
import traceback
import pandas as pd
from datetime import datetime
from typing import Dict

from config import Config
from bot.utils.logger import get_logger
from bot.core.strategy_engine import StrategyEngine, get_consensus_signal
from bot.core.ai_decision import AIDecisionEngine

# 🆕 v5.3.0: 새 캐시 모듈 임포트
from bot.utils.cache import ai_cache, btc_context_cache

logger = get_logger("SignalBot")


class SignalBot:
    # 시간대별 설정
    TIME_ZONES = {
        (9, 11): (1, 1.1, "아시아 개장"),
        (21, 24): (1, 1.1, "미국 개장 전반"),
        (0, 1): (1, 1.1, "미국 개장 후반"),
        (3, 7): (0, 0.7, "저변동성 야간"),
    }
    
    # 🆕 v5.3.0: 캐시 TTL 설정 (초)
    AI_CACHE_TTL = 180       # AI 결정: 3분
    BTC_CONTEXT_TTL = 60     # BTC 컨텍스트: 1분

    def __init__(self, api, exe, pm, rm, pf_engine, price_feed, 
                 strategy=None, tb=None):
        """v5.3.0: 새 캐시 모듈 사용"""
        self.api = api
        self.ee = exe
        self.pm = pm
        self.rm = rm
        self.pf_opt = pf_engine
        self.price_feed = price_feed
        self.strategy = strategy if strategy else StrategyEngine(price_feed)
        self.tb = tb

        self.active_symbols = []
        self.weight_map = {}
        self.last_pf_refresh_date = None
        self.last_pf_refresh_ts = 0
        self.last_btc = None
        
        # 🆕 v5.3.0: 자체 캐시 제거 → bot.utils.cache 사용
        # (기존 self.ai_cache, self.btc_context_cache 삭제)
        
        # 중복 신호 방지용
        self.last_signal_time = {}
        self.SIGNAL_COOLDOWN = 300  # 5분 쿨다운
        
        # 승인 대기 중인 심볼 추적
        self.pending_approval = set()

        logger.info("[SignalBot v5.3.0] 초기화 (Phase 1 캐시 모듈 적용)")

    def _get_time_zone_config(self) -> Dict:
        """현재 시간대 설정 반환"""
        try:
            hour = datetime.now().hour
            
            for (start, end), (strength_adj, pos_mult, name) in self.TIME_ZONES.items():
                if start <= hour < end:
                    return {
                        "strength_adjust": strength_adj,
                        "position_mult": pos_mult,
                        "zone_name": name,
                        "hour": hour,
                    }
            
            return {"strength_adjust": 0, "position_mult": 1.0, "zone_name": "일반", "hour": hour}
        except:
            return {"strength_adjust": 0, "position_mult": 1.0, "zone_name": "기본", "hour": 0}

    def load_ohlcv(self, symbol):
        """OHLCV 데이터 로드"""
        try:
            df30 = self.price_feed.get_ohlcv(symbol, "30m")
            df15 = self.price_feed.get_ohlcv(symbol, "15m")
            df5 = self.price_feed.get_ohlcv(symbol, "5m")

            if df30 is None or df15 is None or df5 is None:
                return None, None, None
            if len(df30) < 50 or len(df15) < 50 or len(df5) < 50:
                return None, None, None
            return df30, df15, df5
        except Exception as e:
            logger.error(f"[{symbol}] OHLCV 에러: {e}")
            return None, None, None

    def _get_btc_context(self):
        """🔥 v5.3.0: BTC 컨텍스트 (새 캐시 모듈 사용)"""
        # 캐시 조회
        cached = btc_context_cache.get("btc_context")
        if cached is not None:
            return cached
        
        try:
            btc_df = self.price_feed.get_ohlcv("BTC/KRW", "30m")
            if btc_df is not None:
                result = AIDecisionEngine.get_btc_context(btc_df)
                # 캐시 저장 (TTL: 60초)
                btc_context_cache.set("btc_context", result, ttl=self.BTC_CONTEXT_TTL)
                return result
        except Exception as e:
            logger.error(f"[BTC Context] 조회 실패: {e}")
        
        return None

    def get_ai_decision(self, symbol, df30, df15, df5, btc_context=None):
        """🔥 v5.3.0: AI 판단 (새 캐시 모듈 사용) - 1h/4h/일봉/주봉 추가"""
        # 캐시 조회
        cached = ai_cache.get(symbol)
        if cached is not None:
            return cached

        if btc_context is None:
            btc_context = self._get_btc_context()

        # 장기 타임프레임 데이터 로드
        df1h = None
        df4h = None
        df_daily = None
        df_weekly = None
        
        if self.price_feed:
            try:
                df1h = self.price_feed.get_ohlcv(symbol, "1h")
                df4h = self.price_feed.get_ohlcv(symbol, "4h")
                df_daily = self.price_feed.get_ohlcv(symbol, "1d")
                df_weekly = self.price_feed.get_ohlcv(symbol, "1w")
            except Exception as e:
                logger.debug(f"[{symbol}] 장기 OHLCV 로드 실패: {e}")

        ai = AIDecisionEngine.analyze(
            symbol, df30, df15, df5,
            btc_context=btc_context,
            df1h=df1h,
            df4h=df4h,
            df_daily=df_daily,
            df_weekly=df_weekly,
        )
        
        # 캐시 저장 (TTL: 180초)
        ai_cache.set(symbol, ai, ttl=self.AI_CACHE_TTL)
        return ai

    def refresh_portfolio(self, force=False):
        """포트폴리오 갱신"""
        now = datetime.now()
        ts = time.time()
        today = now.date()
        need = False

        if force or not self.weight_map:
            need = True
        if self.last_pf_refresh_date != today and now.strftime("%H:%M") >= "09:00":
            need = True
        if ts - self.last_pf_refresh_ts > Config.PF_REFRESH_SEC:
            need = True

        # BTC 급변
        try:
            btc = self.price_feed.get_price("BTC/KRW")
            if btc and self.last_btc:
                if abs(btc - self.last_btc) / self.last_btc >= Config.BTC_SPIKE_THRESHOLD:
                    need = True
            self.last_btc = btc
        except:
            pass

        if not need:
            return

        try:
            pf = self.pf_opt.get_today_portfolio(Config.COIN_POOL)
            self.weight_map = pf
            self.active_symbols = list(pf.keys())
            self.last_pf_refresh_ts = ts
            self.last_pf_refresh_date = today

            if self.tb and self.tb.is_ready():
                msg = "<b>📊 오늘의 포트폴리오</b>\n\n"
                for sym, w in pf.items():
                    msg += f"{sym}: {w*100:.1f}%\n"
                self.tb.send_message_sync(msg)

            logger.info(f"[PF] 활성: {self.active_symbols}")
        except Exception as e:
            logger.error(f"[PF ERROR] {e}")

    def _can_send_signal(self, symbol: str) -> bool:
        """신호 발송 가능 여부 체크"""
        if self.pm.has_position(symbol):
            logger.debug(f"[{symbol}] 이미 보유 중 - 신호 스킵")
            return False
        
        if symbol in self.pending_approval:
            logger.debug(f"[{symbol}] 승인 대기 중 - 신호 스킵")
            return False
        
        if self.tb and hasattr(self.tb, 'approval_queue'):
            for item in self.tb.approval_queue.values():
                if item.get('symbol') == symbol:
                    logger.debug(f"[{symbol}] 텔레그램 승인 큐에 있음 - 신호 스킵")
                    return False
        
        now = time.time()
        last_time = self.last_signal_time.get(symbol, 0)
        if now - last_time < self.SIGNAL_COOLDOWN:
            remaining = int(self.SIGNAL_COOLDOWN - (now - last_time))
            logger.debug(f"[{symbol}] 쿨다운 중 ({remaining}초 남음) - 신호 스킵")
            return False
        
        return True

    def _record_signal(self, symbol: str):
        """신호 발생 시간 기록"""
        self.last_signal_time[symbol] = time.time()
        self.pending_approval.add(symbol)

    def _clear_pending(self, symbol: str):
        """승인/거절 후 대기 목록에서 제거"""
        self.pending_approval.discard(symbol)

    def process_symbol(self, symbol):
        """개별 심볼 처리"""
        try:
            pos = self.pm.get_position(symbol)
            has_pos = pos is not None
            
            if has_pos:
                return
            
            if not self._can_send_signal(symbol):
                return

            # OHLCV 로드
            df30, df15, df5 = self.load_ohlcv(symbol)
            if df30 is None:
                return

            # BTC 컨텍스트
            btc_context = self._get_btc_context()
            
            # BTC 마켓 모드
            btc_mode = AIDecisionEngine.get_btc_market_mode(btc_context)
            
            # 시간대 설정
            time_config = self._get_time_zone_config()

            # 전략 신호
            strat = self.strategy.get_signal(symbol, df30, df15, df5)
            
            # AI 판단 (🔥 v5.3.0: 새 캐시 사용)
            ai = self.get_ai_decision(symbol, df30, df15, df5, btc_context)

            # strength 조정 (BTC 모드 + 시간대)
            original_strength = strat.get("strength_sum", 0)
            btc_adjust = btc_mode.get("strength_adjust", 0)
            time_adjust = time_config.get("strength_adjust", 0)
            
            total_adjust = min(4, max(-4, btc_adjust + time_adjust))
            adjusted_strength = original_strength + total_adjust
            
            # 조정된 strat
            adjusted_strat = strat.copy()
            adjusted_strat["strength_sum"] = adjusted_strength
            adjusted_strat["original_strength"] = original_strength
            adjusted_strat["btc_adjustment"] = btc_adjust
            adjusted_strat["time_adjustment"] = time_adjust
            
            # 합의
            final = get_consensus_signal(adjusted_strat, ai)
            pf_w = self.weight_map.get(symbol, 0.0)

            # 장기 추세 로깅
            lt_trend = ai.get("long_term_trend", {})
            lt_str = lt_trend.get("trend", "N/A") if lt_trend else "N/A"
            
            logger.info(
                f"[{symbol}] str={original_strength}({btc_adjust:+d}btc{time_adjust:+d}time→{adjusted_strength}), "
                f"ai={ai['decision']}(conf={ai.get('confidence', 0):.2f}), "
                f"lt={lt_str}, zone={time_config['zone_name']} → {final}"
            )

            # BUY 신호 처리
            if final == "buy":
                if btc_mode["mode"] == "bear_strong":
                    logger.warning(f"[{symbol}] BTC 급락장 - BUY 차단")
                    return
                
                market_cond = ai.get("market_condition", "")
                if market_cond == "strong_downtrend":
                    logger.warning(f"[{symbol}] strong_downtrend에서 BUY 차단")
                    return
                
                # 주봉 하락 시 차단
                if lt_trend and lt_trend.get("trend") in ["bear", "strong_bear"]:
                    logger.warning(f"[{symbol}] 주봉 하락장({lt_trend.get('trend')}) - BUY 차단")
                    return
                
                risk = self.rm.check_limits()
                if not risk["can_trade"]:
                    logger.info(f"[{symbol}] 리스크 제한: {risk['reasons']}")
                    return

                krw_amount = self.rm.get_trade_amount(
                    symbol, pf_w, 
                    btc_mode=btc_mode,
                    time_config=time_config,
                    ai_confidence=ai.get("confidence", 0.5)
                )
                
                if krw_amount < Config.MIN_ORDER_AMOUNT:
                    logger.info(f"[{symbol}] 금액 부족: {krw_amount:,.0f}")
                    return

                current_price = self.price_feed.get_price(symbol) if self.price_feed else 0

                self._record_signal(symbol)

                # AI 결정에 추가 정보 포함
                ai_with_btc = ai.copy()
                ai_with_btc["btc_mode"] = btc_mode
                ai_with_btc["time_config"] = time_config

                if Config.MODE == "AUTO":
                    success = self.ee.execute(symbol, "buy", ai_with_btc, pf_w)
                    if success:
                        self._clear_pending(symbol)
                else:
                    if self.tb and self.tb.is_ready():
                        self.tb.send_approval_request(
                            symbol=symbol,
                            signal="buy",
                            ai_decision=ai_with_btc,
                            strategy=strat.get("decision", "unknown"),
                            current_price=current_price or 0,
                            krw_amount=krw_amount,
                            btc_mode=btc_mode,
                            time_config=time_config,
                        )
                        logger.info(f"[{symbol}] BUY 승인 요청 (zone={time_config['zone_name']}, lt={lt_str})")
            
            # SELL 신호 처리
            elif final == "sell":
                pos = self.pm.get_position(symbol)
                if not pos:
                    return
                
                current_price = self.price_feed.get_price(symbol) if self.price_feed else 0
                
                if Config.MODE == "AUTO":
                    self.ee.market_sell(symbol, pos)
                    logger.info(f"[{symbol}] AUTO 모드 청산 실행")
                else:
                    if self.tb and self.tb.is_ready():
                        entry_price = pos.get("entry_price", 0)
                        pnl_pct = ((current_price - entry_price) / entry_price * 100) if entry_price > 0 else 0
                        
                        self.tb.send_sell_approval_request(
                            symbol=symbol,
                            pos=pos,
                            current_price=current_price,
                            pnl_pct=pnl_pct,
                            reason=f"전략 청산 신호 (strength={strat.get('strength_sum', 0)})"
                        )
                        logger.info(f"[{symbol}] SELL 승인 요청 (PnL={pnl_pct:+.2f}%)")

        except Exception as e:
            logger.error(f"[process ERROR] {symbol}: {e}")
            traceback.print_exc()

    def on_approval_result(self, symbol: str, approved: bool):
        """텔레그램 승인/거절 결과 콜백"""
        self._clear_pending(symbol)
        if not approved:
            self.last_signal_time[symbol] = time.time() - (self.SIGNAL_COOLDOWN - 60)

    def get_cache_stats(self) -> Dict:
        """🆕 v5.3.0: 캐시 통계 조회"""
        return {
            "ai_cache": ai_cache.stats(),
            "btc_context_cache": btc_context_cache.stats(),
        }

    def loop_once(self):
        """메인 루프 1회 실행"""
        try:
            self.refresh_portfolio()
            
            now = time.time()
            expired = [s for s in self.pending_approval 
                      if now - self.last_signal_time.get(s, 0) > 600]
            for s in expired:
                self.pending_approval.discard(s)
            
            for sym in self.active_symbols:
                self.process_symbol(sym)
                
            if self.ee:
                self.ee.check_positions()
                
        except Exception as e:
            logger.error(f"[LOOP ERROR] {e}")

    def run(self):
        """메인 실행"""
        logger.info("[SignalBot v5.3.0] 시작됨 (Phase 1 캐시 모듈 적용)")
        while True:
            self.loop_once()
            time.sleep(Config.LOOP_SLEEP)
