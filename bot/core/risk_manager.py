# -*- coding: utf-8 -*-
"""
Phoenix v5.0.9a — RiskManager (전략 1 추가)

v5.0.8 기반 + 최소 수정:
- 전략 1 (확신도 사이징) 추가
- time_config 파라미터 추가
"""

import threading
from datetime import datetime
from typing import Dict, Any, Optional

from config import Config
from bot.utils.logger import get_logger

logger = get_logger("RiskManager")


class RiskManager:
    """개선된 리스크 관리자"""

    # 🔥 v5.0.9a: 확신도 사이징 설정 (전략 1)
    CONFIDENCE_MULTIPLIERS = {
        0.85: 1.5,   # conf >= 0.85 → ×1.5
        0.70: 1.2,   # conf >= 0.70 → ×1.2
        0.60: 1.0,   # conf >= 0.60 → ×1.0
        0.00: 0.7,   # conf <  0.60 → ×0.7
    }

    def __init__(self, api, position_manager, datalayer=None, global_risk=None):
        self.api = api
        self.pm = position_manager
        self.dl = datalayer
        self.global_risk = global_risk

        self.lock = threading.Lock()

        # 일일 손익 추적
        self.daily_start_value = None
        self.daily_date = None
        
        # 최고점 추적 (드로우다운)
        self.peak_value = None

        # Aggressive 모드
        self.aggressive = getattr(Config, "AGGRESSIVE_MODE", False)

        # 연속 손실 카운터
        self.loss_streak = 0
        
        logger.info(f"[RiskManager v5.0.9a] 초기화 (전략 1 확신도 사이징 추가)")

    # ============================================================
    # 데이터 조회 (WebSocket fallback REST)
    # ============================================================
    def _fetch_balance(self) -> Dict:
        if self.dl and hasattr(self.dl, "get_balance"):
            bal = self.dl.get_balance()
            if bal:
                return bal
        return self.api.fetch_balance()

    def _fetch_price(self, symbol: str) -> Optional[float]:
        if self.dl and hasattr(self.dl, "get_price"):
            p = self.dl.get_price(symbol)
            if p:
                return p
        try:
            ticker = self.api.fetch_ticker(symbol)
            return ticker.get("last")
        except:
            return None

    # ============================================================
    # 실시간 총 자본금 계산
    # ============================================================
    def get_total_capital(self) -> float:
        if not Config.USE_REALTIME_CAPITAL:
            return Config.BASE_CAPITAL
        
        try:
            balance = self._fetch_balance()
            krw_total = balance.get("KRW", {}).get("total", 0)
            coin_value = self.calculate_positions_value()
            total = krw_total + coin_value
            capital = total * Config.CAPITAL_SAFETY_MARGIN
            capital = max(capital, Config.MIN_ORDER_AMOUNT * 10)
            
            logger.debug(f"[CAPITAL] KRW={krw_total:,.0f}, Coin={coin_value:,.0f}, Total={capital:,.0f}")
            
            return capital
            
        except Exception as e:
            logger.error(f"[CAPITAL ERROR] {e}")
            return Config.BASE_CAPITAL

    def calculate_positions_value(self) -> float:
        total = 0.0
        with self.lock:
            positions = self.pm.get_all_positions()

        for symbol, pos in positions.items():
            try:
                price = self._fetch_price(symbol)
                if price:
                    total += pos.get("qty", 0) * price
            except:
                continue

        return total

    def get_available_krw(self) -> float:
        bal = self._fetch_balance()
        return float(bal.get("KRW", {}).get("free", 0))

    # ============================================================
    # 비중 상한 체크
    # ============================================================
    def check_position_weight_cap(self, symbol: str, additional_krw: float = 0) -> Dict:
        total_capital = self.get_total_capital()
        
        if total_capital <= 0:
            return {"allowed": False, "current_weight": 0, "max_allowed_krw": 0, "reason": "자본금 0"}
        
        current_value = 0
        pos = self.pm.get_position(symbol)
        if pos:
            price = self._fetch_price(symbol)
            if price:
                current_value = pos.get("qty", 0) * price
        
        current_weight = current_value / total_capital
        new_weight = (current_value + additional_krw) / total_capital
        max_weight = Config.POSITION_WEIGHT_CAP
        max_allowed_krw = (max_weight * total_capital) - current_value
        max_allowed_krw = max(0, max_allowed_krw)
        
        allowed = new_weight <= max_weight
        
        if not allowed:
            logger.warning(
                f"[WEIGHT CAP] {symbol} 비중 상한 초과: "
                f"현재 {current_weight*100:.1f}% + 추가 {additional_krw:,.0f} = {new_weight*100:.1f}% > {max_weight*100:.1f}%"
            )
        
        return {
            "allowed": allowed,
            "current_weight": current_weight,
            "new_weight": new_weight,
            "max_allowed_krw": max_allowed_krw,
            "reason": "" if allowed else "비중 상한 초과",
        }

    # ============================================================
    # 추가 매수 횟수 제한
    # ============================================================
    def check_dca_limit(self, symbol: str) -> Dict:
        pos = self.pm.get_position(symbol)
        
        if not pos:
            return {"allowed": True, "current_count": 0, "remaining": Config.MAX_DCA_COUNT}
        
        current_count = pos.get("dca_stage", 0)
        remaining = Config.MAX_DCA_COUNT - current_count
        allowed = remaining > 0
        
        if not allowed:
            logger.warning(f"[DCA LIMIT] {symbol} 추가 매수 횟수 초과: {current_count}/{Config.MAX_DCA_COUNT}")
        
        return {
            "allowed": allowed,
            "current_count": current_count,
            "remaining": max(0, remaining),
            "reason": "" if allowed else "추가 매수 횟수 초과",
        }

    # ============================================================
    # 드로우다운 관리
    # ============================================================
    def check_drawdown(self) -> Dict:
        current_value = self.get_total_capital() / Config.CAPITAL_SAFETY_MARGIN
        
        if self.peak_value is None or current_value > self.peak_value:
            self.peak_value = current_value
        
        if self.peak_value <= 0:
            return {"status": "ok", "drawdown_pct": 0}
        
        drawdown = (self.peak_value - current_value) / self.peak_value
        
        if drawdown >= Config.DRAWDOWN_LIMIT:
            logger.warning(f"[DRAWDOWN] 방어 모드: {drawdown*100:.1f}% 하락")
            return {
                "status": "blocked",
                "drawdown_pct": drawdown * 100,
                "reason": f"드로우다운 {drawdown*100:.1f}% - 방어 모드",
            }
        elif drawdown >= Config.DRAWDOWN_LIMIT * 0.7:
            return {
                "status": "warning",
                "drawdown_pct": drawdown * 100,
                "reason": f"드로우다운 경고 {drawdown*100:.1f}%",
            }
        
        return {"status": "ok", "drawdown_pct": drawdown * 100}

    # ============================================================
    # 일일 손실 제한
    # ============================================================
    def initialize_daily_value(self):
        total = self.get_total_capital() / Config.CAPITAL_SAFETY_MARGIN
        self.daily_start_value = total
        self.daily_date = datetime.utcnow().date()
        logger.info(f"[DAILY INIT] 평가액 = {total:,.0f} KRW")

    def check_daily_loss(self) -> Dict:
        if self.daily_start_value is None:
            self.initialize_daily_value()

        if datetime.utcnow().date() != self.daily_date:
            self.initialize_daily_value()

        current = self.get_total_capital() / Config.CAPITAL_SAFETY_MARGIN
        
        if self.daily_start_value <= 0:
            return {"status": "ok"}

        daily_loss = (self.daily_start_value - current) / self.daily_start_value

        limit = Config.DAILY_LOSS_LIMIT * (1.8 if self.aggressive else 1.0)

        if daily_loss >= limit:
            msg = f"일일 손실 한도 초과 ({daily_loss*100:.1f}%)"
            logger.warning(f"[DAILY LOSS] {msg}")
            return {"status": "blocked", "reason": msg, "daily_loss_pct": daily_loss * 100}

        return {"status": "ok", "daily_loss_pct": daily_loss * 100}

    # ============================================================
    # 연속 손실 감지
    # ============================================================
    def register_trade_result(self, profit_krw: float):
        if profit_krw < 0:
            self.loss_streak += 1
            logger.info(f"[LOSS STREAK] {self.loss_streak}연속 손실")
        else:
            self.loss_streak = 0

    def check_loss_streak(self) -> Dict:
        max_streak = 5 if self.aggressive else 3
        
        if self.loss_streak >= max_streak:
            return {
                "status": "blocked",
                "reason": f"연속 {self.loss_streak}회 손실 - 자동 홀드",
                "loss_streak": self.loss_streak,
            }
        return {"status": "ok", "loss_streak": self.loss_streak}

    # ============================================================
    # 전체 리스크 체크
    # ============================================================
    def check_limits(self) -> Dict:
        reasons = []
        allowed = True

        daily = self.check_daily_loss()
        if daily["status"] == "blocked":
            allowed = False
            reasons.append(daily["reason"])

        drawdown = self.check_drawdown()
        if drawdown["status"] == "blocked":
            allowed = False
            reasons.append(drawdown["reason"])

        streak = self.check_loss_streak()
        if streak["status"] == "blocked":
            allowed = False
            reasons.append(streak["reason"])

        with self.lock:
            pos_count = len(self.pm.get_all_positions())

        max_pos = int(Config.MAX_OPEN_POSITIONS * (1.5 if self.aggressive else 1.0))

        if pos_count >= max_pos:
            allowed = False
            reasons.append(f"최대 포지션 수 초과 ({pos_count}/{max_pos})")

        return {"can_trade": allowed, "reasons": reasons}

    # ============================================================
    # 🔥 v5.0.9a: 확신도 배수 계산 (전략 1)
    # ============================================================
    def _get_confidence_multiplier(self, ai_confidence: float) -> float:
        """AI 확신도 기반 포지션 배수 반환"""
        for threshold, mult in sorted(self.CONFIDENCE_MULTIPLIERS.items(), reverse=True):
            if ai_confidence >= threshold:
                return mult
        return 0.7  # 기본값

    # ============================================================
    # 🔥 v5.0.9a: 진입 금액 계산 (전략 1, 4 적용)
    # ============================================================
    def get_trade_amount(self, symbol: str, pf_weight: float, is_dca: bool = False, 
                         btc_mode: Optional[Dict] = None,
                         time_config: Optional[Dict] = None,
                         ai_confidence: float = 0.5) -> float:
        """
        포트폴리오 비중 기반 진입 금액 계산
        
        🔥 v5.0.9a 추가:
        - 전략 1: 확신도 사이징 (ai_confidence)
        - 전략 4: 시간대 조절 (time_config)
        """
        total_capital = self.get_total_capital()
        free_krw = self.get_available_krw()

        # 1) 기본 목표 금액
        target = total_capital * pf_weight

        # 2) Aggressive 모드 부스트
        if self.aggressive:
            target *= 1.4

        # 3) 시장 위험도 반영
        if self.global_risk:
            risk_level = float(self.global_risk.get_risk_value())
            if risk_level > 0.7:
                target *= 0.4
            elif risk_level > 0.5:
                target *= 0.7
            elif self.aggressive:
                target *= 1.3

        # 4) BTC 모드 반영
        if btc_mode:
            position_mult = btc_mode.get("position_mult", 1.0)
            
            if position_mult <= 0:
                logger.warning(f"[TRADE AMOUNT] {symbol} BTC 급락장 - 진입 차단")
                return 0
            
            target *= position_mult
            logger.info(f"[BTC MODE] {symbol} 포지션 ×{position_mult} ({btc_mode.get('label', 'N/A')})")

        # 🔥 5) v5.0.9a: 시간대 조절 (전략 4)
        if time_config:
            time_mult = time_config.get("position_mult", 1.0)
            zone_name = time_config.get("zone_name", "일반")
            
            if time_mult != 1.0:
                original = target
                target *= time_mult
                logger.info(f"[TIME ZONE] {symbol} 포지션: {original:,.0f} × {time_mult} = {target:,.0f} ({zone_name})")

        # 🔥 6) v5.0.9a: 확신도 사이징 (전략 1)
        conf_mult = self._get_confidence_multiplier(ai_confidence)
        if conf_mult != 1.0:
            original = target
            target *= conf_mult
            logger.info(f"[CONFIDENCE] {symbol} 포지션: {original:,.0f} × {conf_mult} = {target:,.0f} (conf={ai_confidence:.2f})")

        # 7) 비중 상한 체크
        weight_check = self.check_position_weight_cap(symbol, target)
        if not weight_check["allowed"]:
            target = weight_check["max_allowed_krw"]

        # 8) DCA 횟수 체크
        if is_dca:
            dca_check = self.check_dca_limit(symbol)
            if not dca_check["allowed"]:
                logger.warning(f"[TRADE AMOUNT] {symbol} DCA 횟수 초과")
                return 0

        # 9) 가용 KRW 제한
        final_amt = min(target, free_krw * 0.85)
        
        if final_amt < Config.MIN_ORDER_AMOUNT:
            logger.warning(f"[TRADE AMOUNT] {symbol} 잔고 부족 - 스킵")
            return 0
        
        logger.info(
            f"[TRADE AMOUNT] {symbol} pf={pf_weight:.2f} → "
            f"target={target:,.0f}, final={final_amt:,.0f}"
        )

        return max(0, final_amt)

    # ============================================================
    # 리포트용 요약
    # ============================================================
    def get_risk_summary(self) -> Dict:
        daily = self.check_daily_loss()
        drawdown = self.check_drawdown()
        limits = self.check_limits()
        
        with self.lock:
            pos_count = len(self.pm.get_all_positions())
        
        return {
            "can_trade": limits["can_trade"],
            "reasons": limits["reasons"],
            "total_capital": self.get_total_capital(),
            "available_krw": self.get_available_krw(),
            "positions_value": self.calculate_positions_value(),
            "position_count": pos_count,
            "max_positions": Config.MAX_OPEN_POSITIONS,
            "daily_loss_pct": daily.get("daily_loss_pct", 0),
            "drawdown_pct": drawdown.get("drawdown_pct", 0),
            "loss_streak": self.loss_streak,
        }
