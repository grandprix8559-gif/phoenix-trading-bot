# -*- coding: utf-8 -*-
"""
Phoenix v5.1.0a — PositionManager (동적 분할 진입 + SL 홀드 + 빗썸 동기화)

🔥 v5.1.0a 추가:
- sync_with_exchange(): 빗썸 잔고와 포지션 동기화
- _add_synced_position(): 동기화로 추가된 포지션 생성
- _get_avg_buy_price(): 평균 매수가 조회
- get_sync_status(): 동기화 상태 미리보기

🔥 v5.1.0 추가:
- entry_stage: 1차/2차/3차 진입 단계 관리
- sl_hold_until: SL 홀드 만료 시각 관리
- 동적 분할 진입 비율 저장

🔥 v5.0.9d 수정:
- open_position()에 전략 정보 파라미터 추가

기존 기능:
- Race Condition 방지 (threading.Lock)
- JSON Atomic Save (temp → rename)
- DCA / TP / SL / AI 메타 + Dynamic TP / Trailing 메타까지 저장
"""

import json
import os
import threading
from datetime import datetime, timedelta
from typing import Optional, Dict, List
from config import Config
from bot.utils.logger import get_logger

logger = get_logger("PositionManager")


class PositionManager:

    def __init__(self, filename="positions.json"):
        """
        🔥 v5.0.4: 경로 처리 개선
        - filename이 절대 경로면 그대로 사용
        - 상대 경로면 현재 작업 디렉토리 기준
        """
        self.filename = filename
        self.lock = threading.Lock()
        self.positions = self._load()
        
        # 🆕 v5.1.0: SL 홀드 만료 시각 (파일에서 로드)
        self.sl_hold_until: dict = self._load_sl_hold()
        
        # 🔥 로드된 파일 경로 로깅
        abs_path = os.path.abspath(self.filename)
        logger.info(f"[PositionManager v5.1.0a] 파일 경로: {abs_path}")
        logger.info(f"[PositionManager] 로드된 포지션: {list(self.positions.keys())}")
    
    def _load_sl_hold(self) -> dict:
        """🆕 v5.1.0: sl_hold_until 로드"""
        if not os.path.exists(self.filename):
            return {}
        try:
            with open(self.filename, "r", encoding="utf-8") as f:
                data = json.load(f)
                sl_hold_data = data.get("sl_hold_until", {})
                # ISO 문자열 → datetime 변환
                result = {}
                for symbol, dt_str in sl_hold_data.items():
                    try:
                        from datetime import datetime
                        result[symbol] = datetime.fromisoformat(dt_str)
                    except:
                        pass
                return result
        except:
            return {}

    # ============================================================
    # 🔒 Thread-safe JSON Load
    # ============================================================
    def _load(self):
        if not os.path.exists(self.filename):
            return {}

        try:
            with open(self.filename, "r", encoding="utf-8") as f:
                data = json.load(f)
                # 🆕 v5.1.0: 새 구조 지원 {"positions": {...}, "sl_hold_until": {...}}
                if "positions" in data:
                    return data.get("positions", {})
                # 기존 구조 호환 {"BTC/KRW": {...}, ...}
                return data
        except Exception as e:
            logger.error(f"[POSITION LOAD ERROR] {e}")
            return {}

    # ============================================================
    # 🔐 Atomic Save (임시 파일 → rename)
    # ============================================================
    def _save(self):
        try:
            tmp = self.filename + ".tmp"
            
            # 🆕 v5.1.0: 새 구조로 저장
            save_data = {
                "positions": self.positions,
                "sl_hold_until": {k: v.isoformat() for k, v in self.sl_hold_until.items()} if self.sl_hold_until else {}
            }

            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(save_data, f, indent=4, ensure_ascii=False)

            # tmp → 원본 파일로 원자적 교체
            os.replace(tmp, self.filename)

        except Exception as e:
            logger.error(f"[POSITION SAVE ERROR] {e}")

    # ============================================================
    # 조회 관련 (모두 lock 보호)
    # ============================================================
    def has_position(self, symbol: str) -> bool:
        with self.lock:
            return symbol in self.positions

    def get_position(self, symbol: str):
        with self.lock:
            return self.positions.get(symbol)

    def get_all_positions(self):
        # 외부에서 수정 못 하도록 copy 반환
        with self.lock:
            return dict(self.positions)

    # ============================================================
    # 신규 포지션 생성
    #  - ExecutionEngine.market_buy() 에서 호출
    #  - 동적 TP 레벨 / 트레일링 메타까지 같이 저장
    # ============================================================
    def open_position(
        self,
        symbol: str,
        qty: float,
        price: float,
        pf_weight: float,
        ai_tp: float,
        ai_sl: float,
        ai_confidence: float,
        ai_reason: str,
        strat_tp: float = None,
        strat_sl: float = None,
        strat_reason: str = "",
        strength: float = 0.0,
        trailing: dict = None,
        tp_levels: list = None,
        # 🔥 v5.0.9d: 전략 정보 파라미터 추가
        position_type: str = "scalp",
        holding_period: str = "",
        conf_mult: float = 1.0,
        time_zone: str = "",
        time_mult: float = 1.0,
        tp_mult: float = 1.0,
        dynamic_mult: float = 1.0,
        # 🆕 v5.1.0: 동적 분할 진입 파라미터
        entry_stage: int = 1,
        entry_ratio: float = 0.4,
        dca_interval: float = -0.05,
        trend: str = "neutral",
        atr_grade: str = "mid",
    ) -> bool:
        """
        새로운 포지션 열기
        - v4.3: AI TP/SL + confidence + reason 저장
        - v4.4: thread-safe + atomic save
        - v4.4 step1: dynamic TP levels / trailing 메타 확장
        - v5.0.9d: 전략 정보 (position_type, holding_period, 배수들) 저장
        - v5.1.0: 동적 분할 진입 (entry_stage, entry_ratio, dca_interval)
        """

        if trailing is None:
            trailing = {
                "enabled": False,
                "trigger": None,
                "offset": None,
                "highest_price": price,
            }

        if tp_levels is None:
            tp_levels = []

        new_pos = {
            "symbol": symbol,
            "qty": qty,
            "entry_price": price,
            "opened_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),

            # ---------------------------
            # 전략 메타
            # ---------------------------
            "pf_weight": pf_weight,     # 포트폴리오 자금 비중
            "tp": strat_tp,             # 메인 TP 가격 (예: TP2 정도)
            "sl": strat_sl,             # 메인 SL 가격
            "strat_reason": strat_reason,
            "strength": strength,

            # ---------------------------
            # AI 메타
            # ---------------------------
            "ai_tp": ai_tp,             # AI 추천 TP 비율 (예: 0.02 = +2%)
            "ai_sl": ai_sl,             # AI 추천 SL 비율 (예: 0.01 = -1%)
            "ai_confidence": ai_confidence,
            "ai_reason": ai_reason,

            # ---------------------------
            # DCA 메타
            # ---------------------------
            "dca_stage": 0,
            "dca_history": [],

            # ---------------------------
            # Dynamic TP / Trailing 메타
            # ---------------------------
            "initial_qty": qty,         # 부분청산 기준이 되는 최초 수량
            "tp_levels": tp_levels,     # [{id, name, price, portion, executed}]
            "trailing": trailing,       # {enabled, trigger, offset, highest_price}

            # ---------------------------
            # 🔥 v5.0.9d: 전략 정보
            # ---------------------------
            "position_type": position_type,   # "scalp" / "swing"
            "holding_period": holding_period, # 예상 보유기간 (예: "수시간", "1-2일")
            "conf_mult": conf_mult,           # 확신도 배수
            "time_zone": time_zone,           # 시간대 (예: "아시아 오전")
            "time_mult": time_mult,           # 시간대 배수
            "tp_mult": tp_mult,
            "dynamic_mult": dynamic_mult,               # TP 배수
            
            # ---------------------------
            # 🆕 v5.1.0: 동적 분할 진입
            # ---------------------------
            "entry_stage": entry_stage,       # 현재 진입 단계 (1/2/3)
            "entry_ratio": entry_ratio,       # 1차 진입 비율
            "dca_interval": dca_interval,     # 분할 간격 (-0.02 ~ -0.10)
            "trend": trend,                   # 장기 추세 (bull/neutral/bear)
            "atr_grade": atr_grade,           # ATR 등급 (low/mid/high)
        }

        with self.lock:
            self.positions[symbol] = new_pos
            self._save()

        logger.info(f"[OPEN POSITION] {symbol} qty={qty} entry={price} type={position_type}")
        return True

    # ============================================================
    # DCA 추가 (레벨업)
    # ============================================================
    def add_dca(self, symbol: str, qty: float, price: float) -> bool:
        """
        DCA 매수:
        - qty 증가
        - 새로운 평균단가 계산
        - dca_stage + 1
        """

        with self.lock:
            if symbol not in self.positions:
                logger.error(f"[DCA ERROR] 포지션 없음 → {symbol}")
                return False

            pos = self.positions[symbol]

            old_qty = pos["qty"]
            old_entry = pos["entry_price"]

            new_total_qty = old_qty + qty
            new_entry = (old_qty * old_entry + qty * price) / new_total_qty

            pos["qty"] = new_total_qty
            pos["entry_price"] = new_entry

            pos["dca_stage"] += 1
            pos["dca_history"].append(
                {
                    "qty": qty,
                    "price": price,
                    "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                }
            )

            self._save()

        logger.info(f"[DCA UPDATE] {symbol} stage={pos['dca_stage']} avg={new_entry}")
        return True

    # ============================================================
    # 포지션 수정 (부분청산 / TP 레벨 / 트레일링 등)
    # ============================================================
    def update_position(self, symbol: str, new_pos: dict) -> bool:
        """
        ExecutionEngine 에서 수정한 포지션(dict)을 그대로 반영.
        - qty / tp_levels / trailing 등 변경 후 호출
        """
        with self.lock:
            if symbol not in self.positions:
                logger.error(f"[UPDATE ERROR] 포지션 없음 → {symbol}")
                return False

            self.positions[symbol] = new_pos
            self._save()

        return True

    # ============================================================
    # 포지션 종료
    # ============================================================
    def close_position(self, symbol: str, exit_price: float) -> bool:
        """
        포지션 종료 후 삭제 + PnL 로그
        """

        with self.lock:
            if symbol not in self.positions:
                return False

            pos = self.positions[symbol]

            entry = pos["entry_price"]
            qty = pos["qty"]

            pnl = (exit_price - entry) * qty
            pnl_pct = (exit_price - entry) / entry * 100

            logger.info(
                f"[CLOSE POSITION] {symbol} exit={exit_price} "
                f"P/L={pnl:.0f} KRW ({pnl_pct:.2f}%)"
            )

            del self.positions[symbol]
            self._save()

        return True

    # ============================================================
    # 전체 삭제 (백업 / 재시작용)
    # ============================================================
    def reset(self):
        with self.lock:
            self.positions = {}
            self._save()
    
    # ============================================================
    # 🆕 v5.1.0: SL 홀드 관리
    # ============================================================
    def set_sl_hold(self, symbol: str, hours: int = None) -> datetime:
        """
        SL 홀드 설정 (4시간 동안 재알림 금지)
        
        Returns:
            홀드 만료 시각
        """
        if hours is None:
            hours = getattr(Config, 'SL_HOLD_HOURS', 4)
        
        hold_until = datetime.now() + timedelta(hours=hours)
        
        with self.lock:
            self.sl_hold_until[symbol] = hold_until
            self._save()
        
        logger.info(f"[SL HOLD] {symbol} 홀드 설정 → 만료: {hold_until.strftime('%H:%M')}")
        return hold_until
    
    def is_sl_held(self, symbol: str) -> bool:
        """
        SL 홀드 상태 확인
        
        Returns:
            True: 홀드 중 (재알림 금지)
            False: 홀드 만료 또는 미설정
        """
        with self.lock:
            hold_until = self.sl_hold_until.get(symbol)
            
            if not hold_until:
                return False
            
            if datetime.now() >= hold_until:
                # 홀드 만료 → 삭제
                del self.sl_hold_until[symbol]
                self._save()
                logger.info(f"[SL HOLD] {symbol} 홀드 만료")
                return False
            
            return True
    
    def clear_sl_hold(self, symbol: str):
        """SL 홀드 해제"""
        with self.lock:
            if symbol in self.sl_hold_until:
                del self.sl_hold_until[symbol]
                self._save()
                logger.info(f"[SL HOLD] {symbol} 홀드 해제됨")
    
    def get_sl_hold_remaining(self, symbol: str) -> Optional[int]:
        """
        SL 홀드 남은 시간 (분)
        
        Returns:
            남은 분 또는 None (미설정/만료)
        """
        with self.lock:
            hold_until = self.sl_hold_until.get(symbol)
            
            if not hold_until:
                return None
            
            remaining = (hold_until - datetime.now()).total_seconds() / 60
            
            if remaining <= 0:
                del self.sl_hold_until[symbol]
                return None
            
            return int(remaining)
    
    def get_all_sl_holds(self) -> dict:
        """모든 SL 홀드 상태 조회"""
        with self.lock:
            result = {}
            now = datetime.now()
            
            for symbol, hold_until in list(self.sl_hold_until.items()):
                if now >= hold_until:
                    del self.sl_hold_until[symbol]
                else:
                    remaining = int((hold_until - now).total_seconds() / 60)
                    result[symbol] = {
                        "hold_until": hold_until.strftime("%Y-%m-%d %H:%M:%S"),
                        "remaining_min": remaining,
                    }
            
            return result
    
    # ============================================================
    # 🆕 v5.1.0: 진입 단계 업데이트
    # ============================================================
    def update_entry_stage(self, symbol: str, new_stage: int) -> bool:
        """진입 단계 업데이트 (1 → 2 → 3)"""
        with self.lock:
            if symbol not in self.positions:
                return False
            
            self.positions[symbol]["entry_stage"] = new_stage
            self._save()
            
            logger.info(f"[ENTRY STAGE] {symbol} → 단계 {new_stage}")
            return True

    # ============================================================
    # 🆕 v5.1.0a: 빗썸 동기화 기능
    # ============================================================
    def sync_with_exchange(self, api, scalp_positions: dict = None) -> Dict:
        """
        빗썸 잔고와 봇 포지션 동기화
        
        Args:
            api: BithumbCcxtAPI 인스턴스
            scalp_positions: 단타 포지션 딕셔너리 (선택)
        
        Returns:
            동기화 리포트: {"added": [], "removed": [], "matched": [], "errors": []}
        """
        report = {
            "added": [],
            "removed": [],
            "matched": [],
            "errors": []
        }
        
        try:
            # 빗썸 잔고 조회
            balance = api.fetch_balance()
            
            # 봇의 모든 포지션 (메인 + 단타)
            all_bot_symbols = set(self.positions.keys())
            if scalp_positions:
                all_bot_symbols.update(scalp_positions.keys())
            
            # 빗썸에서 유효한 코인 조회
            exchange_coins = {}
            skip_keys = ["KRW", "free", "used", "total", "info", "timestamp", "datetime"]
            
            for coin, data in balance.items():
                if coin in skip_keys:
                    continue
                
                total_qty = 0
                if isinstance(data, dict):
                    total_qty = data.get("total", 0) or 0
                elif isinstance(data, (int, float)):
                    total_qty = data or 0
                
                if total_qty <= 0:
                    continue
                
                symbol = f"{coin}/KRW"
                
                try:
                    # 가치 확인 (최소 주문 금액 이상인지)
                    ticker = api.fetch_ticker(symbol)
                    price = ticker.get("last", 0)
                    value = total_qty * price
                    
                    min_amount = getattr(Config, 'MIN_ORDER_AMOUNT', 5000)
                    if value >= min_amount:
                        # 평균 매수가 조회
                        avg_price = self._get_avg_buy_price(api, coin, balance)
                        
                        exchange_coins[symbol] = {
                            "qty": total_qty,
                            "price": price,
                            "value": value,
                            "avg_price": avg_price or price
                        }
                except Exception as e:
                    logger.warning(f"[SYNC] {symbol} 조회 실패: {e}")
                    continue
            
            exchange_symbols = set(exchange_coins.keys())
            
            # 1. 빗썸에만 있는 코인 → 포지션 추가
            only_exchange = exchange_symbols - all_bot_symbols
            for symbol in only_exchange:
                try:
                    data = exchange_coins[symbol]
                    self._add_synced_position(
                        symbol=symbol,
                        qty=data["qty"],
                        avg_price=data["avg_price"]
                    )
                    report["added"].append({
                        "symbol": symbol,
                        "qty": data["qty"],
                        "avg_price": data["avg_price"],
                        "value": data["value"]
                    })
                    logger.info(f"[SYNC ADD] {symbol}: {data['qty']:.4f}개 @ {data['avg_price']:,.0f}원")
                except Exception as e:
                    report["errors"].append(f"{symbol}: {e}")
            
            # 2. 봇에만 있는 포지션 → 삭제
            only_bot = all_bot_symbols - exchange_symbols
            for symbol in only_bot:
                try:
                    # 메인 포지션에서 삭제
                    if symbol in self.positions:
                        with self.lock:
                            del self.positions[symbol]
                        report["removed"].append({"symbol": symbol, "type": "main"})
                        logger.info(f"[SYNC REMOVE] {symbol} (메인 포지션)")
                    
                    # 단타 포지션에서도 삭제 (있다면)
                    if scalp_positions and symbol in scalp_positions:
                        del scalp_positions[symbol]
                        report["removed"].append({"symbol": symbol, "type": "scalp"})
                        logger.info(f"[SYNC REMOVE] {symbol} (단타 포지션)")
                except Exception as e:
                    report["errors"].append(f"{symbol} 삭제 실패: {e}")
            
            # 3. 일치하는 포지션
            matched = exchange_symbols & all_bot_symbols
            for symbol in matched:
                report["matched"].append(symbol)
            
            # 저장
            with self.lock:
                self._save()
            
            logger.info(f"[SYNC COMPLETE] 추가: {len(report['added'])}, 삭제: {len(report['removed'])}, 일치: {len(report['matched'])}")
            
        except Exception as e:
            logger.error(f"[SYNC ERROR] {e}")
            report["errors"].append(str(e))
        
        return report
    
    def _get_avg_buy_price(self, api, coin: str, balance: dict) -> Optional[float]:
        """
        평균 매수가 조회
        
        방법 1: balance['info']['data'][coin]['average_buy_price']
        방법 2: private_post_info_balance() 직접 호출
        방법 3: 현재가 사용 (fallback)
        """
        try:
            # 방법 1: balance info에서 추출
            info = balance.get("info", {})
            data = info.get("data", {})
            coin_data = data.get(coin, {})
            
            avg_price = coin_data.get("average_buy_price")
            if avg_price:
                return float(avg_price)
            
            # 방법 2: 직접 API 호출
            try:
                if hasattr(api, 'exchange') and hasattr(api.exchange, 'private_post_info_balance'):
                    result = api.exchange.private_post_info_balance({"currency": coin})
                    if result and "data" in result:
                        avg_price = result["data"].get("average_buy_price")
                        if avg_price:
                            return float(avg_price)
            except:
                pass
            
            # 방법 3: 빗썸 private API
            try:
                if hasattr(api, 'exchange'):
                    result = api.exchange.fetch_balance({"currency": coin})
                    info = result.get("info", {}).get("data", {})
                    avg_price = info.get(coin, {}).get("average_buy_price")
                    if avg_price:
                        return float(avg_price)
            except:
                pass
            
        except Exception as e:
            logger.warning(f"[AVG PRICE] {coin} 조회 실패: {e}")
        
        return None
    
    def _add_synced_position(self, symbol: str, qty: float, avg_price: float):
        """
        동기화로 추가된 포지션 생성
        
        - 기본 TP/SL 설정
        - position_type: "synced"
        - synced: True 플래그
        """
        # 기본 TP/SL
        default_tp_pct = getattr(Config, 'DEFAULT_TP_PCT', 0.03)
        default_sl_pct = getattr(Config, 'DEFAULT_SL_PCT', 0.02)
        
        tp_price = avg_price * (1 + default_tp_pct)
        sl_price = avg_price * (1 - default_sl_pct)
        
        new_pos = {
            "symbol": symbol,
            "qty": qty,
            "entry_price": avg_price,
            "opened_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            
            # 전략 메타
            "pf_weight": 0.1,
            "tp": tp_price,
            "sl": sl_price,
            "strat_reason": "",
            "strength": 0,
            
            # AI 메타
            "ai_tp": default_tp_pct,
            "ai_sl": default_sl_pct,
            "ai_confidence": 0.5,
            "ai_reason": "동기화로 추가됨 - 수동 검토 필요",
            
            # DCA 메타
            "dca_stage": 0,
            "dca_history": [],
            
            # Dynamic TP / Trailing
            "initial_qty": qty,
            "tp_levels": [],
            "trailing": {
                "enabled": False,
                "trigger": None,
                "offset": None,
                "highest_price": avg_price,
            },
            
            # 전략 정보
            "position_type": "synced",
            "holding_period": "",
            "conf_mult": 1.0,
            "time_zone": "",
            "time_mult": 1.0,
            "tp_mult": 1.0,
            
            # 분할 진입
            "entry_stage": 1,
            "entry_ratio": 1.0,
            "dca_interval": -0.05,
            "trend": "neutral",
            "atr_grade": "mid",
            
            # 🆕 동기화 플래그
            "synced": True,
            "synced_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        }
        
        with self.lock:
            self.positions[symbol] = new_pos
            self._save()
        
        logger.info(f"[SYNCED POSITION] {symbol} qty={qty:.4f} avg={avg_price:,.0f}")
    
    def get_sync_status(self, api) -> Dict:
        """
        동기화 상태 미리보기 (실제 동기화 없이 상태만 확인)
        
        Returns:
            {
                "exchange_count": 빗썸 보유 코인 수,
                "bot_count": 봇 포지션 수,
                "only_exchange": ["빗썸에만 있는 코인"],
                "only_bot": ["봇에만 있는 포지션"],
                "matched": ["일치하는 포지션"],
                "needs_sync": True/False
            }
        """
        result = {
            "exchange_count": 0,
            "bot_count": len(self.positions),
            "only_exchange": [],
            "only_bot": [],
            "matched": [],
            "needs_sync": False
        }
        
        try:
            balance = api.fetch_balance()
            
            # 빗썸 보유 코인
            exchange_symbols = set()
            skip_keys = ["KRW", "free", "used", "total", "info", "timestamp", "datetime"]
            
            for coin, data in balance.items():
                if coin in skip_keys:
                    continue
                
                total_qty = 0
                if isinstance(data, dict):
                    total_qty = data.get("total", 0) or 0
                elif isinstance(data, (int, float)):
                    total_qty = data or 0
                
                if total_qty <= 0:
                    continue
                
                symbol = f"{coin}/KRW"
                
                try:
                    ticker = api.fetch_ticker(symbol)
                    price = ticker.get("last", 0)
                    value = total_qty * price
                    
                    min_amount = getattr(Config, 'MIN_ORDER_AMOUNT', 5000)
                    if value >= min_amount:
                        exchange_symbols.add(symbol)
                except:
                    continue
            
            bot_symbols = set(self.positions.keys())
            
            result["exchange_count"] = len(exchange_symbols)
            result["only_exchange"] = list(exchange_symbols - bot_symbols)
            result["only_bot"] = list(bot_symbols - exchange_symbols)
            result["matched"] = list(exchange_symbols & bot_symbols)
            result["needs_sync"] = bool(result["only_exchange"] or result["only_bot"])
            
        except Exception as e:
            logger.error(f"[SYNC STATUS ERROR] {e}")
        
        return result
