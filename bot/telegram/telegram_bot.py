# -*- coding: utf-8 -*-
"""
Phoenix v5.2.1b — TelegramBot (상세 통계 리포트)

🆕 v5.2.1b 변경:
- /report: 일일 상세 통계 (승률, MDD, 평균 보유시간, 코인별/전략별 성과)
- /weekly: 주간 상세 통계 (월~일, 상세 분석)
- _format_holding_time(): 보유 시간 포맷 헬퍼 함수

🔥 v5.2.0 변경:
- 단타모드 관련 명령어 삭제 (/scalp, /scalp_status)
- scalp_manager 참조 제거
- scalp_sl 핸들러 제거

v5.1.0e 기능:
- _format_price() 함수 전체 적용
- PEPE, BONK 등 저가 코인 "0₩" 표시 문제 해결

v5.1.0c 기능:
- send_error_alert(): 에러 즉시 알림 메서드 추가

v5.1.0a 기능:
- /signal: UI 버튼 방식으로 개선
- /sync: 빗썸 동기화 강화

기존 기능 유지
"""

import asyncio
import json
import os
import subprocess
import time
from datetime import datetime
from typing import Optional, Dict, List

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, BotCommand
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes

from config import Config
from bot.utils.logger import get_logger

logger = get_logger("Telegram")


def _format_price(price: float) -> str:
    """🔥 v5.1.0d: 가격을 적절한 형식으로 포맷팅 (저가 코인 대응)"""
    if price is None or price <= 0:
        return "N/A"
    elif price >= 1000:
        return f"{price:,.0f}"      # 1,234
    elif price >= 1:
        return f"{price:,.2f}"      # 1.23
    elif price >= 0.01:
        return f"{price:.4f}"       # 0.0123
    else:
        return f"{price:.8f}"       # 0.00001234


def _format_holding_time(hours: float) -> str:
    """🆕 v5.2.1b: 보유 시간 포맷팅"""
    if hours is None or hours <= 0:
        return "0분"
    
    total_minutes = int(hours * 60)
    h = total_minutes // 60
    m = total_minutes % 60
    
    if h > 0 and m > 0:
        return f"{h}시간 {m}분"
    elif h > 0:
        return f"{h}시간"
    else:
        return f"{m}분"


STRATEGY_EMOJI = {
    "phoenix": "🟣", "bb": "💙", "vwap": "🟢", "swing": "🔵",
    "scalp": "🟢", "ai": "🤖", "manual": "👤", "pivot": "📍",
    "chase": "🏃", "unknown": "⚪",
}

MARKET_EMOJI = {
    "strong_uptrend": "🚀", "weak_uptrend": "📈", "sideways": "➡️",
    "high_volatility": "⚡", "weak_downtrend": "📉", "strong_downtrend": "🔻",
    "unknown": "❓",
}

BOT_COMMANDS = [
    BotCommand("start", "🔄 봇 재시작"),
    BotCommand("help", "📖 도움말"),
    BotCommand("status", "📊 상태 확인"),
    BotCommand("balance", "💰 잔고 조회"),
    BotCommand("mode", "⚙️ AUTO↔SEMI 전환"),
    BotCommand("positions", "📈 보유 포지션"),
    BotCommand("close", "🔴 수동 청산"),
    BotCommand("close_all", "🔴 전체 청산"),
    BotCommand("queue", "📋 승인 대기 목록"),
    BotCommand("summary", "📊 오늘 포트폴리오"),
    BotCommand("pf_refresh", "🔄 포트폴리오 갱신"),
    BotCommand("signal", "🤖 AI 신호 분석"),
    BotCommand("pivot", "📍 피봇 포인트"),
    BotCommand("chart", "📈 차트 분석"),
    # 🔥 v5.2.0: scalp, scalp_status 삭제됨
    BotCommand("analyze", "🔮 GPT 시장 분석"),
    BotCommand("risk", "⚠️ 리스크 현황"),
    BotCommand("report", "📊 오늘 리포트"),
    BotCommand("weekly", "📊 주간 리포트"),
    BotCommand("backup", "💾 포지션 백업"),
    BotCommand("sync", "🔄 잔고 동기화"),
    BotCommand("reload", "♻️ 설정 리로드"),
    BotCommand("ws", "🔌 WebSocket 상태"),
]

MAJOR_COINS = ["ETH", "XRP", "SOL", "ADA", "LINK", "DOGE"]

# 🆕 v5.1.0a: Signal UI용 코인 목록 (2행씩)
SIGNAL_COINS_ROW1 = ["ETH", "XRP", "SOL", "ADA"]
SIGNAL_COINS_ROW2 = ["LINK", "DOGE", "HBAR", "SUI"]
SIGNAL_COINS_ROW3 = ["ENS", "ONDO", "DOT", "AVAX"]


class TelegramBot:
    """Phoenix v5.1.0c 텔레그램 봇 (에러 알림 강화)"""

    def __init__(self):
        self.token = Config.TELEGRAM_TOKEN
        self.chat_id = Config.TELEGRAM_CHAT_ID

        self.signal_bot = None
        self.execution_engine = None
        self.pm = None
        self.rm = None
        self.trade_logger = None
        self.price_feed = None
        self.pf_opt = None
        self.api = None
        self.strategy = None
        self.chart = None
        # 🔥 v5.2.0: scalp_manager 삭제됨
        self.circuit_breaker = None
        self.position_sync = None

        self._app: Optional[Application] = None
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._ready: bool = False

        self.approval_queue: Dict[int, Dict] = {}
        self._next_id = 1

    def inject_modules(self, signal_bot=None, execution_engine=None, pm=None,
                       rm=None, trade_logger=None, price_feed=None, pf_opt=None,
                       api=None, strategy=None, chart=None,
                       circuit_breaker=None, position_sync=None):  # 🔥 v5.2.0: scalp_manager 삭제
        self.signal_bot = signal_bot
        self.execution_engine = execution_engine
        self.pm = pm
        self.rm = rm
        self.trade_logger = trade_logger
        self.price_feed = price_feed
        self.pf_opt = pf_opt
        self.api = api
        self.strategy = strategy
        self.chart = chart
        # 🔥 v5.2.0: scalp_manager 삭제됨
        self.circuit_breaker = circuit_breaker
        self.position_sync = position_sync

        if signal_bot:
            if not self.api:
                self.api = getattr(signal_bot, 'api', None)
            if not self.strategy:
                self.strategy = getattr(signal_bot, 'strategy', None)
            if not self.price_feed:
                self.price_feed = getattr(signal_bot, 'price_feed', None)

    def is_ready(self) -> bool:
        return bool(self._app and self._loop and self._ready and self.token and self.chat_id)

    def _get_chat_id(self, update: Update) -> Optional[int]:
        if update and update.effective_chat:
            return update.effective_chat.id
        return self.chat_id

    def _get_current_price(self, symbol: str) -> Optional[float]:
        current = None
        if self.price_feed:
            current = self.price_feed.get_price(symbol)
        if not current and self.api:
            try:
                ticker = self.api.fetch_ticker(symbol)
                current = ticker.get("last")
            except:
                pass
        return current

    def _get_held_coins(self) -> List[str]:
        if not self.pm:
            return []
        return list(self.pm.get_all_positions().keys())

    async def send_message(self, text: str, chat_id: Optional[int] = None, reply_markup=None):
        if not self.is_ready():
            return
        try:
            target = chat_id or self.chat_id
            await self._app.bot.send_message(
                chat_id=target, text=text, parse_mode="HTML", reply_markup=reply_markup
            )
        except Exception as e:
            logger.error(f"send_message ERROR: {e}")

    def send_message_sync(self, text: str, reply_markup=None):
        if not self.is_ready():
            return
        async def _send():
            await self.send_message(text, reply_markup=reply_markup)
        try:
            asyncio.run_coroutine_threadsafe(_send(), self._loop)
        except Exception as e:
            logger.error(f"send_message_sync ERROR: {e}")

    async def send_photo(self, img_path: str, caption: str = None, chat_id: Optional[int] = None, reply_markup=None):
        if not self.is_ready():
            return
        try:
            target = chat_id or self.chat_id
            with open(img_path, "rb") as f:
                await self._app.bot.send_photo(
                    chat_id=target, photo=f, caption=caption,
                    parse_mode="HTML", reply_markup=reply_markup
                )
        except Exception as e:
            logger.error(f"send_photo ERROR: {e}")

    # ================================================================
    # 🆕 v5.1.0c: 에러 알림 즉시 전송
    # ================================================================
    def send_error_alert(self, error_type: str, symbol: str = None, 
                         details: str = None, severity: str = "error"):
        """
        🆕 v5.1.0c: 에러 알림 즉시 전송
        
        Args:
            error_type: 에러 종류 (매수 실패, 매도 실패, 가격 조회 실패 등)
            symbol: 관련 코인 (옵션)
            details: 상세 내용
            severity: "error" | "warning" | "critical"
        """
        if not self.is_ready():
            logger.warning(f"[ERROR ALERT] 봇 미준비 - {error_type}: {details}")
            return
        
        emoji_map = {
            "error": "❌",
            "warning": "⚠️", 
            "critical": "🚨"
        }
        emoji = emoji_map.get(severity, "❌")
        
        symbol_str = symbol.replace("/", "-") if symbol else ""
        
        msg = f"{emoji} <b>{error_type}</b>\n\n"
        if symbol_str:
            msg += f"코인: {symbol_str}\n"
        if details:
            msg += f"상세: {details}\n"
        msg += f"\n⏰ {datetime.now().strftime('%H:%M:%S')}"
        
        self.send_message_sync(msg)
        logger.info(f"[ERROR ALERT SENT] {error_type} - {symbol_str} - {details}")

    # ================================================================
    # 승인 요청 (v5.1.0c: 가격 검증 강화)
    # ================================================================
    def send_approval_request(self, symbol: str, signal: str, ai_decision: Dict,
                              strategy: str, current_price: float, krw_amount: float,
                              indicators: Dict = None, **kwargs):
        # 🔧 v5.1.0c: 가격 재조회 강화
        if not current_price or current_price <= 0:
            if self.api:
                try:
                    ticker = self.api.fetch_ticker(symbol)
                    current_price = float(ticker.get("last", 0)) if ticker else 0
                except Exception as e:
                    logger.error(f"[APPROVAL] {symbol} 가격 재조회 실패: {e}")
        
        # 🆕 v5.1.0c: 가격 0원이면 에러 알림 후 차단
        if not current_price or current_price <= 0:
            self.send_error_alert(
                error_type="가격 조회 실패",
                symbol=symbol,
                details="승인 요청 차단됨 - 가격 데이터 없음",
                severity="error"
            )
            logger.error(f"[APPROVAL BLOCKED] {symbol} 가격 0원")
            return
        
        req_id = self._next_id
        self._next_id += 1

        self.approval_queue[req_id] = {
            "id": req_id,
            "symbol": symbol,
            "signal": signal,
            "ai_decision": ai_decision,
            "strategy": strategy,
            "price_at_signal": current_price,
            "krw_amount": krw_amount,
            "created_at": time.time(),
            "indicators": indicators or {},
        }

        strategy_emoji = STRATEGY_EMOJI.get(strategy.lower(), "⚪")
        signal_emoji = "🟢" if signal == "buy" else "🔴" if signal == "sell" else "⚪"
        symbol_display = symbol.replace("/", "-")

        confidence = ai_decision.get("confidence", 0.5)
        tp = ai_decision.get("tp", 0.02)
        sl = ai_decision.get("sl", 0.01)
        reason = ai_decision.get("reason", "")

        position_type = ai_decision.get("position_type", "scalp").upper()
        holding_period = ai_decision.get("holding_period", "수시간")

        msg = (
            f"{signal_emoji}{strategy_emoji} <b>{signal.upper()} 신호</b>\n\n"
            f"<b>{symbol_display}</b>\n"
            f"💰 가격: {_format_price(current_price)}₩\n"
            f"💵 금액: {krw_amount:,.0f}₩\n"
            f"📊 확신도: {confidence*100:.0f}%\n"
            f"🎯 TP: {tp*100:.1f}% / SL: {sl*100:.1f}%\n\n"
            f"📋 포지션: {position_type} ({holding_period})\n"
        )

        if reason:
            msg += f"\n💡 {reason}\n"

        msg += f"\n⏰ {Config.APPROVAL_TIMEOUT_SEC}초 내 결정"

        keyboard = [
            [
                InlineKeyboardButton("✅ 승인", callback_data=f"approve_{req_id}"),
                InlineKeyboardButton("❌ 거절", callback_data=f"reject_{req_id}"),
            ]
        ]
        self.send_message_sync(msg, reply_markup=InlineKeyboardMarkup(keyboard))

    def check_approval_expiry(self):
        now = time.time()
        expired = []
        for req_id, item in list(self.approval_queue.items()):
            if now - item["created_at"] > Config.APPROVAL_TIMEOUT_SEC:
                expired.append(req_id)
        for req_id in expired:
            item = self.approval_queue.pop(req_id, None)
            if item:
                self.send_message_sync(f"⏰ <b>승인 만료</b>\n\n{item['symbol']}")

    # ================================================================
    # 🆕 v5.1.0a: 콜백 핸들러 (signal, sync 추가)
    # ================================================================
    async def button_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        await query.answer()
        data = query.data
        chat_id = self._get_chat_id(update)

        try:
            if data.startswith("approve_"):
                req_id = int(data.split("_")[1])
                await self._handle_approve(req_id, query)
            elif data.startswith("reject_"):
                req_id = int(data.split("_")[1])
                await self._handle_reject(req_id, query)
            elif data.startswith("close_"):
                symbol = data.replace("close_", "")
                await self._handle_close(symbol, query)
            elif data.startswith("sl_approve_"):
                req_id = int(data.split("_")[2])
                await self._handle_sl_approve(req_id, query)
            elif data.startswith("sl_reject_"):
                req_id = int(data.split("_")[2])
                await self._handle_sl_reject(req_id, query)
            elif data.startswith("sell_approve_"):
                req_id = int(data.split("_")[2])
                await self._handle_sell_approve(req_id, query)
            elif data.startswith("sell_reject_"):
                req_id = int(data.split("_")[2])
                await self._handle_sell_reject(req_id, query)
            # 🔥 v5.1.0d: 단타 손절 승인/거절
            # 🔥 v5.2.0: scalp_sl 핸들러 삭제됨
            elif data.startswith("pivot_"):
                coin = data.replace("pivot_", "")
                symbol = f"{coin}/KRW"
                await query.edit_message_text(f"📍 {symbol} 분석 중...")
                await self._show_pivot_analysis(chat_id, symbol)
            elif data.startswith("chart_"):
                coin = data.replace("chart_", "")
                symbol = f"{coin}/KRW"
                await query.edit_message_text(f"📈 {symbol} 차트 생성 중...")
                await self._show_chart(chat_id, symbol)
            elif data.startswith("analyze_"):
                symbol = data.replace("analyze_", "")
                await query.edit_message_text(f"🔮 {symbol} GPT 분석 중...")
                await self._run_analyze(symbol, chat_id)
            # 🆕 v5.1.0a: Signal 콜백
            elif data.startswith("signal_"):
                await self._handle_signal_callback(data, query, chat_id)
            # 🆕 v5.1.0a: Sync 콜백
            elif data.startswith("sync_"):
                await self._handle_sync_callback(data, query, chat_id)
        except Exception as e:
            logger.error(f"button_callback ERROR: {e}")
            await query.edit_message_text(f"❌ 오류: {e}")

    # 🆕 v5.1.0a: Signal 콜백 처리
    async def _handle_signal_callback(self, data: str, query, chat_id: int):
        """Signal 관련 콜백 처리"""
        if data == "signal_scan":
            await query.edit_message_text("🔍 전체 코인 스캔 중...")
            await self._run_signal_scan(chat_id)
        elif data == "signal_positions":
            await query.edit_message_text("📊 보유 포지션 분석 중...")
            await self._run_signal_positions(chat_id)
        elif data.startswith("signal_buy_"):
            symbol = data.replace("signal_buy_", "")
            await self._handle_signal_buy(symbol, query, chat_id)
        elif data.startswith("signal_"):
            coin = data.replace("signal_", "")
            symbol = f"{coin}/KRW"
            await query.edit_message_text(f"🔍 {symbol} 분석 중...")
            await self._run_signal_analysis(symbol, chat_id)

    # 🆕 v5.1.0a: Sync 콜백 처리
    async def _handle_sync_callback(self, data: str, query, chat_id: int):
        """Sync 관련 콜백 처리"""
        if data == "sync_preview":
            await query.edit_message_text("🔍 동기화 상태 확인 중...")
            await self._run_sync_preview(chat_id)
        elif data == "sync_execute":
            await query.edit_message_text("🔄 동기화 실행 중...")
            await self._run_sync_execute(chat_id)

    async def _handle_approve(self, req_id: int, query):
        item = self.approval_queue.pop(req_id, None)
        if not item:
            await query.edit_message_text("⚠️ 이미 처리되었거나 만료된 요청입니다.")
            return

        symbol = item["symbol"]
        ai_decision = item["ai_decision"]
        pf_weight = ai_decision.get("position_weight", 0.2)
        krw_amount = item["krw_amount"]

        current_price = self._get_current_price(symbol)
        price_at_signal = item.get("price_at_signal") or item.get("current_price")
        
        if (not current_price or current_price <= 0) and (not price_at_signal or price_at_signal <= 0):
            await query.edit_message_text(f"❌ {symbol} 가격 조회 실패")
            return

        if current_price and price_at_signal:
            change = abs(current_price - price_at_signal) / price_at_signal
            if change >= Config.APPROVAL_PRICE_CHANGE_LIMIT:
                await query.edit_message_text(
                    f"⚠️ 가격 {change*100:.1f}% 변동 - 신호 무효"
                )
                return

        try:
            if self.execution_engine:
                success = self.execution_engine.market_buy(symbol, krw_amount, ai_decision, pf_weight)
                if success:
                    if self.trade_logger:
                        self.trade_logger.log_entry(
                            symbol=symbol,
                            entry_price=current_price or price_at_signal or 1,
                            qty=krw_amount / max(current_price or price_at_signal or 1, 1),
                            krw_amount=krw_amount,
                            position_weight=pf_weight,
                            ai_decision=ai_decision,
                            market_condition=ai_decision.get("market_condition", "unknown"),
                            position_type=ai_decision.get("position_type", "scalp"),
                            strategy=item.get("strategy", "ai"),
                        )

                    display_price = current_price if current_price else price_at_signal
                    price_text = f"{_format_price(display_price)}₩" if display_price else "확인 중"
                    
                    await query.edit_message_text(
                        f"✅ <b>매수 승인 완료</b>\n\n{symbol}\n금액: {krw_amount:,.0f}₩\n체결가: {price_text}",
                        parse_mode="HTML"
                    )
                else:
                    await query.edit_message_text(f"❌ 매수 실행 실패: {symbol}")
            else:
                await query.edit_message_text("❌ ExecutionEngine 미연결")
        except Exception as e:
            await query.edit_message_text(f"❌ 오류: {e}")

    async def _handle_reject(self, req_id: int, query):
        item = self.approval_queue.pop(req_id, None)
        if not item:
            await query.edit_message_text("⚠️ 이미 처리되었거나 만료된 요청입니다.")
            return
        await query.edit_message_text(f"❌ <b>거절됨</b>\n\n{item['symbol']}", parse_mode="HTML")

    async def _handle_close(self, symbol: str, query):
        pos = self.pm.get_position(symbol) if self.pm else None
        if not pos:
            await query.edit_message_text(f"⚠️ {symbol} 포지션 없음")
            return
        try:
            if self.execution_engine:
                success = self.execution_engine.close_position(symbol, pos, reason="수동 청산")
                if success:
                    await query.edit_message_text(f"✅ <b>청산 완료</b>\n\n{symbol}", parse_mode="HTML")
                else:
                    await query.edit_message_text(f"❌ 청산 실패: {symbol}")
            else:
                await query.edit_message_text("❌ ExecutionEngine 미연결")
        except Exception as e:
            await query.edit_message_text(f"❌ 오류: {e}")

    # ================================================================
    # 손절 승인 요청 (v5.1.0 - 중복 방지 연동)
    # ================================================================
    def send_sl_approval_request(self, symbol: str, pos: Dict, current_price: float, 
                                   reason: str, sl_rationale: Dict = None):
        """SL 승인 요청 (v5.1.0: 전략적 근거 포함)"""
        req_id = self._next_id
        self._next_id += 1

        entry_price = pos.get("entry_price", 0)
        qty = pos.get("qty", 0)
        pnl_pct = (current_price - entry_price) / max(entry_price, 1) * 100 if entry_price else 0
        pnl_krw = (current_price - entry_price) * qty

        self.approval_queue[req_id] = {
            "id": req_id,
            "type": "sl",
            "symbol": symbol,
            "pos": pos,
            "current_price": current_price,
            "reason": reason,
            "sl_rationale": sl_rationale,
            "created_at": time.time(),
        }

        symbol_display = symbol.replace("/", "-")

        # 기본 메시지
        msg = (
            f"🔴 <b>손절 승인 요청</b>\n\n"
            f"<b>{symbol_display}</b>\n"
            f"진입가: {_format_price(entry_price)}₩\n"
            f"현재가: {_format_price(current_price)}₩\n"
            f"손익: <b>{pnl_pct:+.2f}%</b> ({pnl_krw:+,.0f}₩)\n\n"
            f"사유: {reason}\n"
        )
        
        # 🆕 v5.1.0: 전략적 근거 추가
        if sl_rationale:
            recommendation = sl_rationale.get("recommendation", "")
            confidence = sl_rationale.get("confidence", 0)
            rationale = sl_rationale.get("rationale", "")
            recovery_chance = sl_rationale.get("recovery_chance", 0)
            
            rec_emoji = "🔴" if recommendation == "손절" else "⏸"
            msg += (
                f"\n<b>📊 AI 분석</b>\n"
                f"{rec_emoji} 추천: {recommendation} (확신도 {confidence*100:.0f}%)\n"
                f"📈 회복 가능성: {recovery_chance*100:.0f}%\n"
            )
            if rationale:
                msg += f"💡 {rationale}\n"
        
        msg += f"\n⏰ 손절하시겠습니까?"

        keyboard = [
            [
                InlineKeyboardButton("🔴 손절", callback_data=f"sl_approve_{req_id}"),
                InlineKeyboardButton("⏸ 홀드", callback_data=f"sl_reject_{req_id}"),
            ]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)

        self.send_message_sync(msg, reply_markup=reply_markup)

    # 🔥 v5.1.0: SL 승인 - pending 해제
    async def _handle_sl_approve(self, req_id: int, query):
        item = self.approval_queue.pop(req_id, None)
        if not item:
            await query.edit_message_text("⚠️ 이미 처리되었거나 만료된 요청입니다.")
            return

        symbol = item["symbol"]
        pos = item["pos"]

        try:
            if self.execution_engine:
                # 🔥 pending 먼저 해제 (market_sell에서도 하지만 명시적으로)
                self.execution_engine.clear_sl_pending(symbol)
                
                success = self.execution_engine.market_sell(symbol, pos, reason="손절 승인")
                if success:
                    await query.edit_message_text(f"🔴 <b>손절 완료</b>\n\n{symbol}", parse_mode="HTML")
                else:
                    await query.edit_message_text(f"❌ 손절 실패: {symbol}")
            else:
                await query.edit_message_text("❌ ExecutionEngine 미연결")
        except Exception as e:
            await query.edit_message_text(f"❌ 오류: {e}")

    # 🔥 v5.1.0: SL 거절 - pending 해제
    async def _handle_sl_reject(self, req_id: int, query):
        """SL 홀드 처리 - 4시간 동안 재알림 금지"""
        item = self.approval_queue.pop(req_id, None)
        if not item:
            await query.edit_message_text("⚠️ 이미 처리되었거나 만료된 요청입니다.")
            return

        symbol = item["symbol"]
        
        # 🔥 거절 시에도 pending 해제
        if self.execution_engine:
            self.execution_engine.clear_sl_pending(symbol)
        
        # 🆕 v5.1.0: SL 홀드 설정 (4시간)
        hold_until = None
        if self.pm and hasattr(self.pm, 'set_sl_hold'):
            hold_until = self.pm.set_sl_hold(symbol)
            hold_time = hold_until.strftime("%H:%M") if hold_until else "N/A"
            msg = (
                f"⏸ <b>SL 홀드 설정</b>\n\n"
                f"<b>{symbol}</b>\n"
                f"⏰ {Config.SL_HOLD_HOURS}시간 동안 재알림 금지\n"
                f"만료 시각: {hold_time}\n\n"
                f"💡 가격이 SL 이하로 유지되면 만료 후 재알림됩니다."
            )
        else:
            msg = f"⏸ <b>홀드 유지</b>\n\n{symbol}"
        
        await query.edit_message_text(msg, parse_mode="HTML")

    # 🔥 v5.2.0: _handle_scalp_sl_approve, _handle_scalp_sl_reject 함수 삭제됨

    def send_sell_approval_request(self, symbol: str, pos: Dict, current_price: float, 
                                    pnl_pct: float, reason: str = ""):
        req_id = self._next_id
        self._next_id += 1

        entry_price = pos.get("entry_price", 0)
        qty = pos.get("qty", 0)
        if entry_price <= 0:
            entry_price = current_price or 1
        pnl_krw = (current_price - entry_price) * qty

        self.approval_queue[req_id] = {
            "id": req_id,
            "type": "strategy_sell",
            "symbol": symbol,
            "pos": pos,
            "current_price": current_price,
            "reason": reason,
            "created_at": time.time(),
        }

        symbol_display = symbol.replace("/", "-")
        pnl_emoji = "🟢" if pnl_pct >= 0 else "🔴"

        msg = (
            f"📉 <b>전략 청산 신호</b>\n\n"
            f"<b>{symbol_display}</b>\n"
            f"진입가: {_format_price(entry_price)}₩\n"
            f"현재가: {_format_price(current_price)}₩\n"
            f"손익: {pnl_emoji} <b>{pnl_pct:+.2f}%</b> ({pnl_krw:+,.0f}₩)\n\n"
            f"💡 {reason}\n\n⏰ 청산하시겠습니까?"
        )

        keyboard = [
            [
                InlineKeyboardButton("📉 청산", callback_data=f"sell_approve_{req_id}"),
                InlineKeyboardButton("⏸ 홀드", callback_data=f"sell_reject_{req_id}"),
            ]
        ]
        self.send_message_sync(msg, reply_markup=InlineKeyboardMarkup(keyboard))

    async def _handle_sell_approve(self, req_id: int, query):
        item = self.approval_queue.pop(req_id, None)
        if not item:
            await query.edit_message_text("⚠️ 이미 처리되었거나 만료된 요청입니다.")
            return

        symbol = item["symbol"]
        pos = item["pos"]

        try:
            if self.execution_engine:
                success = self.execution_engine.market_sell(symbol, pos, reason="전략 청산 승인")
                if success:
                    await query.edit_message_text(f"📉 <b>청산 완료</b>\n\n{symbol}", parse_mode="HTML")
                else:
                    await query.edit_message_text(f"❌ 청산 실패: {symbol}")
        except Exception as e:
            await query.edit_message_text(f"❌ 오류: {e}")

    async def _handle_sell_reject(self, req_id: int, query):
        item = self.approval_queue.pop(req_id, None)
        if not item:
            await query.edit_message_text("⚠️ 이미 처리되었거나 만료된 요청입니다.")
            return
        await query.edit_message_text(f"⏸ <b>홀드 유지</b>\n\n{item['symbol']}", parse_mode="HTML")

    def send_trade_notification(self, trade_type: str, symbol: str, price: float,
                                 qty: float, pnl_pct: float = None, pnl_krw: float = None, reason: str = ""):
        symbol_display = symbol.replace("/", "-")
        price_str = _format_price(price)
        if trade_type == "buy":
            msg = f"✅ <b>매수 체결</b>\n\n{symbol_display} @ {price_str}₩\n수량: {qty:.4f}"
        elif trade_type in ["sell", "tp", "sl"]:
            emoji = "🟢" if pnl_krw and pnl_krw >= 0 else "🔴"
            label = {"sell": "매도", "tp": "익절", "sl": "손절"}.get(trade_type, "매도")
            msg = f"{emoji} <b>{label} 체결</b>\n\n{symbol_display} @ {price_str}₩"
            if pnl_pct is not None:
                msg += f"\n수익률: <b>{pnl_pct:+.2f}%</b>"
            if pnl_krw is not None:
                msg += f"\n손익: <b>{pnl_krw:+,.0f}₩</b>"
        else:
            msg = f"📌 {symbol_display} @ {price_str}₩"
        self.send_message_sync(msg)

    def send_daily_report(self, summary: Dict):
        total_trades = summary.get("total_trades", 0)
        wins = summary.get("wins", 0)
        losses = summary.get("losses", 0)
        total_pnl = summary.get("total_pnl_krw", 0)
        win_rate = (wins / total_trades * 100) if total_trades > 0 else 0
        emoji = "🟢" if total_pnl >= 0 else "🔴"

        msg = (
            f"📊 <b>일일 리포트</b>\n\n"
            f"거래: {total_trades}건 (승 {wins} / 패 {losses})\n"
            f"승률: {win_rate:.1f}%\n"
            f"손익: {emoji} <b>{total_pnl:+,.0f}₩</b>"
        )
        self.send_message_sync(msg)

    # ================================================================
    # 명령어 핸들러
    # ================================================================
    async def cmd_start(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        chat_id = self._get_chat_id(update)
        await self.send_message("🔄 <b>Phoenix 봇 재시작 중...</b>", chat_id=chat_id)
        
        async def _restart():
            await asyncio.sleep(1)
            try:
                subprocess.run(["systemctl", "restart", "phoenix_v5.service"], capture_output=True, timeout=10)
            except Exception as e:
                logger.error(f"[RESTART ERROR] {e}")
        
        asyncio.create_task(_restart())

    async def cmd_help(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        chat_id = self._get_chat_id(update)
        msg = (
            "<b>📖 Phoenix v5.1.0c 명령어</b>\n\n"
            "<b>📊 기본</b>\n"
            "/start - 봇 재시작\n"
            "/status - 상태 조회\n"
            "/balance - 잔고 조회\n"
            "/mode - AUTO↔SEMI 전환\n\n"
            "<b>💰 포지션</b>\n"
            "/positions - 포지션 목록\n"
            "/close - 수동 청산\n"
            "/close_all - 전체 청산\n"
            "/sync - 빗썸 동기화\n\n"
            "<b>📈 분석</b>\n"
            "/signal - AI 신호 분석\n"
            "/pivot - 피봇 포인트\n"
            "/chart - 차트 분석\n"
            "/analyze - GPT 분석\n\n"
            "<b>📊 리포트</b>\n"
            "/report - 오늘 리포트\n"
            "/weekly - 주간 리포트"
        )
        await self.send_message(msg, chat_id=chat_id)

    async def cmd_status(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        chat_id = self._get_chat_id(update)
        mode = Config.MODE
        pos_cnt = len(self.pm.positions) if self.pm and hasattr(self.pm, 'positions') else 0
        queue_cnt = len(self.approval_queue)

        krw_balance = 0
        if self.api:
            try:
                bal = self.api.fetch_balance()
                krw_balance = bal.get("KRW", {}).get("free", 0)
            except:
                pass

        total_value = 0
        if self.rm:
            try:
                total_value = self.rm.get_total_capital()
            except:
                pass

        # 🔥 v5.2.0: scalp_status 삭제됨

        ws_status = "❓"
        if self.price_feed:
            try:
                if hasattr(self.price_feed, 'get_health_status'):
                    health = self.price_feed.get_health_status()
                    connected = health.get("connected", False)
                    last_age = health.get("last_update_age_sec", 999)
                    reconnects = health.get("reconnect_count", 0)
                    if connected and last_age < 60:
                        ws_status = f"🟢 정상 ({last_age:.0f}초, 재연결 {reconnects}회)"
                    elif connected:
                        ws_status = f"🟡 지연 ({last_age:.0f}초)"
                    else:
                        ws_status = "🔴 끊김"
            except:
                pass

        msg = (
            f"<b>📊 Phoenix v5.2.0 상태</b>\n\n"
            f"⚙️ 모드: <b>{mode}</b>\n"
            f"🔌 WebSocket: <b>{ws_status}</b>\n"
            f"💰 가용 KRW: <b>{krw_balance:,.0f}₩</b>\n"
            f"📈 총 자본: <b>{total_value:,.0f}₩</b>\n"
            f"📊 포지션: <b>{pos_cnt}개</b>\n"
            f"🔔 승인 대기: <b>{queue_cnt}개</b>"
        )
        await self.send_message(msg, chat_id=chat_id)

    async def cmd_balance(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        chat_id = self._get_chat_id(update)
        if not self.api:
            await self.send_message("❌ API 미연결", chat_id=chat_id)
            return
        try:
            bal = self.api.fetch_balance()
            krw_free = bal.get("KRW", {}).get("free", 0)
            krw_total = bal.get("KRW", {}).get("total", 0)
            msg = f"<b>💰 잔고</b>\n\n총: <b>{krw_total:,.0f}₩</b>\n가용: <b>{krw_free:,.0f}₩</b>"
            await self.send_message(msg, chat_id=chat_id)
        except Exception as e:
            await self.send_message(f"❌ 잔고 조회 실패: {e}", chat_id=chat_id)

    async def cmd_mode(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        chat_id = self._get_chat_id(update)
        old_mode = Config.MODE
        Config.MODE = "SEMI" if Config.MODE == "AUTO" else "AUTO"
        await self.send_message(f"✅ 모드 변경: {old_mode} → <b>{Config.MODE}</b>", chat_id=chat_id)

    async def cmd_positions(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        chat_id = self._get_chat_id(update)
        if not self.pm:
            await self.send_message("❌ PositionManager 미연결", chat_id=chat_id)
            return

        positions = self.pm.get_all_positions()
        if not positions:
            await self.send_message("📭 보유 포지션 없음", chat_id=chat_id)
            return

        msg = "📊 <b>보유 포지션</b>\n\n"
        total_invested = 0
        total_pnl_krw = 0

        for symbol, pos in positions.items():
            entry = pos.get("entry_price", 0)
            qty = pos.get("qty", 0)
            invested = entry * qty
            total_invested += invested

            current = self._get_current_price(symbol)
            pnl_pct = 0
            pnl_krw = 0
            if current and entry:
                pnl_pct = (current - entry) / entry * 100
                pnl_krw = (current - entry) * qty
                total_pnl_krw += pnl_krw

            emoji = "🟢" if pnl_pct >= 0 else "🔴"
            symbol_display = symbol.replace("/", "-")
            
            # 🔥 v5.1.0d: 저가 코인 가격 포맷팅 수정
            entry_str = _format_price(entry) if entry else "N/A"
            current_str = _format_price(current) if current else "N/A"

            position_type = pos.get("position_type", "").upper()
            holding_period = pos.get("holding_period", "")

            type_str = f" {position_type}" if position_type else ""
            strat_line = f"⏱{holding_period}\n" if holding_period else ""

            msg += (
                f"{emoji}<b>{type_str} {symbol_display}</b>\n"
                f"진입: {entry_str}₩ | 현재: {current_str}₩\n"
                f"투자: {invested:,.0f}₩ | 손익: <b>{pnl_krw:+,.0f}₩</b> ({pnl_pct:+.2f}%)\n"
                f"{strat_line}\n"
            )

        total_emoji = "🟢" if total_pnl_krw >= 0 else "🔴"
        total_pnl_pct = (total_pnl_krw / total_invested * 100) if total_invested > 0 else 0
        
        msg += (
            f"━━━━━━━━━━━━━━━━━━\n"
            f"💰 총 투자: <b>{total_invested:,.0f}₩</b>\n"
            f"{total_emoji} 총 손익: <b>{total_pnl_krw:+,.0f}₩</b> ({total_pnl_pct:+.2f}%)"
        )

        keyboard = []
        for symbol in positions.keys():
            btn_text = f"🔴 {symbol.replace('/KRW', '')} 청산"
            keyboard.append([InlineKeyboardButton(btn_text, callback_data=f"close_{symbol}")])

        reply_markup = InlineKeyboardMarkup(keyboard) if keyboard else None
        await self.send_message(msg, chat_id=chat_id, reply_markup=reply_markup)

    async def cmd_close(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        chat_id = self._get_chat_id(update)
        if not (self.pm and self.execution_engine):
            await self.send_message("❌ 모듈 미연결", chat_id=chat_id)
            return

        if len(context.args) > 0:
            symbol = context.args[0].upper()
            if "/" not in symbol:
                symbol = f"{symbol}/KRW"
            pos = self.pm.get_position(symbol)
            if not pos:
                await self.send_message(f"❌ {symbol} 포지션 없음", chat_id=chat_id)
                return
            try:
                self.execution_engine.close_position(symbol, pos, reason="수동 청산")
                await self.send_message(f"✅ {symbol} 청산 완료", chat_id=chat_id)
            except Exception as e:
                await self.send_message(f"❌ 청산 실패: {e}", chat_id=chat_id)
            return

        positions = self.pm.get_all_positions()
        if not positions:
            await self.send_message("📭 청산할 포지션 없음", chat_id=chat_id)
            return

        keyboard = []
        for symbol, pos in positions.items():
            coin = symbol.replace("/KRW", "")
            entry = pos.get("entry_price", 0)
            current = self._get_current_price(symbol) or entry
            pnl_pct = (current - entry) / entry * 100 if entry > 0 else 0
            emoji = "🟢" if pnl_pct >= 0 else "🔴"
            keyboard.append([InlineKeyboardButton(f"{emoji} {coin} ({pnl_pct:+.1f}%)", callback_data=f"close_{symbol}")])

        await self.send_message("🔴 <b>청산할 코인 선택</b>", chat_id=chat_id, reply_markup=InlineKeyboardMarkup(keyboard))

    async def cmd_close_all(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        chat_id = self._get_chat_id(update)
        if not (self.pm and self.execution_engine):
            await self.send_message("❌ 모듈 미연결", chat_id=chat_id)
            return

        positions = self.pm.get_all_positions()
        if not positions:
            await self.send_message("📊 청산할 포지션 없음", chat_id=chat_id)
            return

        closed = []
        for sym, pos in list(positions.items()):
            try:
                self.execution_engine.close_position(sym, pos, reason="전체 청산")
                closed.append(sym.replace("/KRW", ""))
            except:
                pass

        await self.send_message(f"✅ 청산 완료: {', '.join(closed)}", chat_id=chat_id)

    async def cmd_queue(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        chat_id = self._get_chat_id(update)
        if not self.approval_queue:
            await self.send_message("📋 승인 대기 목록이 비어 있습니다.", chat_id=chat_id)
            return

        msg = "<b>📋 승인 대기 목록</b>\n\n"
        buttons = []
        for req_id, item in self.approval_queue.items():
            symbol = item['symbol'].replace("/", "-")
            elapsed = int(time.time() - item['created_at'])
            req_type = item.get('type', 'buy')
            
            if req_type == 'sl':
                msg += f"<b>#{req_id} 🔴 SL {symbol}</b>\n경과: {elapsed}초\n\n"
                buttons.append([
                    InlineKeyboardButton(f"🔴 #{req_id} 손절", callback_data=f"sl_approve_{req_id}"),
                    InlineKeyboardButton(f"⏸ #{req_id} 홀드", callback_data=f"sl_reject_{req_id}"),
                ])
            else:
                krw = item.get('krw_amount', 0)
                msg += f"<b>#{req_id} {symbol}</b>\n금액: {krw:,.0f}₩ | 경과: {elapsed}초\n\n"
                buttons.append([
                    InlineKeyboardButton(f"✅ #{req_id} 승인", callback_data=f"approve_{req_id}"),
                    InlineKeyboardButton(f"❌ #{req_id} 거절", callback_data=f"reject_{req_id}"),
                ])

        reply_markup = InlineKeyboardMarkup(buttons) if buttons else None
        await self.send_message(msg, chat_id=chat_id, reply_markup=reply_markup)

    async def cmd_summary(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        chat_id = self._get_chat_id(update)
        if not self.signal_bot or not hasattr(self.signal_bot, 'weight_map'):
            await self.send_message("📊 포트폴리오 미계산", chat_id=chat_id)
            return

        pf = self.signal_bot.weight_map
        if not pf:
            await self.send_message("📊 포트폴리오 미계산", chat_id=chat_id)
            return

        msg = "<b>📊 오늘의 포트폴리오</b>\n\n"
        for sym, w in sorted(pf.items(), key=lambda x: -x[1]):
            bar = "█" * int(w * 20)
            msg += f"{sym.replace('/KRW', '')}: <b>{w*100:.1f}%</b> {bar}\n"

        await self.send_message(msg, chat_id=chat_id)

    async def cmd_pf_refresh(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        chat_id = self._get_chat_id(update)
        if not self.signal_bot:
            await self.send_message("❌ SignalBot 미연결", chat_id=chat_id)
            return
        try:
            await self.send_message("🔄 갱신 중...", chat_id=chat_id)
            self.signal_bot.refresh_portfolio(force=True)
            await self.cmd_summary(update, context)
        except Exception as e:
            await self.send_message(f"❌ 갱신 실패: {e}", chat_id=chat_id)

    # ================================================================
    # 🆕 v5.1.0a: /signal UI 방식 개선
    # ================================================================
    async def cmd_signal(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """AI 신호 분석 - UI 버튼 방식"""
        chat_id = self._get_chat_id(update)
        
        # 인자가 있으면 직접 분석
        if len(context.args) > 0:
            symbol = context.args[0].upper()
            if "/" not in symbol:
                symbol = f"{symbol}/KRW"
            await self.send_message(f"🔍 {symbol} 분석 중...", chat_id=chat_id)
            await self._run_signal_analysis(symbol, chat_id)
            return
        
        # UI 버튼 표시
        msg = "<b>🤖 AI 신호 분석</b>\n\n코인을 선택하세요:"
        
        keyboard = [
            # 1행: 주요 코인
            [InlineKeyboardButton(coin, callback_data=f"signal_{coin}") for coin in SIGNAL_COINS_ROW1],
            # 2행
            [InlineKeyboardButton(coin, callback_data=f"signal_{coin}") for coin in SIGNAL_COINS_ROW2],
            # 3행
            [InlineKeyboardButton(coin, callback_data=f"signal_{coin}") for coin in SIGNAL_COINS_ROW3],
            # 4행: 특수 기능
            [
                InlineKeyboardButton("📊 보유 분석", callback_data="signal_positions"),
                InlineKeyboardButton("🔍 전체 스캔", callback_data="signal_scan"),
            ],
        ]
        
        await self.send_message(msg, chat_id=chat_id, reply_markup=InlineKeyboardMarkup(keyboard))

    async def _run_signal_analysis(self, symbol: str, chat_id: int):
        """단일 코인 신호 분석 실행"""
        if not self.signal_bot:
            await self.send_message("❌ SignalBot 미연결", chat_id=chat_id)
            return

        try:
            df30, df15, df5 = self.signal_bot.load_ohlcv(symbol)
            if df30 is None:
                await self.send_message(f"❌ {symbol} 데이터 없음", chat_id=chat_id)
                return

            strat = {"decision": "hold", "strength_sum": 0}
            if self.strategy:
                strat = self.strategy.get_signal(symbol, df30, df15, df5)

            ai = self.signal_bot.get_ai_decision(symbol, df30, df15, df5)
            current_price = self._get_current_price(symbol) or 0

            strat_decision = strat.get("decision", "hold")
            ai_decision = ai.get("decision", "hold")
            strength = strat.get("strength_sum", 0)
            confidence = ai.get("confidence", 0.5)
            
            strat_emoji = {"buy": "🟢", "sell": "🔴", "hold": "⚪"}.get(strat_decision, "⚪")
            ai_emoji = {"buy": "🟢", "sell": "🔴", "hold": "⚪"}.get(ai_decision, "⚪")

            # 최종 신호 판단
            final_signal = "hold"
            if strat_decision == "buy" and ai_decision == "buy":
                final_signal = "buy"
            elif strat_decision == "sell" or ai_decision == "sell":
                final_signal = "sell"
            
            final_emoji = {"buy": "🟢 매수", "sell": "🔴 매도", "hold": "⚪ 관망"}.get(final_signal, "⚪ 관망")

            msg = (
                f"<b>🤖 {symbol.replace('/', '-')} 신호</b>\n\n"
                f"💰 현재가: <b>{_format_price(current_price)}₩</b>\n\n"
                f"<b>📊 전략 분석</b>\n"
                f"{strat_emoji} {strat_decision.upper()} (강도: {strength})\n\n"
                f"<b>🧠 AI 분석</b>\n"
                f"{ai_emoji} {ai_decision.upper()}\n"
                f"확신도: {confidence*100:.0f}%\n"
                f"TP: {ai.get('tp', 0.02)*100:.1f}% | SL: {ai.get('sl', 0.01)*100:.1f}%\n\n"
                f"━━━━━━━━━━━━━━━\n"
                f"<b>📍 최종: {final_emoji}</b>"
            )
            
            # BUY 신호일 때 매수 버튼 추가
            keyboard = None
            if final_signal == "buy" and strength >= Config.SIGNAL_THRESHOLD:
                keyboard = [[InlineKeyboardButton(f"💰 {symbol.replace('/KRW', '')} 매수하기", callback_data=f"signal_buy_{symbol}")]]
            
            await self.send_message(msg, chat_id=chat_id, reply_markup=InlineKeyboardMarkup(keyboard) if keyboard else None)
            
        except Exception as e:
            await self.send_message(f"❌ 분석 실패: {e}", chat_id=chat_id)

    async def _run_signal_scan(self, chat_id: int):
        """전체 코인 스캔"""
        if not self.signal_bot:
            await self.send_message("❌ SignalBot 미연결", chat_id=chat_id)
            return
        
        try:
            buy_signals = []
            sell_signals = []
            hold_signals = []
            
            for symbol in Config.COIN_POOL[:15]:  # 상위 15개만 스캔
                try:
                    df30, df15, df5 = self.signal_bot.load_ohlcv(symbol)
                    if df30 is None:
                        continue
                    
                    strat = {"decision": "hold", "strength_sum": 0}
                    if self.strategy:
                        strat = self.strategy.get_signal(symbol, df30, df15, df5)
                    
                    ai = self.signal_bot.get_ai_decision(symbol, df30, df15, df5)
                    
                    coin = symbol.replace("/KRW", "")
                    strength = strat.get("strength_sum", 0)
                    strat_dec = strat.get("decision", "hold")
                    ai_dec = ai.get("decision", "hold")
                    confidence = ai.get("confidence", 0.5)
                    
                    info = f"{coin}: 강도 {strength}, AI {ai_dec.upper()} ({confidence*100:.0f}%)"
                    
                    if strat_dec == "buy" and ai_dec == "buy" and strength >= Config.SIGNAL_THRESHOLD:
                        buy_signals.append(info)
                    elif strat_dec == "sell" or ai_dec == "sell":
                        sell_signals.append(info)
                    else:
                        hold_signals.append(coin)
                except:
                    continue
            
            msg = "<b>🔍 전체 스캔 결과</b>\n\n"
            
            if buy_signals:
                msg += "<b>🟢 매수 신호</b>\n"
                for s in buy_signals:
                    msg += f"  • {s}\n"
                msg += "\n"
            
            if sell_signals:
                msg += "<b>🔴 매도 신호</b>\n"
                for s in sell_signals:
                    msg += f"  • {s}\n"
                msg += "\n"
            
            msg += f"<b>⚪ 관망</b>: {', '.join(hold_signals[:10])}"
            if len(hold_signals) > 10:
                msg += f" 외 {len(hold_signals)-10}개"
            
            await self.send_message(msg, chat_id=chat_id)
            
        except Exception as e:
            await self.send_message(f"❌ 스캔 실패: {e}", chat_id=chat_id)

    async def _run_signal_positions(self, chat_id: int):
        """보유 포지션 신호 분석"""
        if not (self.pm and self.signal_bot):
            await self.send_message("❌ 모듈 미연결", chat_id=chat_id)
            return
        
        positions = self.pm.get_all_positions()
        if not positions:
            await self.send_message("📭 보유 포지션 없음", chat_id=chat_id)
            return
        
        try:
            msg = "<b>📊 보유 포지션 신호</b>\n\n"
            
            for symbol, pos in positions.items():
                try:
                    df30, df15, df5 = self.signal_bot.load_ohlcv(symbol)
                    if df30 is None:
                        continue
                    
                    ai = self.signal_bot.get_ai_decision(symbol, df30, df15, df5)
                    current = self._get_current_price(symbol) or 0
                    entry = pos.get("entry_price", 0)
                    pnl_pct = (current - entry) / entry * 100 if entry > 0 else 0
                    
                    ai_dec = ai.get("decision", "hold")
                    confidence = ai.get("confidence", 0.5)
                    
                    pnl_emoji = "🟢" if pnl_pct >= 0 else "🔴"
                    ai_emoji = {"buy": "🟢 추매", "sell": "🔴 청산", "hold": "⚪ 유지"}.get(ai_dec, "⚪")
                    
                    coin = symbol.replace("/KRW", "")
                    msg += (
                        f"<b>{coin}</b> {pnl_emoji} {pnl_pct:+.2f}%\n"
                        f"  AI: {ai_emoji} ({confidence*100:.0f}%)\n\n"
                    )
                except:
                    continue
            
            await self.send_message(msg, chat_id=chat_id)
            
        except Exception as e:
            await self.send_message(f"❌ 분석 실패: {e}", chat_id=chat_id)

    async def _handle_signal_buy(self, symbol: str, query, chat_id: int):
        """신호 분석 후 매수 요청"""
        if not self.signal_bot:
            await query.edit_message_text("❌ SignalBot 미연결")
            return
        
        try:
            df30, df15, df5 = self.signal_bot.load_ohlcv(symbol)
            ai = self.signal_bot.get_ai_decision(symbol, df30, df15, df5)
            current_price = self._get_current_price(symbol) or 0
            
            if current_price <= 0:
                await query.edit_message_text(f"❌ {symbol} 가격 조회 실패")
                return
            
            # 매수 금액 계산
            krw_amount = 50000  # 기본 5만원
            if self.rm:
                pf_weight = ai.get("position_weight", 0.2)
                krw_amount = self.rm.get_trade_amount(symbol, pf_weight)
            
            # 승인 요청 생성
            self.send_approval_request(
                symbol=symbol,
                signal="buy",
                ai_decision=ai,
                strategy="signal_ui",
                current_price=current_price,
                krw_amount=krw_amount,
            )
            
            await query.edit_message_text(f"📤 {symbol} 매수 승인 요청 전송됨\n\n금액: {krw_amount:,.0f}₩", parse_mode="HTML")
            
        except Exception as e:
            await query.edit_message_text(f"❌ 오류: {e}")

    # ================================================================
    # 🆕 v5.1.0a: /sync 강화 (미리보기 + 실행)
    # ================================================================
    async def cmd_sync(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """빗썸 동기화 - UI 버튼 방식"""
        chat_id = self._get_chat_id(update)
        if not (self.pm and self.api):
            await self.send_message("❌ 모듈 미연결", chat_id=chat_id)
            return
        
        # 미리보기 먼저 표시
        await self._run_sync_preview(chat_id)

    async def _run_sync_preview(self, chat_id: int):
        """동기화 미리보기"""
        try:
            bal = self.api.fetch_balance()
            positions = self.pm.get_all_positions()
            
            # 빗썸 보유 코인
            exchange_coins = {}
            for coin, data in bal.items():
                if coin in ["KRW", "free", "used", "total", "info", "timestamp", "datetime"]:
                    continue
                total_qty = data.get("total", 0) if isinstance(data, dict) else 0
                if total_qty > 0:
                    symbol = f"{coin}/KRW"
                    try:
                        ticker = self.api.fetch_ticker(symbol)
                        price = ticker.get("last", 0)
                        value = total_qty * price
                        if value >= Config.MIN_ORDER_AMOUNT:
                            exchange_coins[symbol] = {"qty": total_qty, "price": price, "value": value}
                    except:
                        pass
            
            # 봇 포지션
            bot_symbols = set(positions.keys())
            exchange_symbols = set(exchange_coins.keys())
            
            only_exchange = exchange_symbols - bot_symbols
            only_bot = bot_symbols - exchange_symbols
            matched = exchange_symbols & bot_symbols
            
            msg = "<b>🔄 동기화 미리보기</b>\n\n"
            
            if only_exchange:
                msg += "<b>➕ 추가 예정 (빗썸에만 있음)</b>\n"
                for sym in only_exchange:
                    coin = sym.replace("/KRW", "")
                    data = exchange_coins[sym]
                    msg += f"  • {coin}: {data['qty']:.4f}개 ({data['value']:,.0f}₩)\n"
                msg += "\n"
            
            if only_bot:
                msg += "<b>➖ 삭제 예정 (봇에만 있음)</b>\n"
                for sym in only_bot:
                    coin = sym.replace("/KRW", "")
                    msg += f"  • {coin}\n"
                msg += "\n"
            
            if matched:
                msg += f"<b>✅ 일치</b>: {len(matched)}개\n\n"
            
            if not only_exchange and not only_bot:
                msg += "✅ 이미 동기화 상태입니다!"
                await self.send_message(msg, chat_id=chat_id)
                return
            
            msg += "동기화를 실행하시겠습니까?"
            
            keyboard = [[
                InlineKeyboardButton("✅ 실행", callback_data="sync_execute"),
                InlineKeyboardButton("❌ 취소", callback_data="sync_cancel"),
            ]]
            
            await self.send_message(msg, chat_id=chat_id, reply_markup=InlineKeyboardMarkup(keyboard))
            
        except Exception as e:
            await self.send_message(f"❌ 미리보기 실패: {e}", chat_id=chat_id)

    async def _run_sync_execute(self, chat_id: int):
        """동기화 실행"""
        try:
            # 🔥 v5.2.0: scalp_pos 관련 코드 삭제됨
            
            # 동기화 실행
            if hasattr(self.pm, 'sync_with_exchange'):
                report = self.pm.sync_with_exchange(self.api, {})  # 빈 dict 전달
            else:
                # 기존 방식 fallback
                report = await self._sync_legacy()
            
            # 결과 메시지
            msg = "🔄 <b>동기화 완료</b>\n\n"
            
            if report.get("added"):
                msg += "<b>➕ 추가됨</b>\n"
                for item in report["added"]:
                    msg += f"  • {item['symbol']}: {item['qty']:.4f}개 @ {item['avg_price']:,.0f}₩\n"
                msg += "\n"
            
            if report.get("removed"):
                msg += "<b>➖ 삭제됨</b>\n"
                for item in report["removed"]:
                    msg += f"  • {item['symbol']}\n"
                msg += "\n"
            
            if report.get("matched"):
                msg += f"<b>✅ 일치</b>: {len(report['matched'])}개\n"
            
            if report.get("errors"):
                msg += f"\n⚠️ 오류: {report['errors']}\n"
            
            if not report.get("added") and not report.get("removed"):
                msg += "✅ 변경 없음"
            
            await self.send_message(msg, chat_id=chat_id)
            
        except Exception as e:
            await self.send_message(f"❌ 동기화 실패: {e}", chat_id=chat_id)

    async def _sync_legacy(self) -> Dict:
        """기존 동기화 로직 (fallback)"""
        report = {"added": [], "removed": [], "matched": [], "errors": []}
        
        try:
            bal = self.api.fetch_balance()
            positions = self.pm.get_all_positions()
            
            # 봇에만 있는 포지션 삭제
            for symbol in list(positions.keys()):
                coin = symbol.replace("/KRW", "")
                actual_qty = 0
                for k, v in bal.items():
                    if k == coin:
                        actual_qty = v.get("total", 0) if isinstance(v, dict) else v or 0
                        break
                
                if actual_qty < 0.0001:
                    del self.pm.positions[symbol]
                    self.pm._save()
                    report["removed"].append({"symbol": symbol})
            
            # 빗썸에만 있는 코인 추가
            for coin, data in bal.items():
                if coin in ["KRW", "free", "used", "total", "info", "timestamp", "datetime"]:
                    continue
                
                total_qty = data.get("total", 0) if isinstance(data, dict) else 0
                if total_qty <= 0:
                    continue
                
                symbol = f"{coin}/KRW"
                if symbol in self.pm.positions:
                    report["matched"].append(symbol)
                    continue
                
                # 가격 조회
                try:
                    ticker = self.api.fetch_ticker(symbol)
                    price = ticker.get("last", 0)
                    value = total_qty * price
                    
                    if value >= Config.MIN_ORDER_AMOUNT:
                        # 포지션 추가
                        if hasattr(self.pm, '_add_synced_position'):
                            self.pm._add_synced_position(symbol, total_qty, price)
                        report["added"].append({
                            "symbol": symbol,
                            "qty": total_qty,
                            "avg_price": price,
                        })
                except:
                    pass
            
        except Exception as e:
            report["errors"].append(str(e))
        
        return report

    async def cmd_pivot(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        chat_id = self._get_chat_id(update)
        if len(context.args) > 0:
            symbol = context.args[0].upper()
            if "/" not in symbol:
                symbol = f"{symbol}/KRW"
            await self._show_pivot_analysis(chat_id, symbol)
            return

        msg = "<b>📍 피봇 분석할 코인 선택</b>"
        keyboard = []
        for coin in MAJOR_COINS[:6]:
            keyboard.append(InlineKeyboardButton(coin, callback_data=f"pivot_{coin}"))
        await self.send_message(msg, chat_id=chat_id, reply_markup=InlineKeyboardMarkup([keyboard]))

    async def _show_pivot_analysis(self, chat_id: int, symbol: str):
        try:
            df = self.api.fetch_ohlcv(symbol, timeframe="1d", limit=2)
            if df is None or len(df) < 2:
                await self.send_message(f"❌ {symbol} 데이터 없음", chat_id=chat_id)
                return

            prev = df.iloc[-2]
            high, low, close = float(prev["high"]), float(prev["low"]), float(prev["close"])

            pp = (high + low + close) / 3
            r1, s1 = 2 * pp - low, 2 * pp - high
            r2, s2 = pp + (high - low), pp - (high - low)

            current_price = self._get_current_price(symbol) or 0

            msg = (
                f"<b>📍 {symbol.replace('/', '-')} 피봇</b>\n\n"
                f"💰 현재가: <b>{_format_price(current_price)}₩</b>\n\n"
                f"<b>저항</b>\nR2: {_format_price(r2)}₩\nR1: {_format_price(r1)}₩\n\n"
                f"<b>피봇</b>\nPP: {_format_price(pp)}₩\n\n"
                f"<b>지지</b>\nS1: {_format_price(s1)}₩\nS2: {_format_price(s2)}₩"
            )
            await self.send_message(msg, chat_id=chat_id)
        except Exception as e:
            await self.send_message(f"❌ 피봇 분석 실패: {e}", chat_id=chat_id)

    async def cmd_chart(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        chat_id = self._get_chat_id(update)
        if len(context.args) > 0:
            symbol = context.args[0].upper()
            if "/" not in symbol:
                symbol = f"{symbol}/KRW"
            await self._show_chart(chat_id, symbol)
            return

        msg = "<b>📈 차트 분석할 코인 선택</b>"
        keyboard = []
        for coin in MAJOR_COINS[:6]:
            keyboard.append(InlineKeyboardButton(coin, callback_data=f"chart_{coin}"))
        await self.send_message(msg, chat_id=chat_id, reply_markup=InlineKeyboardMarkup([keyboard]))

    async def _show_chart(self, chat_id: int, symbol: str):
        try:
            if not self.chart:
                await self.send_message("❌ ChartEngine 미연결", chat_id=chat_id)
                return
            msg, img_path = self.chart.create_chart_for_telegram(symbol)
            if img_path and os.path.exists(img_path):
                await self.send_photo(img_path, caption=msg, chat_id=chat_id)
            else:
                await self.send_message(msg, chat_id=chat_id)
        except Exception as e:
            await self.send_message(f"❌ 차트 생성 실패: {e}", chat_id=chat_id)

    # 🔥 v5.2.0: cmd_scalp, cmd_scalp_status 함수 삭제됨

    async def _run_analyze(self, symbol: str, chat_id: int):
        """v5.0.9f: 실제 기술적 지표 기반 GPT 분석"""
        await self.send_message(f"🔮 {symbol} GPT 분석 중...", chat_id=chat_id)
        try:
            import ta
            from openai import OpenAI
            
            df30, df15, df5 = self.signal_bot.load_ohlcv(symbol)
            if df30 is None or len(df30) < 50:
                await self.send_message(f"❌ {symbol} 데이터 부족", chat_id=chat_id)
                return
            
            # === 기술적 지표 계산 ===
            current_price = df30['close'].iloc[-1]
            high_24h = df30['high'].tail(48).max()
            low_24h = df30['low'].tail(48).min()
            open_24h = df30['open'].iloc[-48] if len(df30) >= 48 else df30['open'].iloc[0]
            change_24h = ((current_price - open_24h) / open_24h) * 100
            
            rsi = ta.momentum.rsi(df30['close'], window=14).iloc[-1]
            ema20 = ta.trend.ema_indicator(df30['close'], window=20).iloc[-1]
            ema50 = ta.trend.ema_indicator(df30['close'], window=50).iloc[-1]
            ema_status = "골든크로스" if ema20 > ema50 else "데드크로스"
            ema_diff = ((ema20 - ema50) / ema50) * 100
            adx = ta.trend.adx(df30['high'], df30['low'], df30['close'], window=14).iloc[-1]
            atr = ta.volatility.average_true_range(df30['high'], df30['low'], df30['close'], window=14).iloc[-1]
            atr_pct = (atr / current_price) * 100
            
            bb = ta.volatility.BollingerBands(df30['close'], window=20, window_dev=2)
            bb_upper = bb.bollinger_hband().iloc[-1]
            bb_lower = bb.bollinger_lband().iloc[-1]
            bb_position = ((current_price - bb_lower) / (bb_upper - bb_lower)) * 100 if (bb_upper - bb_lower) > 0 else 50
            
            prev_high = df30['high'].iloc[-49:-1].max() if len(df30) >= 50 else high_24h
            prev_low = df30['low'].iloc[-49:-1].min() if len(df30) >= 50 else low_24h
            prev_close = df30['close'].iloc[-2] if len(df30) >= 2 else current_price
            pivot = (prev_high + prev_low + prev_close) / 3
            r1 = 2 * pivot - prev_low
            s1 = 2 * pivot - prev_high
            
            vol_avg = df30['volume'].tail(20).mean()
            vol_current = df30['volume'].iloc[-1]
            vol_ratio = (vol_current / vol_avg) if vol_avg > 0 else 1
            
            prompt = f"""다음 {symbol} 기술적 지표를 분석해서 한국어로 간결하게 답변해줘.

【현재가】{current_price:,.0f}원 (24H: {change_24h:+.2f}%)
【24H 고저】고가 {high_24h:,.0f} / 저가 {low_24h:,.0f}

【RSI(14)】{rsi:.1f}
【EMA】20: {ema20:,.0f} / 50: {ema50:,.0f} ({ema_status}, 차이 {ema_diff:+.2f}%)
【ADX(14)】{adx:.1f} (25이상=강한추세)
【ATR%】{atr_pct:.2f}%

【볼린저밴드】상단 {bb_upper:,.0f} / 하단 {bb_lower:,.0f}
【BB 위치】{bb_position:.0f}% (0=하단, 100=상단)

【피봇】P {pivot:,.0f} / R1 {r1:,.0f} / S1 {s1:,.0f}
【거래량】현재/평균 비율: {vol_ratio:.2f}x

다음 형식으로 답변:
1. 추세 판단 (상승/하락/횡보, 강도)
2. 과매수/과매도 상태
3. 주요 지지/저항 구간
4. 단기 전망 (1~3일)
5. 주의사항"""

            client = OpenAI(api_key=Config.OPENAI_API_KEY)
            response = client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[{"role": "user", "content": prompt}],
                max_tokens=500,
                temperature=0.3
            )
            
            analysis = response.choices[0].message.content
            
            trend_emoji = "📈" if change_24h > 0 else "📉" if change_24h < 0 else "➡️"
            rsi_status = "과매수⚠️" if rsi > 70 else "과매도⚠️" if rsi < 30 else "중립"
            
            header = (
                f"🔮 <b>{symbol} 분석</b>\n"
                f"━━━━━━━━━━━━━━━\n"
                f"💰 현재가: <b>{_format_price(current_price)}₩</b> ({change_24h:+.2f}%) {trend_emoji}\n"
                f"📊 RSI: {rsi:.1f} ({rsi_status}) | ADX: {adx:.1f}\n"
                f"📈 EMA: {ema_status} | BB: {bb_position:.0f}%\n"
                f"🎯 저항 R1: {_format_price(r1)} | 지지 S1: {_format_price(s1)}\n"
                f"━━━━━━━━━━━━━━━\n\n"
            )
            
            msg = header + analysis
            await self.send_message(msg, chat_id=chat_id)
            
        except Exception as e:
            logger.error(f"[Analyze] {symbol} 분석 실패: {e}")
            await self.send_message(f"❌ 분석 실패: {e}", chat_id=chat_id)

    async def cmd_analyze(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        chat_id = self._get_chat_id(update)
        if len(context.args) > 0:
            symbol = context.args[0].upper()
            if "/" not in symbol:
                symbol = f"{symbol}/KRW"
            await self._run_analyze(symbol, chat_id)
        else:
            keyboard = []
            for coin in ["BTC", "ETH", "XRP", "SOL"]:
                keyboard.append(InlineKeyboardButton(coin, callback_data=f"analyze_{coin}/KRW"))
            await self.send_message("🔮 <b>GPT 분석할 코인 선택</b>", chat_id=chat_id, reply_markup=InlineKeyboardMarkup([keyboard]))

    async def cmd_risk(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        chat_id = self._get_chat_id(update)
        if not self.rm:
            await self.send_message("❌ RiskManager 미연결", chat_id=chat_id)
            return
        try:
            summary = self.rm.get_risk_summary()
            daily_loss = summary.get("daily_loss_pct", 0)
            drawdown = summary.get("drawdown_pct", 0)
            can_trade = summary.get("can_trade", True)
            status_emoji = "🟢" if can_trade else "🔴"

            msg = (
                f"⚠️ <b>리스크 현황</b>\n\n"
                f"거래 가능: {status_emoji}\n"
                f"일일 손실: {daily_loss:.2f}%\n"
                f"드로우다운: {drawdown:.2f}%"
            )
            await self.send_message(msg, chat_id=chat_id)
        except Exception as e:
            await self.send_message(f"❌ 리스크 조회 실패: {e}", chat_id=chat_id)

    async def cmd_report(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """🆕 v5.2.1b: 일일 상세 리포트 (00:00 ~ 24:00 KST)"""
        chat_id = self._get_chat_id(update)
        if not self.trade_logger:
            await self.send_message("❌ TradeLogger 미연결", chat_id=chat_id)
            return
        
        # 상세 통계 조회
        stats = self.trade_logger.get_daily_detailed_stats()
        
        if stats.get("total_trades", 0) == 0:
            await self.send_message("📭 오늘 청산된 거래 없음", chat_id=chat_id)
            return
        
        # 메시지 구성
        pnl = stats["total_pnl_krw"]
        emoji = "🟢" if pnl >= 0 else "🔴"
        mdd_emoji = "⚠️" if stats["mdd_pct"] < -5 else ""
        
        msg = f"📊 <b>일일 리포트</b> ({stats['period']})\n"
        msg += "━━━━━━━━━━━━━━━━━━━━━━\n\n"
        
        # 📈 거래 요약
        msg += "<b>📈 거래 요약</b>\n"
        msg += f"• 총 거래: {stats['total_trades']}건 (익절 {stats['wins']} / 손절 {stats['losses']})\n"
        msg += f"• 승률: <b>{stats['win_rate']:.1f}%</b>\n"
        msg += f"• 총 수익: {emoji} <b>{pnl:+,.0f}원</b>\n"
        msg += f"• 평균 수익률: {stats['avg_pnl_pct']:+.2f}%\n\n"
        
        # 📉 리스크 지표
        msg += "<b>📉 리스크 지표</b>\n"
        msg += f"• MDD: {mdd_emoji}{stats['mdd_pct']:.1f}%\n"
        msg += f"• 최대 연속 손실: {stats['max_losing_streak']}회\n"
        msg += f"• 평균 보유 시간: {_format_holding_time(stats['avg_holding_hours'])}\n\n"
        
        # 💰 코인별 성과 (상위 5개)
        if stats["by_coin"]:
            msg += "<b>💰 코인별 성과</b>\n"
            sorted_coins = sorted(stats["by_coin"].items(), key=lambda x: x[1]["pnl_krw"], reverse=True)
            for coin, data in sorted_coins[:5]:
                coin_emoji = "🟢" if data["pnl_krw"] >= 0 else "🔴"
                coin_name = coin.replace("/KRW", "")
                msg += f"• {coin_name}: {coin_emoji} {data['pnl_krw']:+,.0f}원 ({data['trades']}건, {data['win_rate']:.0f}%)\n"
            msg += "\n"
        
        # 🎯 전략별 성과
        if stats["by_strategy"]:
            msg += "<b>🎯 전략별 성과</b>\n"
            for strategy, data in stats["by_strategy"].items():
                strat_emoji = "🟢" if data["pnl_krw"] >= 0 else "🔴"
                strat_name = strategy.upper() if strategy else "UNKNOWN"
                msg += f"• {strat_name}: {strat_emoji} {data['pnl_krw']:+,.0f}원 ({data['trades']}건, {data['win_rate']:.0f}%)\n"
        
        await self.send_message(msg, chat_id=chat_id)

    async def cmd_weekly(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """🆕 v5.2.1b: 주간 상세 리포트 (월요일 ~ 일요일)"""
        chat_id = self._get_chat_id(update)
        if not self.trade_logger:
            await self.send_message("❌ TradeLogger 미연결", chat_id=chat_id)
            return
        
        # 상세 통계 조회
        stats = self.trade_logger.get_weekly_detailed_stats()
        
        if stats.get("total_trades", 0) == 0:
            await self.send_message("📭 이번 주 청산된 거래 없음", chat_id=chat_id)
            return
        
        # 메시지 구성
        pnl = stats["total_pnl_krw"]
        emoji = "🟢" if pnl >= 0 else "🔴"
        mdd_emoji = "⚠️" if stats["mdd_pct"] < -5 else ""
        
        msg = f"📊 <b>주간 리포트</b>\n"
        msg += f"📅 {stats['period']}\n"
        msg += "━━━━━━━━━━━━━━━━━━━━━━\n\n"
        
        # 📈 거래 요약
        msg += "<b>📈 거래 요약</b>\n"
        msg += f"• 총 거래: {stats['total_trades']}건 (익절 {stats['wins']} / 손절 {stats['losses']})\n"
        msg += f"• 승률: <b>{stats['win_rate']:.1f}%</b>\n"
        msg += f"• 총 수익: {emoji} <b>{pnl:+,.0f}원</b>\n"
        msg += f"• 평균 수익률: {stats['avg_pnl_pct']:+.2f}%\n\n"
        
        # 📉 리스크 지표
        msg += "<b>📉 리스크 지표</b>\n"
        msg += f"• MDD: {mdd_emoji}{stats['mdd_pct']:.1f}%\n"
        msg += f"• 최대 연속 손실: {stats['max_losing_streak']}회\n"
        msg += f"• 평균 보유 시간: {_format_holding_time(stats['avg_holding_hours'])}\n"
        msg += f"• 최고 거래: +{stats['best_trade_pnl']:,.0f}원\n"
        msg += f"• 최저 거래: {stats['worst_trade_pnl']:,.0f}원\n\n"
        
        # 💰 코인별 성과 (상위 5개)
        if stats["by_coin"]:
            msg += "<b>💰 코인별 성과</b>\n"
            sorted_coins = sorted(stats["by_coin"].items(), key=lambda x: x[1]["pnl_krw"], reverse=True)
            for coin, data in sorted_coins[:5]:
                coin_emoji = "🟢" if data["pnl_krw"] >= 0 else "🔴"
                coin_name = coin.replace("/KRW", "")
                msg += f"• {coin_name}: {coin_emoji} {data['pnl_krw']:+,.0f}원 ({data['trades']}건, {data['win_rate']:.0f}%)\n"
            msg += "\n"
        
        # 🎯 전략별 성과
        if stats["by_strategy"]:
            msg += "<b>🎯 전략별 성과</b>\n"
            for strategy, data in stats["by_strategy"].items():
                strat_emoji = "🟢" if data["pnl_krw"] >= 0 else "🔴"
                strat_name = strategy.upper() if strategy else "UNKNOWN"
                msg += f"• {strat_name}: {strat_emoji} {data['pnl_krw']:+,.0f}원 ({data['trades']}건, {data['win_rate']:.0f}%)\n"
        
        await self.send_message(msg, chat_id=chat_id)

    async def cmd_backup(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        chat_id = self._get_chat_id(update)
        if not self.pm:
            await self.send_message("❌ PositionManager 미연결", chat_id=chat_id)
            return
        try:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            backup_file = f"data/positions_backup_{timestamp}.json"
            os.makedirs("data", exist_ok=True)
            with open(backup_file, "w", encoding="utf-8") as f:
                json.dump(self.pm.get_all_positions(), f, indent=4, ensure_ascii=False)
            await self.send_message(f"💾 <b>백업 완료</b>\n\n파일: {backup_file}", chat_id=chat_id)
        except Exception as e:
            await self.send_message(f"❌ 백업 실패: {e}", chat_id=chat_id)

    async def cmd_reload(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        chat_id = self._get_chat_id(update)
        try:
            from dotenv import load_dotenv
            load_dotenv(override=True)
            Config.MODE = os.getenv("MODE", "SEMI").upper()
            await self.send_message(f"♻️ <b>리로드 완료</b>\n\nMODE: {Config.MODE}", chat_id=chat_id)
        except Exception as e:
            await self.send_message(f"❌ 리로드 실패: {e}", chat_id=chat_id)

    async def cmd_ws(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        chat_id = self._get_chat_id(update)
        if not self.price_feed:
            await self.send_message("❌ PriceFeed 미연결", chat_id=chat_id)
            return
        try:
            if hasattr(self.price_feed, 'get_health_status'):
                health = self.price_feed.get_health_status()
                connected = health.get("connected", False)
                last_age = health.get("last_update_age_sec", 999)
                reconnects = health.get("reconnect_count", 0)
                
                if connected and last_age < 60:
                    ws_status = "🟢 정상"
                elif connected:
                    ws_status = "🟡 지연"
                else:
                    ws_status = "🔴 끊김"
                
                msg = (
                    f"<b>🔌 WebSocket 상태</b>\n\n"
                    f"상태: {ws_status}\n"
                    f"마지막 데이터: {last_age:.0f}초 전\n"
                    f"재연결: {reconnects}회"
                )
            else:
                msg = "WebSocket 상태 조회 미지원"
            await self.send_message(msg, chat_id=chat_id)
        except Exception as e:
            await self.send_message(f"❌ 오류: {e}", chat_id=chat_id)

    # ================================================================
    # 실행
    # ================================================================
    async def _run(self):
        self._app = Application.builder().token(self.token).build()
        await self._app.bot.set_my_commands(BOT_COMMANDS)

        handlers = [
            ("start", self.cmd_start), ("help", self.cmd_help), ("status", self.cmd_status),
            ("balance", self.cmd_balance), ("mode", self.cmd_mode), ("positions", self.cmd_positions),
            ("close", self.cmd_close), ("close_all", self.cmd_close_all), ("queue", self.cmd_queue),
            ("summary", self.cmd_summary), ("pf_refresh", self.cmd_pf_refresh), ("signal", self.cmd_signal),
            ("pivot", self.cmd_pivot), ("chart", self.cmd_chart),
            # 🔥 v5.2.0: scalp, scalp_status 핸들러 삭제됨
            ("analyze", self.cmd_analyze), ("risk", self.cmd_risk), ("report", self.cmd_report),
            ("weekly", self.cmd_weekly), ("backup", self.cmd_backup), ("sync", self.cmd_sync),
            ("reload", self.cmd_reload), ("ws", self.cmd_ws),
        ]

        for cmd, handler in handlers:
            self._app.add_handler(CommandHandler(cmd, handler))

        self._app.add_handler(CallbackQueryHandler(self.button_callback))

        self._ready = True
        logger.info("[TelegramBot] Started (Phoenix v5.1.0c)")

        await self.send_message("🚀 <b>Phoenix v5.1.0c 시작됨</b>\n\n명령어: /help")

        await self._app.initialize()
        await self._app.start()
        await self._app.updater.start_polling(drop_pending_updates=True)

        expiry_counter = 0
        while True:
            await asyncio.sleep(0.5)
            expiry_counter += 1
            if expiry_counter >= 20:
                self.check_approval_expiry()
                expiry_counter = 0

    def run_in_thread(self):
        import threading
        def _thread():
            self._loop = asyncio.new_event_loop()
            asyncio.set_event_loop(self._loop)
            self._loop.run_until_complete(self._run())

        t = threading.Thread(target=_thread, daemon=True)
        t.start()
