# -*- coding: utf-8 -*-
"""
Phoenix v5.1.0d — CircuitBreaker (안전장치)

🆕 v5.1.0d 신규:
- 연속 손실 N회 시 자동 매매 중단
- 일일 손실률 N% 초과 시 자동 매매 중단
- API 연속 실패 N회 시 자동 매매 중단
- 쿨다운 후 자동 해제
- 텔레그램 긴급 알림

발동 조건 (기본값):
- 연속 5회 손실
- 일일 손실 3% 초과
- API 연속 10회 실패
"""

import threading
from datetime import datetime, timedelta
from typing import Dict, Optional, Callable

from bot.utils.logger import get_logger

logger = get_logger("CircuitBreaker")


class CircuitBreaker:
    """
    매매 안전장치 - 비정상 상황 감지 시 자동 중단
    
    발동 조건:
    - 연속 N회 손실
    - 일일 손실률 N% 초과
    - API 연속 실패 N회
    """
    
    def __init__(self, config: dict = None):
        config = config or {}
        
        # 설정값
        self.max_consecutive_losses = config.get('max_consecutive_losses', 5)
        self.max_daily_loss_pct = config.get('max_daily_loss_pct', 3.0)  # 3%
        self.max_api_failures = config.get('max_api_failures', 10)
        self.cooldown_minutes = config.get('cooldown_minutes', 30)
        
        # 상태 변수
        self.consecutive_losses = 0
        self.daily_pnl = 0.0
        self.daily_pnl_pct = 0.0
        self.api_failures = 0
        self.is_tripped = False
        self.trip_reason = None
        self.trip_time: Optional[datetime] = None
        self.last_reset_date = datetime.now().date()
        
        # 스레드 안전
        self.lock = threading.Lock()
        
        # 콜백 (텔레그램 알림용)
        self.alert_callback: Optional[Callable[[str], None]] = None
        
        logger.info(
            f"[CircuitBreaker] 초기화 완료 - "
            f"연속손실:{self.max_consecutive_losses}회, "
            f"일일손실:{self.max_daily_loss_pct}%, "
            f"API실패:{self.max_api_failures}회, "
            f"쿨다운:{self.cooldown_minutes}분"
        )
    
    def set_alert_callback(self, callback: Callable[[str], None]):
        """텔레그램 알림 콜백 설정"""
        self.alert_callback = callback
    
    def _daily_reset_check(self):
        """일일 리셋 체크 (자정 기준)"""
        today = datetime.now().date()
        if today > self.last_reset_date:
            self.daily_pnl = 0.0
            self.daily_pnl_pct = 0.0
            self.api_failures = 0
            self.last_reset_date = today
            logger.info("[CircuitBreaker] 일일 카운터 리셋")
    
    def record_trade(self, pnl: float, pnl_pct: float):
        """
        거래 결과 기록
        
        Args:
            pnl: 손익 금액 (KRW)
            pnl_pct: 손익률 (%)
        """
        with self.lock:
            self._daily_reset_check()
            
            self.daily_pnl += pnl
            self.daily_pnl_pct += pnl_pct
            
            if pnl < 0:
                self.consecutive_losses += 1
                logger.warning(f"[CircuitBreaker] 손실 기록 - 연속 {self.consecutive_losses}회")
            else:
                self.consecutive_losses = 0
            
            self._check_conditions()
    
    def record_api_failure(self):
        """API 실패 기록"""
        with self.lock:
            self._daily_reset_check()
            self.api_failures += 1
            logger.warning(f"[CircuitBreaker] API 실패 - 누적 {self.api_failures}회")
            self._check_conditions()
    
    def record_api_success(self):
        """API 성공 시 실패 카운터 감소"""
        with self.lock:
            if self.api_failures > 0:
                self.api_failures = max(0, self.api_failures - 1)
    
    def _check_conditions(self):
        """중단 조건 체크 (lock 내부에서 호출)"""
        if self.is_tripped:
            return
        
        # 조건 1: 연속 손실
        if self.consecutive_losses >= self.max_consecutive_losses:
            self._trip(f"연속 {self.consecutive_losses}회 손실")
            return
        
        # 조건 2: 일일 손실률
        if self.daily_pnl_pct <= -self.max_daily_loss_pct:
            self._trip(f"일일 손실 {self.daily_pnl_pct:.2f}% (한도: -{self.max_daily_loss_pct}%)")
            return
        
        # 조건 3: API 연속 실패
        if self.api_failures >= self.max_api_failures:
            self._trip(f"API 실패 {self.api_failures}회 누적")
            return
    
    def _trip(self, reason: str):
        """서킷 브레이커 발동 (lock 내부에서 호출)"""
        self.is_tripped = True
        self.trip_reason = reason
        self.trip_time = datetime.now()
        
        logger.critical(f"[CircuitBreaker] 🚨 매매 중단 발동: {reason}")
        
        # 텔레그램 긴급 알림
        if self.alert_callback:
            alert_msg = (
                f"🚨 <b>서킷브레이커 발동</b>\n\n"
                f"📛 사유: {reason}\n"
                f"⏰ 시간: {self.trip_time.strftime('%H:%M:%S')}\n"
                f"📊 일일 손익: {self.daily_pnl:,.0f}원 ({self.daily_pnl_pct:+.2f}%)\n\n"
                f"⚠️ 모든 신규 매매가 중단되었습니다.\n"
                f"🔧 <code>/cb_reset</code> 명령으로 수동 해제 가능\n"
                f"⏱ {self.cooldown_minutes}분 후 자동 해제"
            )
            try:
                self.alert_callback(alert_msg)
            except Exception as e:
                logger.error(f"[CircuitBreaker] 알림 전송 실패: {e}")
    
    def can_trade(self) -> bool:
        """거래 가능 여부 확인"""
        with self.lock:
            if not self.is_tripped:
                return True
            
            # 쿨다운 자동 해제 체크
            if self.trip_time and self.cooldown_minutes > 0:
                elapsed = (datetime.now() - self.trip_time).total_seconds() / 60
                if elapsed >= self.cooldown_minutes:
                    logger.info(f"[CircuitBreaker] 쿨다운 {self.cooldown_minutes}분 경과 - 자동 해제")
                    self._reset_internal(auto=True)
                    return True
            
            return False
    
    def _reset_internal(self, auto: bool = False):
        """내부 리셋 (lock 내부에서 호출)"""
        prev_reason = self.trip_reason
        
        self.is_tripped = False
        self.trip_reason = None
        self.trip_time = None
        self.consecutive_losses = 0
        self.api_failures = 0
        
        reset_type = "자동" if auto else "수동"
        logger.info(f"[CircuitBreaker] ✅ {reset_type} 리셋 완료 (이전 사유: {prev_reason})")
        
        if self.alert_callback:
            try:
                self.alert_callback(
                    f"✅ <b>서킷브레이커 {reset_type} 해제</b>\n\n"
                    f"매매가 재개됩니다."
                )
            except:
                pass
    
    def reset(self, manual: bool = False):
        """
        서킷 브레이커 리셋
        
        Args:
            manual: 수동 리셋 여부 (텔레그램 명령)
        """
        with self.lock:
            if not self.is_tripped:
                return False
            self._reset_internal(auto=not manual)
            return True
    
    def get_status(self) -> Dict:
        """현재 상태 조회"""
        with self.lock:
            return {
                'is_tripped': self.is_tripped,
                'trip_reason': self.trip_reason,
                'trip_time': self.trip_time.isoformat() if self.trip_time else None,
                'consecutive_losses': self.consecutive_losses,
                'daily_pnl': self.daily_pnl,
                'daily_pnl_pct': self.daily_pnl_pct,
                'api_failures': self.api_failures,
                'limits': {
                    'max_consecutive_losses': self.max_consecutive_losses,
                    'max_daily_loss_pct': self.max_daily_loss_pct,
                    'max_api_failures': self.max_api_failures,
                    'cooldown_minutes': self.cooldown_minutes
                }
            }
    
    def get_remaining_cooldown(self) -> int:
        """남은 쿨다운 시간 (분)"""
        with self.lock:
            if not self.is_tripped or not self.trip_time:
                return 0
            
            elapsed = (datetime.now() - self.trip_time).total_seconds() / 60
            remaining = self.cooldown_minutes - elapsed
            return max(0, int(remaining))
