# -*- coding: utf-8 -*-

"""
Phoenix v5.3.1a — ExecutionEngine (TypeError Fix)

🔥 v5.3.1a 변경 (2025-12-04):
- _safe_float() 헬퍼 메서드 추가 (문자열/None 타입 안전 변환)
- entry_price 조회 시 타입 안전성 강화
- TypeError: '>=' not supported between 'str' and 'int' 수정
- PENGU/KRW 등 저가 코인 매도 승인 시 발생하던 버그 해결

🔥 v5.3.0 Phase B 변경:
- error_handler 연동 (통합 에러 관리)
- _send_error_alert() → error_handler 사용
- 주요 try-except에서 handle_error() 사용
- 에러 통계 기능 추가

🔥 v5.2.3 기능 유지:
- 동적 비중 적용: BTC mode position_mult + Confidence conf_mult
- 스마트 트레일링: TP1 도달 후에만 활성화 (휩쏘 방지)
- krw_amount에 position_mult × conf_mult 실제 적용
- trailing["enabled"] = False (진입 시 비활성, TP1 후 활성화)

🔥 v5.2.1b 기능 유지:
- SEMI 모드 모든 매도에 승인 요청 적용
- 실제 잔고 기반 비율 방식 매도
- 안전 마진 99.95% 적용
"""

import traceback
import threading
from datetime import datetime
from typing import Dict, Optional, List
from collections import deque

from config import Config
from bot.utils.logger import get_logger

# 🆕 v5.3.0 Phase B: error_handler 연동
from bot.utils.error_handler import (
    error_handler,
    handle_error,
    log_and_notify,
    ErrorSeverity,
)

logger = get_logger("ExecutionEngine")


# =========================================================
# 🔥 슬리피지 추적 클래스
# =========================================================

class SlippageTracker:
    """슬리피지 추적 및 통계"""

    WARNING_THRESHOLD = 0.005
    CRITICAL_THRESHOLD = 0.01

    def __init__(self, max_history: int = 100):
        self.lock = threading.Lock()
        self.history: deque = deque(maxlen=max_history)
        self.total_trades = 0
        self.total_slippage_krw = 0.0
        self.warning_count = 0
        self.critical_count = 0

    def record(self, symbol: str, side: str, expected_price: float,
               actual_price: float, qty: float, order_id: str = None) -> Dict:
        if expected_price <= 0:
            return {}
        
        if side == "buy":
            slippage_pct = (actual_price - expected_price) / expected_price
        else:
            slippage_pct = (expected_price - actual_price) / expected_price
        
        slippage_krw = abs(actual_price - expected_price) * qty
        
        if abs(slippage_pct) >= self.CRITICAL_THRESHOLD:
            level = "critical"
        elif abs(slippage_pct) >= self.WARNING_THRESHOLD:
            level = "warning"
        else:
            level = "normal"
        
        record = {
            "timestamp": datetime.now().isoformat(),
            "symbol": symbol,
            "side": side,
            "expected_price": expected_price,
            "actual_price": actual_price,
            "qty": qty,
            "slippage_pct": round(slippage_pct * 100, 4),
            "slippage_krw": round(slippage_krw, 0),
            "level": level,
            "order_id": order_id,
        }
        
        with self.lock:
            self.history.append(record)
            self.total_trades += 1
            if slippage_pct > 0:
                self.total_slippage_krw += slippage_krw
            if level == "warning":
                self.warning_count += 1
            elif level == "critical":
                self.critical_count += 1
        
        if level == "critical":
            logger.warning(f"[슬리피지 심각] {symbol} {side}: {slippage_pct*100:+.2f}%")
        
        return record

    def get_stats(self) -> Dict:
        with self.lock:
            if not self.history:
                return {"total_trades": 0, "avg_slippage_pct": 0, "total_slippage_krw": 0}
            slippages = [r["slippage_pct"] for r in self.history]
            return {
                "total_trades": self.total_trades,
                "avg_slippage_pct": round(sum(slippages) / len(slippages), 4),
                "total_slippage_krw": round(self.total_slippage_krw, 0),
                "warning_count": self.warning_count,
                "critical_count": self.critical_count,
            }


class ExecutionEngine:
    """체결 엔진 (v5.3.0 Phase B - error_handler 연동)"""

    def __init__(self, api, position_manager, risk_manager, price_feed=None, 
                 trade_logger=None, telegram_bot=None):
        self.api = api
        self.pm = position_manager
        self.rm = risk_manager
        self.pf = price_feed
        self.trade_logger = trade_logger
        self.telegram_bot = telegram_bot
        
        # 슬리피지 추적기
        self.slippage_tracker = SlippageTracker()
        
        # 🔥 v5.0.9e: SL 승인 대기 중인 심볼 (중복 요청 방지)
        self.sl_pending_symbols: set = set()
        self.sl_pending_lock = threading.Lock()

        # Aggressive Mode 여부
        self.aggressive = getattr(Config, "AGGRESSIVE_MODE", False)

        # 트레일링 설정
        self.trailing_trigger = 0.03
        self.trailing_offset = 0.015

        if self.aggressive:
            logger.warning("[AGGRESSIVE MODE] 초공격형 매매 활성화됨")
            self.trailing_trigger = 0.015
            self.trailing_offset = 0.006
            self.ai_tp_multiplier = 1.8
            self.ai_sl_reduction = 0.5
            self.position_boost = 1.4
            self.max_dca_stage = 5
        else:
            self.ai_tp_multiplier = 1.0
            self.ai_sl_reduction = 1.0
            self.position_boost = 1.0
            self.max_dca_stage = 3
        
        # 🆕 v5.3.0: error_handler 텔레그램 콜백 설정
        if telegram_bot and hasattr(telegram_bot, 'send_error_alert'):
            def notify_callback(msg):
                try:
                    telegram_bot.send_message_sync(msg)
                except:
                    pass
            error_handler.set_notify_callback(notify_callback)

    def inject_modules(self, trade_logger=None, telegram_bot=None):
        """런타임 모듈 주입"""
        if trade_logger:
            self.trade_logger = trade_logger
        if telegram_bot:
            self.telegram_bot = telegram_bot
            # 🆕 v5.3.0: error_handler 콜백 업데이트
            if hasattr(telegram_bot, 'send_message_sync'):
                def notify_callback(msg):
                    try:
                        telegram_bot.send_message_sync(msg)
                    except:
                        pass
                error_handler.set_notify_callback(notify_callback)

    # ================================================================
    # 🆕 v5.3.0 Phase B: 에러 알림 (error_handler 사용)
    # ================================================================
    def _send_error_alert(self, error_type: str, symbol: str, details: str, severity: str = "error"):
        """
        에러 알림 전송 (v5.3.0: error_handler 통합)
        
        Args:
            error_type: 에러 타입 (매수 실패, 매도 실패 등)
            symbol: 심볼
            details: 상세 내용
            severity: 심각도 (debug, info, warning, error, critical)
        """
        # 심각도 변환
        severity_map = {
            "debug": ErrorSeverity.DEBUG,
            "info": ErrorSeverity.INFO,
            "warning": ErrorSeverity.WARNING,
            "error": ErrorSeverity.ERROR,
            "critical": ErrorSeverity.CRITICAL,
        }
        error_severity = severity_map.get(severity, ErrorSeverity.ERROR)
        
        # 🆕 v5.3.0: log_and_notify로 통합 로깅 + 알림
        log_and_notify(
            message=f"{error_type}: {symbol} - {details}",
            severity=error_severity,
            context="ExecutionEngine",
            notify=(error_severity in [ErrorSeverity.ERROR, ErrorSeverity.CRITICAL]),
        )
        
        # 기존 텔레그램 알림도 유지 (호환성)
        if self.telegram_bot and hasattr(self.telegram_bot, 'send_error_alert'):
            try:
                self.telegram_bot.send_error_alert(error_type, symbol, details, severity)
            except Exception as e:
                logger.error(f"[ERROR ALERT] 전송 실패: {e}")

    # 🔥 v5.0.9e: SL pending 관리 메서드
    def _add_sl_pending(self, symbol: str):
        """SL 승인 대기 목록에 추가"""
        with self.sl_pending_lock:
            self.sl_pending_symbols.add(symbol)

    def _remove_sl_pending(self, symbol: str):
        """SL 승인 대기 목록에서 제거"""
        with self.sl_pending_lock:
            self.sl_pending_symbols.discard(symbol)

    def _is_sl_pending(self, symbol: str) -> bool:
        """SL 승인 대기 중인지 확인"""
        with self.sl_pending_lock:
            return symbol in self.sl_pending_symbols

    def clear_sl_pending(self, symbol: str):
        """외부에서 SL pending 해제 (승인/거절 후 호출)"""
        self._remove_sl_pending(symbol)
        logger.info(f"[SL PENDING] {symbol} 해제됨")

    def _get_price(self, symbol):
        """가격 조회 - WebSocket 우선, REST fallback"""
        price = None
        if self.pf:
            price = self.pf.get_price(symbol)
            if price and price > 0:
                return price
        try:
            ticker = self.api.fetch_ticker(symbol)
            price = ticker.get("last")
            if price and price > 0:
                return float(price)
        except Exception as e:
            logger.error(f"[가격 조회 오류] {symbol}: {e}")
        return None

    # ================================================================
    # 🆕 v5.3.1a: 안전한 타입 변환 헬퍼
    # ================================================================
    def _safe_float(self, value, default: float = 0.0) -> float:
        """
        🆕 v5.3.1a: 안전한 float 변환 (문자열/None 처리)
        
        positions.json에서 가격이 문자열로 저장되거나
        API에서 문자열로 반환되는 경우 TypeError 방지
        
        Args:
            value: 변환할 값 (str, int, float, None 등)
            default: 변환 실패 시 기본값
            
        Returns:
            float 값 (실패 시 default)
        """
        if value is None:
            return default
        try:
            result = float(value)
            # NaN 체크
            if result != result:
                return default
            # Inf 체크
            if result == float('inf') or result == float('-inf'):
                return default
            return result
        except (ValueError, TypeError):
            return default

    def _extract_fill_info(self, order: dict, expected_price: float, expected_qty: float) -> tuple:
        if not order:
            return expected_price, expected_qty, None
        
        order_id = order.get("id") or order.get("order_id")
        info = order.get("info", {})
        bithumb_status = info.get("status")
        
        actual_price = order.get("average") or order.get("price")
        actual_qty = order.get("filled") or order.get("amount")
        
        if not actual_price:
            actual_price = info.get("average") or info.get("price")
            if isinstance(actual_price, str):
                try:
                    actual_price = float(actual_price)
                except:
                    actual_price = None
        
        if not actual_qty:
            actual_qty = info.get("units") or info.get("filled")
            if isinstance(actual_qty, str):
                try:
                    actual_qty = float(actual_qty)
                except:
                    actual_qty = None
        
        if bithumb_status == "0000":
            if not actual_price or actual_price <= 0:
                actual_price = expected_price
            if not actual_qty or actual_qty <= 0:
                actual_qty = expected_qty
        else:
            if not actual_price or actual_price <= 0:
                actual_price = expected_price
            if not actual_qty or actual_qty <= 0:
                actual_qty = expected_qty
        
        return float(actual_price), float(actual_qty), order_id

    def _calculate_dynamic_tp_multiplier(self, ai_decision: Dict) -> float:
        tp_mult = 1.0
        if not ai_decision:
            return tp_mult
        
        btc_mode = ai_decision.get("btc_mode", {})
        if btc_mode:
            tp_mult *= btc_mode.get("tp_mult", 1.0)
        
        confidence = float(ai_decision.get("confidence", 0.5))
        if confidence >= 0.85:
            tp_mult *= 1.1
        elif confidence >= 0.70:
            tp_mult *= 1.05
        
        return min(tp_mult, 1.5)

    # ================================================================
    # 🆕 v5.2.3: 동적 비중 배수 계산
    # ================================================================
    def _calculate_dynamic_position_multiplier(self, ai_decision: Dict) -> float:
        """
        🆕 v5.2.3: BTC 모드 + Confidence 기반 동적 비중 배수 계산
        
        Args:
            ai_decision: AI 판단 결과
            
        Returns:
            position_mult × conf_mult (최종 비중 배수)
        """
        if not ai_decision:
            return 1.0
        
        # 1. BTC 모드 기반 비중 배수
        btc_mode = ai_decision.get("btc_mode", {})
        position_mult = btc_mode.get("position_mult", 1.0)
        
        # bear_strong (급락장)이면 진입 금지
        if position_mult <= 0:
            logger.warning(f"[동적 비중] BTC 급락장 - 진입 금지 (position_mult=0)")
            return 0.0
        
        # 2. Confidence 기반 비중 배수
        confidence = float(ai_decision.get("confidence", 0.5))
        
        if confidence >= 0.85:
            conf_mult = 1.3
        elif confidence >= 0.75:
            conf_mult = 1.15
        elif confidence >= 0.65:
            conf_mult = 1.0
        elif confidence >= 0.55:
            conf_mult = 0.85
        else:
            conf_mult = 0.7
        
        # 3. 최종 배수 계산 (상한 1.6, 하한 0.5)
        final_mult = position_mult * conf_mult
        final_mult = max(0.5, min(1.6, final_mult))
        
        logger.info(
            f"[동적 비중] BTC mode={btc_mode.get('mode', 'neutral')} "
            f"pos_mult={position_mult:.2f} × conf_mult={conf_mult:.2f} "
            f"= {final_mult:.2f}"
        )
        
        return final_mult

    def _build_tp_levels(self, entry_price: float, base_ratio: float, ai_decision: Dict = None):
        if base_ratio is None or base_ratio <= 0:
            base_ratio = 0.02

        tp_multiplier = 1.0
        if ai_decision:
            tp_multiplier = self._calculate_dynamic_tp_multiplier(ai_decision)
        
        adjusted_ratio = min(base_ratio * tp_multiplier, 0.15)

        levels_conf = [
            {"id": 1, "name": "TP1", "mult": 0.6, "portion": 0.5},
            {"id": 2, "name": "TP2", "mult": 1.0, "portion": 0.3},
            {"id": 3, "name": "TP3", "mult": 1.6, "portion": 0.2},
        ]

        levels = []
        for c in levels_conf:
            target_price = entry_price * (1.0 + adjusted_ratio * c["mult"])
            levels.append({
                "id": c["id"],
                "name": c["name"],
                "price": round(target_price, 2),
                "portion": c["portion"],
                "executed": False,
            })
        
        return levels

    def _handle_tp_levels(self, symbol: str, pos: dict, price: float) -> bool:
        levels = pos.get("tp_levels") or []
        if not levels:
            return False

        # 🆕 v5.3.1a: 타입 안전 변환
        entry = self._safe_float(pos.get("entry_price"), 0)
        qty = self._safe_float(pos.get("qty"), 0)
        initial_qty = self._safe_float(pos.get("initial_qty"), qty)

        if initial_qty <= 0 or qty <= 0:
            return False

        levels = sorted(levels, key=lambda x: x.get("id", 0))
        changed = False

        for i, lvl in enumerate(levels):
            if lvl.get("executed"):
                continue

            # 🆕 v5.3.1a: 타입 안전 변환
            target = self._safe_float(lvl.get("price"), 0)
            portion = self._safe_float(lvl.get("portion"), 0)
            if target <= 0 or portion <= 0:
                continue

            if price < target:
                break

            is_last = (i == len(levels) - 1)

            if is_last:
                logger.info(f"[TP3 FULL CLOSE] {symbol} price={price} target={target}")
                self.market_sell(symbol, pos, reason="TP3 익절", skip_approval=True)
                return True

            sell_qty = round(initial_qty * portion, 6)
            if sell_qty > qty:
                sell_qty = qty
            if sell_qty <= 0:
                lvl["executed"] = True
                continue

            try:
                order = self.api.create_limit_sell(symbol, sell_qty)
                logger.info(f"[TP PARTIAL] {symbol} {lvl.get('name')} qty={sell_qty}")
            except Exception as e:
                # 🆕 v5.3.0: error_handler 사용
                handle_error(e, f"TP_PARTIAL:{symbol}", notify=False)
                break

            qty -= sell_qty
            lvl["executed"] = True
            changed = True
            pos["qty"] = qty

            # 🆕 v5.2.3: TP1 도달 시 트레일링 활성화 (스마트 트레일링)
            tr = pos.get("trailing") or {}
            if tr:
                if lvl.get("id") == 1:  # TP1 도달
                    tr["enabled"] = True
                    logger.info(f"[SMART TRAILING] {symbol} TP1 도달 → 트레일링 활성화")
                # 🆕 v5.3.1a: 타입 안전 변환
                highest = self._safe_float(tr.get("highest_price"), price)
                tr["highest_price"] = max(highest, price)
                pos["trailing"] = tr

            if qty <= 0:
                break

        if changed:
            pos["tp_levels"] = levels
            self.pm.update_position(symbol, pos)

        return False

    def _apply_legacy_exit(self, symbol, pos, price, entry) -> bool:
        """
        🔥 v5.2.1b: 레거시 청산 로직 - SEMI 모드 승인 강화
        """
        # 🆕 v5.3.1a: entry가 0이면 안전하게 처리
        if entry <= 0:
            return False
            
        diff = (price - entry) / max(entry, 1)

        # 🆕 v5.3.1a: 타입 안전 변환
        tp_price = self._safe_float(pos.get("tp"), 0)
        sl_price = self._safe_float(pos.get("sl"), 0)

        # TP 도달 - 승인 없이 익절 (이익이므로)
        if tp_price > 0 and price >= tp_price:
            self.market_sell(symbol, pos, reason="TP 익절", skip_approval=True)
            return True
        
        # SL 도달 - SEMI 모드 승인 필요
        if sl_price > 0 and price <= sl_price:
            if Config.MODE == "SEMI":
                self._request_sell_approval(symbol, pos, price, "레거시 SL 도달", sell_type="sl")
                return True
            self.market_sell(symbol, pos, reason="SL 손절")
            return True

        # 🆕 v5.3.1a: 타입 안전 변환
        ai_tp = self._safe_float(pos.get("ai_tp"), 0)
        ai_sl = self._safe_float(pos.get("ai_sl"), 0)

        # AI TP 도달 - 승인 없이 익절 (이익이므로)
        if ai_tp > 0 and diff >= ai_tp:
            self.market_sell(symbol, pos, reason="AI TP 익절", skip_approval=True)
            return True
        
        # AI SL 도달 - SEMI 모드 승인 필요
        if ai_sl > 0 and diff <= -ai_sl:
            if Config.MODE == "SEMI":
                self._request_sell_approval(symbol, pos, price, f"AI SL 도달 ({diff*100:.1f}%)", sell_type="sl")
                return True
            self.market_sell(symbol, pos, reason="AI SL 손절")
            return True

        return False

    # ======================================================================
    # 🔥 v5.2.1b: 매도 승인 요청 (범용 - SL/전략신호/리밸런싱 모두 처리)
    # ======================================================================
    def _request_sell_approval(self, symbol: str, pos: Dict, current_price: float, 
                                reason: str, sell_type: str = "sell"):
        """
        🆕 v5.2.1b: SEMI 모드 매도 승인 요청 (범용)
        """
        # 🔥 이미 승인 대기 중이면 스킵
        if self._is_sl_pending(symbol):
            logger.debug(f"[매도 승인] {symbol} 이미 대기 중 - 스킵")
            return True
        
        # 🆕 v5.1.0: SL 홀드 상태 체크 (SL 타입만)
        if sell_type == "sl":
            if self.pm and hasattr(self.pm, 'is_sl_held') and self.pm.is_sl_held(symbol):
                remaining = self.pm.get_sl_hold_remaining(symbol)
                logger.debug(f"[매도 승인] {symbol} SL 홀드 중 (남은 시간: {remaining}분) - 스킵")
                return True
        
        # 🔥 v5.2.1b: telegram_bot 없으면 매도 보류
        if not self.telegram_bot:
            logger.warning(f"[매도 승인] {symbol} telegram_bot 미연결 - 매도 보류!")
            self._send_error_alert("매도 보류", symbol, f"telegram_bot 미연결 - {reason}", severity="warning")
            return False
        
        try:
            self._add_sl_pending(symbol)
            
            # 🆕 v5.3.1a: 타입 안전 변환
            entry = self._safe_float(pos.get("entry_price"), current_price)
            if entry <= 0:
                entry = current_price
            pnl_pct = ((current_price - entry) / max(entry, 1)) * 100
            
            sl_rationale = None
            if sell_type == "sl":
                try:
                    from bot.core.ai_decision import AIDecisionEngine
                    df30 = None
                    if self.pf:
                        df30 = self.pf.get_ohlcv(symbol, "30m") if hasattr(self.pf, 'get_ohlcv') else None
                    sl_rationale = AIDecisionEngine.generate_sl_rationale(symbol, pos, current_price, df30)
                except Exception as e:
                    logger.warning(f"[SL 근거 생성 실패] {symbol}: {e}")
            
            if sell_type == "sl":
                self.telegram_bot.send_sl_approval_request(symbol, pos, current_price, reason, sl_rationale)
            else:
                self.telegram_bot.send_sell_approval_request(symbol, pos, current_price, reason, pnl_pct)
            
            logger.info(f"[매도 승인 요청] {symbol} - {reason} (type={sell_type})")
            return True
            
        except Exception as e:
            # 🆕 v5.3.0: error_handler 사용
            handle_error(e, f"SELL_APPROVAL:{symbol}", notify=True)
            self._remove_sl_pending(symbol)
            self._send_error_alert("매도 승인 실패", symbol, str(e), severity="critical")
            return False

    def _request_sl_approval(self, symbol: str, pos: Dict, current_price: float, reason: str):
        """SL 승인 요청 (범용 함수 래퍼)"""
        return self._request_sell_approval(symbol, pos, current_price, reason, sell_type="sl")

    # ======================================================================
    # 🔥 v5.1.0f: 코인별 수량 정밀도 보정
    # ======================================================================
    def _get_qty_precision(self, symbol: str) -> int:
        """빗썸 코인별 수량 정밀도 반환"""
        coin = symbol.replace("/KRW", "").replace("-KRW", "").upper()
        
        # 저가 코인 (1원 미만) - 정수 수량만 허용
        LOW_PRICE_COINS = {"PEPE", "SHIB", "BONK", "FLOKI", "LUNC", "BTT", "WIN", "SPELL"}
        if coin in LOW_PRICE_COINS:
            return 0
        
        # 고가 코인 - 8자리까지 허용
        HIGH_PRICE_COINS = {"BTC", "ETH"}
        if coin in HIGH_PRICE_COINS:
            return 8
        
        return 4

    def _format_qty(self, symbol: str, qty: float) -> float:
        """코인별 수량 포맷팅"""
        precision = self._get_qty_precision(symbol)
        if precision == 0:
            return float(int(qty))
        else:
            factor = 10 ** precision
            return float(int(qty * factor)) / factor

    # ======================================================================
    # 🔥 v5.2.1: 실제 잔고 조회 헬퍼
    # ======================================================================
    def _get_actual_balance(self, symbol: str) -> float:
        """실제 거래소 잔고 조회"""
        try:
            coin = symbol.replace("/KRW", "").replace("-KRW", "").upper()
            balance = self.api.fetch_balance(force=True)
            
            coin_data = balance.get(coin, {})
            if isinstance(coin_data, dict):
                return float(coin_data.get("total", 0) or 0)
            elif isinstance(coin_data, (int, float)):
                return float(coin_data or 0)
            
            return 0.0
        except Exception as e:
            # 🆕 v5.3.0: error_handler 사용
            handle_error(e, f"BALANCE:{symbol}", notify=False)
            return 0.0

    # ======================================================================
    # 🔥 v5.2.3: 시장가 BUY (동적 비중 적용)
    # ======================================================================
    def market_buy(self, symbol, krw_amount, ai_decision, pf_weight):
        try:
            bal = self.api.fetch_balance()
            free_krw = bal.get("KRW", {}).get("free", 0)

            # ================================================================
            # 🆕 v5.2.3: 동적 비중 배수 적용 (핵심 변경!)
            # ================================================================
            dynamic_mult = self._calculate_dynamic_position_multiplier(ai_decision)
            
            # 급락장 (position_mult=0) 진입 차단
            if dynamic_mult <= 0:
                logger.warning(f"[BUY BLOCKED] {symbol} 급락장 진입 차단 (dynamic_mult=0)")
                return False
            
            # 기존 position_boost + 동적 비중 적용
            krw_amount *= self.position_boost * dynamic_mult
            
            logger.info(
                f"[BUY] {symbol} 최종 금액: {krw_amount:,.0f}원 "
                f"(pos_boost={self.position_boost:.2f} × dynamic={dynamic_mult:.2f})"
            )
            # ================================================================

            if krw_amount > free_krw:
                krw_amount = free_krw

            if krw_amount < Config.MIN_ORDER_AMOUNT:
                logger.warning(f"[BUY SKIP] {symbol} 금액 부족: {krw_amount:,.0f}")
                return False

            expected_price = self._get_price(symbol)
            if not expected_price or expected_price <= 0:
                logger.error(f"[BUY BLOCKED] {symbol} 가격 조회 실패")
                self._send_error_alert("매수 차단", symbol, "가격 조회 실패")
                return False

            raw_qty = krw_amount / expected_price
            expected_qty = self._format_qty(symbol, raw_qty)
            
            if expected_qty <= 0:
                logger.error(f"[BUY BLOCKED] {symbol} 수량 보정 후 0 - raw={raw_qty}")
                self._send_error_alert("매수 차단", symbol, f"수량 보정 후 0 (raw={raw_qty:.8f})")
                return False
            
            logger.info(f"[BUY] {symbol} 수량: {raw_qty:.8f} → {expected_qty} (precision={self._get_qty_precision(symbol)})")

            order = self.api.create_limit_buy(symbol, krw_amount)
            
            if not order:
                logger.error(f"[BUY FAILED] {symbol} 주문 응답 없음")
                self._send_error_alert("매수 실패", symbol, "주문 응답 없음")
                return False
            
            order_status = str(order.get("status", "")).lower()
            if order_status in ["canceled", "cancelled", "rejected", "expired"]:
                logger.error(f"[BUY FAILED] {symbol} 주문 상태: {order_status}")
                self._send_error_alert("매수 거부", symbol, f"주문 상태: {order_status}")
                return False
            
            actual_price, actual_qty, order_id = self._extract_fill_info(order, expected_price, expected_qty)
            
            if actual_price <= 0 or actual_qty <= 0:
                logger.error(f"[BUY FAILED] {symbol} 체결 정보 이상")
                self._send_error_alert("매수 실패", symbol, "체결 정보 이상 (가격 또는 수량 0)")
                return False
            
            slip_record = self.slippage_tracker.record(
                symbol=symbol, side="buy", expected_price=expected_price,
                actual_price=actual_price, qty=actual_qty, order_id=order_id
            )
            
            entry_price = actual_price
            qty = actual_qty

            ai_tp = float(ai_decision.get("tp_ratio", ai_decision.get("tp", 0.02))) * self.ai_tp_multiplier
            ai_sl = float(ai_decision.get("sl_ratio", ai_decision.get("sl", 0.01))) * self.ai_sl_reduction
            ai_conf = float(ai_decision.get("confidence", 0.5))
            ai_reason = ai_decision.get("reason", "")

            tp_levels = self._build_tp_levels(entry_price, ai_tp, ai_decision)
            strat_tp_price = entry_price * (1.0 + ai_tp)
            strat_sl_price = entry_price * (1.0 - ai_sl)

            # ================================================================
            # 🆕 v5.2.3: 스마트 트레일링 (TP1 전까지 비활성)
            # ================================================================
            trailing = {
                "enabled": False,  # 🔥 v5.2.3: 진입 시 비활성 → TP1 도달 시 활성화
                "trigger": self.trailing_trigger,
                "offset": self.trailing_offset,
                "highest_price": entry_price,
            }
            # ================================================================

            position_type = ai_decision.get("position_type", "scalp")
            holding_period = ai_decision.get("holding_period", "수시간")
            
            # Confidence 기반 배수 (저장용)
            conf_mult = 1.0
            if ai_conf >= 0.85:
                conf_mult = 1.5
            elif ai_conf >= 0.70:
                conf_mult = 1.2
            elif ai_conf >= 0.60:
                conf_mult = 1.0
            else:
                conf_mult = 0.7
            
            time_config = ai_decision.get("time_config", {})
            time_zone = time_config.get("zone_name", "일반") if time_config else "일반"
            time_mult = time_config.get("position_mult", 1.0) if time_config else 1.0
            tp_mult = self._calculate_dynamic_tp_multiplier(ai_decision)

            self.pm.open_position(
                symbol=symbol,
                qty=qty,
                price=entry_price,
                pf_weight=pf_weight,
                ai_tp=ai_tp,
                ai_sl=ai_sl,
                ai_confidence=ai_conf,
                ai_reason=ai_reason,
                strat_tp=strat_tp_price,
                strat_sl=strat_sl_price,
                strat_reason=f"AI 기반 TP/SL",
                strength=ai_conf,
                trailing=trailing,
                tp_levels=tp_levels,
                position_type=position_type,
                holding_period=holding_period,
                conf_mult=conf_mult,
                time_zone=time_zone,
                time_mult=time_mult,
                tp_mult=tp_mult,
                dynamic_mult=dynamic_mult,  # 🆕 v5.2.3: 동적 배수 저장
            )
            
            slip_pct = slip_record.get("slippage_pct", 0) if slip_record else 0
            logger.info(f"[BUY EXECUTED] {symbol} qty={qty:.6f} entry={entry_price:,.0f} (slip={slip_pct:+.2f}%)")
            return True

        except Exception as e:
            # 🆕 v5.3.0: error_handler 사용
            handle_error(e, f"BUY:{symbol}", notify=True)
            self._send_error_alert("매수 오류", symbol, str(e), severity="critical")
            traceback.print_exc()
            return False

    # ======================================================================
    # 🔥 v5.2.1b: 시장가 SELL (비율 방식 + 실제 잔고 기반 + SEMI 모드 승인)
    # ======================================================================
    def market_sell(self, symbol, pos, reason: str = "", ratio: float = 1.0, skip_approval: bool = False):
        """시장가 매도 (v5.3.0)"""
        try:
            expected_price = self._get_price(symbol)
            if expected_price is None or expected_price <= 0:
                logger.error(f"[SELL ERROR] {symbol} 가격 없음")
                self._send_error_alert("매도 실패", symbol, "가격 조회 실패")
                return False

            # SEMI 모드 승인 체크
            if Config.MODE == "SEMI" and not skip_approval:
                # 🆕 v5.3.1a: 타입 안전 변환
                entry = self._safe_float(pos.get("entry_price"), expected_price)
                if entry <= 0:
                    entry = expected_price
                pnl_pct = ((expected_price - entry) / max(entry, 1)) * 100
                
                if pnl_pct < 0:
                    logger.info(f"[SELL] {symbol} 손실 중 ({pnl_pct:.1f}%) - SEMI 모드 승인 요청")
                    return self._request_sell_approval(symbol, pos, expected_price, reason, sell_type="signal")

            # 실제 잔고 조회
            stored_qty = pos.get("qty", 0)
            actual_qty = self._get_actual_balance(symbol)
            
            logger.info(f"[SELL] {symbol} 저장수량={stored_qty:.6f} 실제잔고={actual_qty:.6f}")
            
            if actual_qty <= 0:
                logger.warning(f"[SELL SKIP] {symbol} 실제 잔고 없음 (저장값: {stored_qty:.6f})")
                self._remove_sl_pending(symbol)
                self.pm.close_position(symbol, expected_price)
                return True
            
            # 비율 적용 + 안전 마진
            if ratio >= 1.0:
                sell_qty = actual_qty * 0.9995
            else:
                sell_qty = actual_qty * ratio
            
            sell_qty = self._format_qty(symbol, sell_qty)
            
            if sell_qty <= 0:
                logger.error(f"[SELL ERROR] {symbol} 매도 수량 0 (포맷 후)")
                return False
            
            logger.info(f"[SELL] {symbol} 매도수량={sell_qty:.6f} (비율={ratio*100:.1f}%)")

            # 매도 실행
            try:
                order = self.api.create_limit_sell(symbol, sell_qty)
            except Exception as api_error:
                # 🆕 v5.3.0: error_handler 사용
                handle_error(api_error, f"SELL_API:{symbol}", notify=True)
                self._send_error_alert("매도 실패", symbol, f"5회 재시도 후 실패: {api_error}", severity="critical")
                return False
            
            if not order:
                logger.error(f"[SELL FAILED] {symbol} 주문 응답 없음")
                self._send_error_alert("매도 실패", symbol, "주문 응답 없음")
                return False
            
            actual_price, actual_qty_filled, order_id = self._extract_fill_info(order, expected_price, sell_qty)
            
            self.slippage_tracker.record(
                symbol=symbol, side="sell", expected_price=expected_price,
                actual_price=actual_price, qty=actual_qty_filled, order_id=order_id
            )

            try:
                # 🆕 v5.3.1a: 타입 안전 변환
                entry = self._safe_float(pos.get("entry_price"), actual_price)
                if entry <= 0:
                    entry = actual_price
                profit = (actual_price - entry) * actual_qty_filled
                if hasattr(self.rm, "register_trade_result"):
                    self.rm.register_trade_result(profit)
            except Exception as e:
                logger.error(f"[RISK REGISTER ERROR] {symbol}: {e}")

            if self.trade_logger:
                try:
                    exit_reason = reason if reason else "매도 체결"
                    self.trade_logger.log_exit(symbol, actual_price, exit_reason)
                except Exception as e:
                    logger.error(f"[TRADE LOG ERROR] {symbol}: {e}")

            self._remove_sl_pending(symbol)
            self.pm.close_position(symbol, actual_price)
            
            # 🆕 v5.3.1a: 타입 안전 변환
            entry = self._safe_float(pos.get("entry_price"), actual_price)
            if entry <= 0:
                entry = actual_price
            pnl_pct = ((actual_price - entry) / max(entry, 1)) * 100
            
            logger.info(f"[SELL EXECUTED] {symbol} price={actual_price:,.0f} PnL={pnl_pct:+.2f}% reason={reason}")
            return True
            
        except Exception as e:
            # 🆕 v5.3.0: error_handler 사용
            handle_error(e, f"SELL:{symbol}", notify=True)
            self._send_error_alert("매도 오류", symbol, str(e), severity="critical")
            traceback.print_exc()
            return False

    def close_position(self, symbol, pos, reason: str = ""):
        """수동 청산"""
        logger.info(f"[MANUAL CLOSE] {symbol} reason={reason}")
        return self.market_sell(symbol, pos, reason=reason if reason else "수동 청산", skip_approval=True)

    def check_trailing_stop(self, symbol, pos, price):
        tr = pos.get("trailing", {})
        if not tr or not tr.get("enabled", False):
            return False

        # 🆕 v5.3.1a: 타입 안전 변환
        entry_price = self._safe_float(pos.get("entry_price"), price)
        highest = self._safe_float(tr.get("highest_price"), entry_price)
        if highest <= 0:
            highest = price

        if price > highest:
            tr["highest_price"] = price
            pos["trailing"] = tr
            self.pm.update_position(symbol, pos)
            return False

        trigger = highest * (1 - tr["offset"])
        if price <= trigger:
            logger.info(f"[TRAILING STOP] {symbol} price={price} trigger={trigger}")
            return True

        return False

    def dca_buy(self, symbol, pos):
        try:
            stage = pos.get("dca_stage", 0)
            # 🆕 v5.3.1a: 타입 안전 변환
            entry = self._safe_float(pos.get("entry_price"), 0)
            if entry <= 0:
                logger.warning(f"[DCA SKIP] {symbol} entry_price 없음")
                return False

            max_dca = getattr(Config, "MAX_DCA_COUNT", 3)
            if stage >= max_dca:
                return False

            dca_levels = {0: 0.02, 1: 0.04, 2: 0.06, 3: 0.09, 4: 0.12}

            if stage not in dca_levels or stage >= self.max_dca_stage:
                return False

            price = self._get_price(symbol)
            if not price or price <= 0:
                return False
                
            diff = (price - entry) / max(entry, 1)

            if diff > -dca_levels[stage]:
                return False

            avail = self.rm.get_available_krw()
            if avail < Config.MIN_ORDER_AMOUNT:
                return False

            dca_amount = avail * Config.BASE_TRADE_RISK_RATIO * self.position_boost

            order = self.api.create_limit_buy(symbol, dca_amount)
            
            if not order:
                return False
                
            qty = round(dca_amount / price, 4)

            self.pm.add_dca(symbol, qty, price)

            logger.info(f"[DCA EXECUTED] {symbol} stage={stage+1}/{max_dca}")
            return True

        except Exception as e:
            # 🆕 v5.3.0: error_handler 사용
            handle_error(e, f"DCA:{symbol}", notify=False)
            return False

    # ======================================================================
    # 실시간 TP/SL 체크
    # ======================================================================
    def check_positions(self):
        positions = self.pm.get_all_positions()

        for symbol, pos in positions.items():
            try:
                price = self._get_price(symbol)
                if price is None or price <= 0:
                    continue

                # 🆕 v5.3.1a: 타입 안전 변환
                entry = self._safe_float(pos.get("entry_price"), 0)
                if entry <= 0:
                    logger.warning(f"[CHECK_POS] {symbol} entry_price 없음 - 스킵")
                    continue
                    
                tp_levels = pos.get("tp_levels") or []

                sl_price = self._safe_float(pos.get("sl"), 0)
                ai_sl = self._safe_float(pos.get("ai_sl"), 0)

                if tp_levels:
                    # SL 체크
                    if sl_price > 0 and price <= sl_price:
                        if Config.MODE == "SEMI":
                            self._request_sell_approval(symbol, pos, price, "SL 도달", sell_type="sl")
                        else:
                            self.market_sell(symbol, pos, reason="SL 손절")
                        continue
                    elif ai_sl > 0 and price <= entry * (1.0 - ai_sl):
                        pnl_pct = ((price - entry) / entry) * 100
                        if Config.MODE == "SEMI":
                            self._request_sell_approval(symbol, pos, price, f"AI SL 도달 ({pnl_pct:.1f}%)", sell_type="sl")
                        else:
                            self.market_sell(symbol, pos, reason="AI SL 손절")
                        continue
                else:
                    if self._apply_legacy_exit(symbol, pos, price, entry):
                        continue

                if tp_levels:
                    closed = self._handle_tp_levels(symbol, pos, price)
                    if closed:
                        continue

                # 트레일링 스탑 체크 (TP1 이후에만 활성화됨)
                if self.check_trailing_stop(symbol, pos, price):
                    if Config.MODE == "SEMI":
                        self._request_sell_approval(symbol, pos, price, "트레일링 스탑", sell_type="sl")
                    else:
                        self.market_sell(symbol, pos, reason="트레일링 스탑")
                    continue

                self.dca_buy(symbol, pos)

            except Exception as e:
                # 🆕 v5.3.0: error_handler 사용
                handle_error(e, f"CHECK_POS:{symbol}", notify=False)

    def execute(self, symbol, final_signal, ai_decision, pf_weight):
        """매매 실행"""
        try:
            if final_signal == "sell":
                pos = self.pm.get_position(symbol)
                if pos:
                    if Config.MODE == "SEMI":
                        current_price = self._get_price(symbol)
                        if current_price:
                            return self._request_sell_approval(
                                symbol, pos, current_price, 
                                "전략 신호 매도", sell_type="signal"
                            )
                        else:
                            logger.error(f"[EXECUTE] {symbol} 가격 조회 실패 - 매도 보류")
                            return False
                    else:
                        return self.market_sell(symbol, pos, reason="전략 신호 매도")
                return False

            if final_signal == "buy":
                if not self.aggressive and self.pm.has_position(symbol):
                    return False

                krw = self.rm.get_trade_amount(symbol, pf_weight)
                return self.market_buy(symbol, krw, ai_decision, pf_weight)

            return False

        except Exception as e:
            # 🆕 v5.3.0: error_handler 사용
            handle_error(e, f"EXECUTE:{symbol}", notify=True)
            return False

    def get_slippage_stats(self) -> Dict:
        return self.slippage_tracker.get_stats()

    def get_slippage_summary(self) -> str:
        stats = self.slippage_tracker.get_stats()
        if stats["total_trades"] == 0:
            return "📊 슬리피지 데이터 없음"
        return f"📊 슬리피지: {stats['avg_slippage_pct']:+.3f}% ({stats['total_trades']}건)"
    
    # ======================================================================
    # 🆕 v5.3.0 Phase B: 에러 통계 조회
    # ======================================================================
    def get_error_stats(self) -> Dict:
        """에러 통계 조회"""
        return error_handler.get_stats()
    
    def get_error_summary(self) -> str:
        """텔레그램용 에러 요약"""
        stats = error_handler.get_stats()
        if stats["total_errors"] == 0:
            return "✅ 에러 없음"
        
        lines = [f"🚨 <b>에러 통계</b>"]
        lines.append(f"총 에러: {stats['total_errors']}건")
        
        if stats.get("error_counts"):
            lines.append("")
            lines.append("<b>타입별:</b>")
            for error_type, count in list(stats["error_counts"].items())[:5]:
                lines.append(f"  • {error_type}: {count}건")
        
        return "\n".join(lines)
