# -*- coding: utf-8 -*-
"""
Phoenix v5.1.0d — PositionSyncManager (포지션 동기화)

🆕 v5.1.0d 신규:
- 로컬 포지션과 거래소 실제 잔고 비교
- 불일치 감지 시 텔레그램 알림
- 강제 동기화 기능
"""

import json
import threading
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Callable

from bot.utils.logger import get_logger

logger = get_logger("PositionSync")


class PositionSyncManager:
    """포지션 동기화 관리자"""
    
    def __init__(
        self, 
        api_client, 
        position_manager=None,
        threshold_pct: float = 5.0,  # 5% 이상 차이 시 불일치 판단
        alert_callback: Optional[Callable[[str], None]] = None
    ):
        """
        Args:
            api_client: 빗썸 API 클라이언트
            position_manager: 포지션 매니저 (로컬 포지션 관리)
            threshold_pct: 불일치 판단 임계값 (%)
            alert_callback: 텔레그램 알림 콜백
        """
        self.api = api_client
        self.pm = position_manager
        self.threshold_pct = threshold_pct
        self.alert_callback = alert_callback
        self.last_sync_time: Optional[datetime] = None
        self.lock = threading.Lock()
        
        logger.info(f"[PositionSync] 초기화 완료 - 임계값: {threshold_pct}%")
    
    def set_position_manager(self, pm):
        """포지션 매니저 설정 (런타임 주입)"""
        self.pm = pm
    
    def set_alert_callback(self, callback: Callable[[str], None]):
        """알림 콜백 설정"""
        self.alert_callback = callback
    
    def get_exchange_balances(self) -> Dict[str, float]:
        """
        거래소 실제 잔고 조회
        
        Returns:
            {코인명: 수량} 딕셔너리
        """
        try:
            balances = {}
            response = self.api.fetch_balance()
            
            if not response:
                logger.error("[PositionSync] 거래소 잔고 응답 없음")
                return {}
            
            for currency, info in response.items():
                # 메타데이터 스킵
                if currency in ['KRW', 'free', 'used', 'total', 'info', 'timestamp', 'datetime']:
                    continue
                
                if isinstance(info, dict):
                    available = float(info.get('free', 0) or 0)
                    in_use = float(info.get('used', 0) or 0)
                    total = float(info.get('total', 0) or 0)
                    
                    # total이 없으면 계산
                    if total == 0:
                        total = available + in_use
                    
                    if total > 0:
                        balances[currency] = total
            
            return balances
            
        except Exception as e:
            logger.error(f"[PositionSync] 거래소 잔고 조회 실패: {e}")
            return {}
    
    def get_local_positions(self) -> Dict[str, float]:
        """
        로컬 포지션 수량 조회
        
        Returns:
            {코인명: 수량} 딕셔너리
        """
        if not self.pm:
            return {}
        
        try:
            positions = self.pm.get_all_positions()
            local = {}
            
            for symbol, pos in positions.items():
                # "BTC/KRW" -> "BTC"
                coin = symbol.replace("/KRW", "").replace("_KRW", "")
                qty = pos.get("qty", 0)
                if qty > 0:
                    local[coin] = qty
            
            return local
            
        except Exception as e:
            logger.error(f"[PositionSync] 로컬 포지션 조회 실패: {e}")
            return {}
    
    def sync_and_verify(self) -> Dict:
        """
        포지션 동기화 및 검증 실행
        
        Returns:
            {
                'synced': bool,
                'discrepancies': [...],
                'exchange_balances': {...},
                'local_positions': {...}
            }
        """
        result = {
            'synced': True,
            'discrepancies': [],
            'exchange_balances': {},
            'local_positions': {},
            'sync_time': datetime.now().isoformat()
        }
        
        with self.lock:
            try:
                # 1) 거래소 잔고 조회
                exchange_balances = self.get_exchange_balances()
                result['exchange_balances'] = exchange_balances
                
                # 2) 로컬 포지션 로드
                local_positions = self.get_local_positions()
                result['local_positions'] = local_positions
                
                # 3) 불일치 검사
                all_coins = set(exchange_balances.keys()) | set(local_positions.keys())
                
                for coin in all_coins:
                    exchange_amount = exchange_balances.get(coin, 0)
                    local_amount = local_positions.get(coin, 0)
                    
                    # 차이 계산
                    max_amount = max(exchange_amount, local_amount)
                    if max_amount > 0:
                        diff = exchange_amount - local_amount
                        diff_pct = abs(diff) / max_amount * 100
                        
                        if diff_pct > self.threshold_pct:
                            discrepancy = {
                                'coin': coin,
                                'symbol': f"{coin}/KRW",
                                'exchange': exchange_amount,
                                'local': local_amount,
                                'diff': diff,
                                'diff_pct': diff_pct
                            }
                            result['discrepancies'].append(discrepancy)
                            result['synced'] = False
                
                # 4) 불일치 발견 시 알림
                if result['discrepancies']:
                    self._notify_discrepancies(result['discrepancies'])
                
                self.last_sync_time = datetime.now()
                logger.info(f"[PositionSync] 동기화 검증 완료 - 불일치: {len(result['discrepancies'])}건")
                
            except Exception as e:
                logger.error(f"[PositionSync] 동기화 검증 실패: {e}")
                result['synced'] = False
                result['error'] = str(e)
        
        return result
    
    def _notify_discrepancies(self, discrepancies: List[Dict]):
        """불일치 알림 전송"""
        msg = "⚠️ <b>포지션 불일치 감지</b>\n\n"
        
        for d in discrepancies:
            msg += (
                f"• <b>{d['coin']}</b>\n"
                f"  거래소: {d['exchange']:.6f}\n"
                f"  로컬: {d['local']:.6f}\n"
                f"  차이: {d['diff']:+.6f} ({d['diff_pct']:.1f}%)\n\n"
            )
        
        msg += "🔧 <code>/sync_force</code> 명령으로 강제 동기화 가능"
        
        logger.warning(f"[PositionSync] 불일치 발견: {discrepancies}")
        
        if self.alert_callback:
            try:
                self.alert_callback(msg)
            except Exception as e:
                logger.error(f"[PositionSync] 알림 전송 실패: {e}")
    
    def force_sync_from_exchange(self) -> Dict:
        """
        거래소 기준으로 로컬 포지션 강제 동기화
        
        ⚠️ 주의: 로컬 포지션이 거래소 잔고로 덮어씌워집니다.
        진입가, 전략 정보 등은 유실됩니다.
        
        Returns:
            동기화 결과
        """
        result = {
            'success': False,
            'synced_coins': [],
            'removed_coins': [],
            'message': ''
        }
        
        with self.lock:
            try:
                if not self.pm:
                    result['message'] = 'PositionManager 미연결'
                    return result
                
                # 1) 거래소 잔고 조회
                exchange_balances = self.get_exchange_balances()
                
                if not exchange_balances:
                    logger.warning("[PositionSync] 거래소 잔고가 비어있음")
                
                # 2) 기존 로컬 포지션
                local_positions = self.pm.get_all_positions()
                
                # 3) 로컬에만 있는 포지션 제거
                for symbol in list(local_positions.keys()):
                    coin = symbol.replace("/KRW", "").replace("_KRW", "")
                    if coin not in exchange_balances or exchange_balances[coin] <= 0:
                        self.pm.remove_position(symbol)
                        result['removed_coins'].append(symbol)
                        logger.info(f"[PositionSync] 포지션 제거: {symbol}")
                
                # 4) 거래소에 있는 코인으로 포지션 업데이트
                for coin, qty in exchange_balances.items():
                    symbol = f"{coin}/KRW"
                    
                    if qty <= 0:
                        continue
                    
                    # 현재가 조회
                    current_price = 0
                    try:
                        ticker = self.api.fetch_ticker(symbol)
                        current_price = ticker.get('last', 0)
                    except:
                        pass
                    
                    existing = self.pm.get_position(symbol)
                    
                    if existing:
                        # 수량만 업데이트
                        existing['qty'] = qty
                        existing['synced_at'] = datetime.now().isoformat()
                        self.pm.update_position(symbol, existing)
                    else:
                        # 새 포지션 생성 (진입가 = 현재가로 추정)
                        new_pos = {
                            'qty': qty,
                            'entry_price': current_price,
                            'entry_time': datetime.now().isoformat(),
                            'strategy': 'sync',
                            'synced_at': datetime.now().isoformat(),
                            'note': '동기화로 추가됨'
                        }
                        self.pm.add_position(symbol, new_pos)
                    
                    result['synced_coins'].append(symbol)
                
                result['success'] = True
                result['message'] = f"동기화 완료: {len(result['synced_coins'])}개 코인"
                
                logger.info(f"[PositionSync] 강제 동기화 완료: {result}")
                
            except Exception as e:
                logger.error(f"[PositionSync] 강제 동기화 실패: {e}")
                result['message'] = str(e)
        
        return result
    
    def get_sync_status(self) -> Dict:
        """동기화 상태 조회"""
        with self.lock:
            exchange = self.get_exchange_balances()
            local = self.get_local_positions()
            
            return {
                'last_sync_time': self.last_sync_time.isoformat() if self.last_sync_time else None,
                'exchange_count': len(exchange),
                'local_count': len(local),
                'exchange_coins': list(exchange.keys()),
                'local_coins': list(local.keys())
            }
