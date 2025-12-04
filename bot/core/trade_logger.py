# -*- coding: utf-8 -*-
"""
Phoenix v5.3.1c — Trade Logger (확신도 분석 기능 추가)

🆕 v5.3.1c 변경:
- get_confidence_stats(): 확신도별 상세 통계
- get_optimal_confidence_threshold(): 최적 확신도 임계값 추천

🆕 v5.2.1b 변경:
- get_daily_detailed_stats(): 일일 상세 통계 (00:00 ~ 24:00 KST)
- get_weekly_detailed_stats(): 주간 상세 통계 (월~일)
- _calculate_mdd(): MDD (Maximum Drawdown) 계산
- _calculate_max_losing_streak(): 최대 연속 손실 계산
- _format_holding_time(): 보유 시간 포맷팅

저장 항목:
- 진입/청산 기록
- AI 판단 내역 (ai_confidence 포함)
- 손익 기록
- 성과 분석용 메타데이터
"""

import os
import json
import threading
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any

from bot.utils.logger import get_logger

logger = get_logger("TradeLogger")


class TradeLogger:
    """거래 기록 관리 클래스"""
    
    def __init__(self, data_dir: str = "data"):
        self.data_dir = data_dir
        self.trades_file = os.path.join(data_dir, "trades.json")
        self.daily_file = os.path.join(data_dir, "daily_summary.json")
        self.ai_history_file = os.path.join(data_dir, "ai_history.json")
        
        self.lock = threading.Lock()
        
        # 디렉토리 생성
        os.makedirs(data_dir, exist_ok=True)
        
        # 데이터 로드
        self.trades = self._load_json(self.trades_file, [])
        self.daily_summary = self._load_json(self.daily_file, {})
        self.ai_history = self._load_json(self.ai_history_file, [])
        
        logger.info(f"[TradeLogger] 초기화 완료 - 기존 거래: {len(self.trades)}건")
    
    # ================================================================
    # 파일 I/O
    # ================================================================
    def _load_json(self, filepath: str, default: Any) -> Any:
        """JSON 파일 로드"""
        try:
            if os.path.exists(filepath):
                with open(filepath, "r", encoding="utf-8") as f:
                    return json.load(f)
        except Exception as e:
            logger.error(f"[LOAD ERROR] {filepath}: {e}")
        return default
    
    def _save_json(self, filepath: str, data: Any):
        """JSON 파일 저장"""
        try:
            with open(filepath, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.error(f"[SAVE ERROR] {filepath}: {e}")
    
    # ================================================================
    # 거래 기록
    # ================================================================
    def log_entry(
        self,
        symbol: str,
        entry_price: float,
        qty: float,
        krw_amount: float,
        position_weight: float,
        ai_decision: Dict,
        market_condition: str = "unknown",
        position_type: str = "scalp",
        strategy: str = "unknown",
    ) -> str:
        """
        진입 기록
        
        Returns:
            trade_id: 고유 거래 ID
        """
        with self.lock:
            trade_id = f"{symbol.replace('/', '')}_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
            
            trade = {
                "trade_id": trade_id,
                "symbol": symbol,
                "status": "open",
                
                # 진입 정보
                "entry_time": datetime.now().isoformat(),
                "entry_price": entry_price,
                "qty": qty,
                "krw_amount": krw_amount,
                "position_weight": position_weight,
                
                # AI 판단
                "ai_decision": ai_decision.get("decision", "unknown"),
                "ai_confidence": ai_decision.get("confidence", 0),
                "ai_tp": ai_decision.get("tp", 0),
                "ai_sl": ai_decision.get("sl", 0),
                "ai_reason": ai_decision.get("reason", ""),
                "ai_risk_note": ai_decision.get("risk_note", ""),
                
                # 시장 상황
                "market_condition": market_condition,
                "position_type": position_type,
                "holding_period": ai_decision.get("holding_period", "unknown"),
                
                # 전략
                "strategy": strategy,
                
                # 청산 정보 (나중에 업데이트)
                "exit_time": None,
                "exit_price": None,
                "exit_reason": None,
                "pnl_krw": None,
                "pnl_pct": None,
                "holding_hours": None,
            }
            
            self.trades.append(trade)
            self._save_json(self.trades_file, self.trades)
            
            logger.info(f"[ENTRY LOG] {trade_id} - {symbol} @ {entry_price:,.0f}")
            
            return trade_id
    
    def log_exit(
        self,
        symbol: str,
        exit_price: float,
        exit_reason: str,
        trade_id: Optional[str] = None,
    ) -> Optional[Dict]:
        """
        청산 기록
        
        Returns:
            업데이트된 거래 정보
        """
        with self.lock:
            # trade_id가 없으면 해당 symbol의 마지막 open 거래 찾기
            target_trade = None
            
            for trade in reversed(self.trades):
                if trade["symbol"] == symbol and trade["status"] == "open":
                    if trade_id is None or trade["trade_id"] == trade_id:
                        target_trade = trade
                        break
            
            if not target_trade:
                logger.warning(f"[EXIT LOG] {symbol} open 거래 없음")
                return None
            
            # 청산 정보 업데이트
            entry_price = target_trade["entry_price"]
            qty = target_trade["qty"]
            entry_time = datetime.fromisoformat(target_trade["entry_time"])
            exit_time = datetime.now()
            
            pnl_krw = (exit_price - entry_price) * qty
            pnl_pct = (exit_price - entry_price) / entry_price * 100
            holding_hours = (exit_time - entry_time).total_seconds() / 3600
            
            target_trade.update({
                "status": "closed",
                "exit_time": exit_time.isoformat(),
                "exit_price": exit_price,
                "exit_reason": exit_reason,
                "pnl_krw": round(pnl_krw, 0),
                "pnl_pct": round(pnl_pct, 2),
                "holding_hours": round(holding_hours, 2),
            })
            
            self._save_json(self.trades_file, self.trades)
            
            # 일일 요약 업데이트
            self._update_daily_summary(target_trade)
            
            logger.info(
                f"[EXIT LOG] {target_trade['trade_id']} - {symbol} "
                f"PnL: {pnl_pct:+.2f}% ({pnl_krw:+,.0f} KRW)"
            )
            
            return target_trade
    
    # ================================================================
    # AI 히스토리
    # ================================================================
    def log_ai_decision(
        self,
        symbol: str,
        ai_decision: Dict,
        market_data: Dict,
        executed: bool,
    ):
        """AI 판단 기록 (실행 여부 무관)"""
        with self.lock:
            record = {
                "timestamp": datetime.now().isoformat(),
                "symbol": symbol,
                "decision": ai_decision.get("decision"),
                "confidence": ai_decision.get("confidence"),
                "market_condition": ai_decision.get("market_condition"),
                "position_type": ai_decision.get("position_type"),
                "tp": ai_decision.get("tp"),
                "sl": ai_decision.get("sl"),
                "reason": ai_decision.get("reason"),
                "executed": executed,
                "market_data": market_data,
            }
            
            self.ai_history.append(record)
            
            # 최근 1000개만 유지
            if len(self.ai_history) > 1000:
                self.ai_history = self.ai_history[-1000:]
            
            self._save_json(self.ai_history_file, self.ai_history)
    
    # ================================================================
    # 일일 요약
    # ================================================================
    def _update_daily_summary(self, trade: Dict):
        """일일 요약 업데이트"""
        date_key = datetime.now().strftime("%Y-%m-%d")
        
        if date_key not in self.daily_summary:
            self.daily_summary[date_key] = {
                "date": date_key,
                "total_trades": 0,
                "wins": 0,
                "losses": 0,
                "total_pnl_krw": 0,
                "total_pnl_pct": 0,
                "best_trade": None,
                "worst_trade": None,
                "by_strategy": {},
                "by_coin": {},
                "by_market_condition": {},
            }
        
        summary = self.daily_summary[date_key]
        pnl_krw = trade.get("pnl_krw", 0)
        pnl_pct = trade.get("pnl_pct", 0)
        
        # 기본 통계
        summary["total_trades"] += 1
        summary["total_pnl_krw"] += pnl_krw
        summary["total_pnl_pct"] += pnl_pct
        
        if pnl_krw >= 0:
            summary["wins"] += 1
        else:
            summary["losses"] += 1
        
        # 최고/최저 거래
        if summary["best_trade"] is None or pnl_pct > summary["best_trade"]["pnl_pct"]:
            summary["best_trade"] = {
                "symbol": trade["symbol"],
                "pnl_pct": pnl_pct,
                "pnl_krw": pnl_krw,
            }
        
        if summary["worst_trade"] is None or pnl_pct < summary["worst_trade"]["pnl_pct"]:
            summary["worst_trade"] = {
                "symbol": trade["symbol"],
                "pnl_pct": pnl_pct,
                "pnl_krw": pnl_krw,
            }
        
        # 전략별 통계
        strategy = trade.get("strategy", "unknown")
        if strategy not in summary["by_strategy"]:
            summary["by_strategy"][strategy] = {"trades": 0, "wins": 0, "pnl_krw": 0}
        summary["by_strategy"][strategy]["trades"] += 1
        summary["by_strategy"][strategy]["pnl_krw"] += pnl_krw
        if pnl_krw >= 0:
            summary["by_strategy"][strategy]["wins"] += 1
        
        # 코인별 통계
        coin = trade.get("symbol", "unknown")
        if coin not in summary["by_coin"]:
            summary["by_coin"][coin] = {"trades": 0, "wins": 0, "pnl_krw": 0}
        summary["by_coin"][coin]["trades"] += 1
        summary["by_coin"][coin]["pnl_krw"] += pnl_krw
        if pnl_krw >= 0:
            summary["by_coin"][coin]["wins"] += 1
        
        # 시장 상황별 통계
        condition = trade.get("market_condition", "unknown")
        if condition not in summary["by_market_condition"]:
            summary["by_market_condition"][condition] = {"trades": 0, "wins": 0, "pnl_krw": 0}
        summary["by_market_condition"][condition]["trades"] += 1
        summary["by_market_condition"][condition]["pnl_krw"] += pnl_krw
        if pnl_krw >= 0:
            summary["by_market_condition"][condition]["wins"] += 1
        
        self._save_json(self.daily_file, self.daily_summary)
    
    # ================================================================
    # 조회 메서드
    # ================================================================
    def get_open_trades(self) -> List[Dict]:
        """현재 오픈된 거래 목록"""
        return [t for t in self.trades if t["status"] == "open"]
    
    def get_today_trades(self) -> List[Dict]:
        """오늘 거래 목록"""
        today = datetime.now().strftime("%Y-%m-%d")
        return [
            t for t in self.trades 
            if t["entry_time"].startswith(today)
        ]
    
    def get_today_summary(self) -> Dict:
        """오늘 요약"""
        today = datetime.now().strftime("%Y-%m-%d")
        return self.daily_summary.get(today, {
            "total_trades": 0,
            "wins": 0,
            "losses": 0,
            "total_pnl_krw": 0,
        })
    
    def get_period_summary(self, days: int = 7) -> Dict:
        """기간별 요약 (최근 N일)"""
        result = {
            "period_days": days,
            "total_trades": 0,
            "wins": 0,
            "losses": 0,
            "total_pnl_krw": 0,
            "win_rate": 0,
            "avg_pnl_per_trade": 0,
            "by_strategy": {},
            "by_coin": {},
        }
        
        cutoff = datetime.now() - timedelta(days=days)
        
        for trade in self.trades:
            if trade["status"] != "closed":
                continue
            
            exit_time = datetime.fromisoformat(trade["exit_time"])
            if exit_time < cutoff:
                continue
            
            result["total_trades"] += 1
            result["total_pnl_krw"] += trade.get("pnl_krw", 0)
            
            if trade.get("pnl_krw", 0) >= 0:
                result["wins"] += 1
            else:
                result["losses"] += 1
            
            # 전략별
            strategy = trade.get("strategy", "unknown")
            if strategy not in result["by_strategy"]:
                result["by_strategy"][strategy] = {"trades": 0, "wins": 0, "pnl_krw": 0}
            result["by_strategy"][strategy]["trades"] += 1
            result["by_strategy"][strategy]["pnl_krw"] += trade.get("pnl_krw", 0)
            if trade.get("pnl_krw", 0) >= 0:
                result["by_strategy"][strategy]["wins"] += 1
            
            # 코인별
            coin = trade.get("symbol", "unknown")
            if coin not in result["by_coin"]:
                result["by_coin"][coin] = {"trades": 0, "wins": 0, "pnl_krw": 0}
            result["by_coin"][coin]["trades"] += 1
            result["by_coin"][coin]["pnl_krw"] += trade.get("pnl_krw", 0)
            if trade.get("pnl_krw", 0) >= 0:
                result["by_coin"][coin]["wins"] += 1
        
        # 승률 계산
        if result["total_trades"] > 0:
            result["win_rate"] = result["wins"] / result["total_trades"] * 100
            result["avg_pnl_per_trade"] = result["total_pnl_krw"] / result["total_trades"]
        
        return result
    
    def get_ai_accuracy(self, days: int = 7) -> Dict:
        """AI 판단 정확도 분석"""
        cutoff = datetime.now() - timedelta(days=days)
        
        result = {
            "total_decisions": 0,
            "executed": 0,
            "profitable": 0,
            "accuracy": 0,
            "by_confidence": {
                "high": {"total": 0, "profitable": 0},    # 0.7+
                "medium": {"total": 0, "profitable": 0},  # 0.5~0.7
                "low": {"total": 0, "profitable": 0},     # 0~0.5
            },
            "by_market_condition": {},
        }
        
        # 실행된 거래들 분석
        for trade in self.trades:
            if trade["status"] != "closed":
                continue
            
            exit_time = datetime.fromisoformat(trade["exit_time"])
            if exit_time < cutoff:
                continue
            
            result["total_decisions"] += 1
            result["executed"] += 1
            
            if trade.get("pnl_krw", 0) >= 0:
                result["profitable"] += 1
            
            # 신뢰도별
            conf = trade.get("ai_confidence", 0.5)
            if conf >= 0.7:
                level = "high"
            elif conf >= 0.5:
                level = "medium"
            else:
                level = "low"
            
            result["by_confidence"][level]["total"] += 1
            if trade.get("pnl_krw", 0) >= 0:
                result["by_confidence"][level]["profitable"] += 1
            
            # 시장 상황별
            condition = trade.get("market_condition", "unknown")
            if condition not in result["by_market_condition"]:
                result["by_market_condition"][condition] = {"total": 0, "profitable": 0}
            result["by_market_condition"][condition]["total"] += 1
            if trade.get("pnl_krw", 0) >= 0:
                result["by_market_condition"][condition]["profitable"] += 1
        
        # 정확도 계산
        if result["executed"] > 0:
            result["accuracy"] = result["profitable"] / result["executed"] * 100
        
        return result

    # ================================================================
    # 🆕 v5.2.1b: 상세 통계 메서드
    # ================================================================
    def get_daily_detailed_stats(self, target_date: str = None) -> Dict:
        """
        🆕 v5.2.1b: 일일 상세 통계 (00:00 ~ 24:00 KST)
        
        Args:
            target_date: YYYY-MM-DD 형식 (None이면 오늘)
        
        Returns:
            상세 통계 딕셔너리
        """
        if target_date is None:
            target_date = datetime.now().strftime("%Y-%m-%d")
        
        # 해당 날짜의 청산된 거래 필터링
        closed_trades = []
        for trade in self.trades:
            if trade["status"] != "closed":
                continue
            exit_time = trade.get("exit_time", "")
            if exit_time and exit_time.startswith(target_date):
                closed_trades.append(trade)
        
        return self._calculate_detailed_stats(closed_trades, target_date, "daily")
    
    def get_weekly_detailed_stats(self, target_date: str = None) -> Dict:
        """
        🆕 v5.2.1b: 주간 상세 통계 (월요일 00:00 ~ 일요일 24:00 KST)
        
        Args:
            target_date: YYYY-MM-DD 형식 (None이면 이번 주)
        
        Returns:
            상세 통계 딕셔너리
        """
        if target_date is None:
            today = datetime.now()
        else:
            today = datetime.strptime(target_date, "%Y-%m-%d")
        
        # 월요일 찾기 (weekday: 0=월, 6=일)
        days_since_monday = today.weekday()
        monday = today - timedelta(days=days_since_monday)
        sunday = monday + timedelta(days=6)
        
        monday_str = monday.strftime("%Y-%m-%d")
        sunday_str = sunday.strftime("%Y-%m-%d")
        
        # 해당 주의 청산된 거래 필터링
        closed_trades = []
        for trade in self.trades:
            if trade["status"] != "closed":
                continue
            exit_time = trade.get("exit_time", "")
            if not exit_time:
                continue
            exit_date = exit_time[:10]  # YYYY-MM-DD
            if monday_str <= exit_date <= sunday_str:
                closed_trades.append(trade)
        
        period_str = f"{monday_str} ~ {sunday_str}"
        return self._calculate_detailed_stats(closed_trades, period_str, "weekly")
    
    def _calculate_detailed_stats(self, trades: List[Dict], period: str, period_type: str) -> Dict:
        """
        🆕 v5.2.1b: 상세 통계 계산 (공통 로직)
        
        Args:
            trades: 분석할 거래 목록
            period: 기간 문자열
            period_type: "daily" 또는 "weekly"
        
        Returns:
            상세 통계 딕셔너리
        """
        result = {
            "period": period,
            "period_type": period_type,
            
            # 기본 통계
            "total_trades": 0,
            "wins": 0,
            "losses": 0,
            "win_rate": 0.0,
            
            # 수익 통계
            "total_pnl_krw": 0,
            "avg_pnl_krw": 0,
            "avg_pnl_pct": 0.0,
            "best_trade_pnl": 0,
            "worst_trade_pnl": 0,
            
            # 리스크 지표
            "mdd_pct": 0.0,
            "max_losing_streak": 0,
            "avg_holding_hours": 0.0,
            
            # 코인별 성과
            "by_coin": {},
            
            # 전략별 성과
            "by_strategy": {},
            
            # 원본 거래 목록 (정렬용)
            "_trades": [],
        }
        
        if not trades:
            return result
        
        # 시간순 정렬
        sorted_trades = sorted(trades, key=lambda x: x.get("exit_time", ""))
        result["_trades"] = sorted_trades
        
        total_pnl_pct = 0.0
        total_holding_hours = 0.0
        pnl_sequence = []  # MDD 및 연속 손실 계산용
        
        for trade in sorted_trades:
            pnl_krw = trade.get("pnl_krw", 0) or 0
            pnl_pct = trade.get("pnl_pct", 0) or 0
            holding_hours = trade.get("holding_hours", 0) or 0
            strategy = trade.get("strategy", "unknown")
            coin = trade.get("symbol", "unknown")
            
            result["total_trades"] += 1
            result["total_pnl_krw"] += pnl_krw
            total_pnl_pct += pnl_pct
            total_holding_hours += holding_hours
            pnl_sequence.append(pnl_krw)
            
            if pnl_krw >= 0:
                result["wins"] += 1
            else:
                result["losses"] += 1
            
            # 최고/최저
            if pnl_krw > result["best_trade_pnl"]:
                result["best_trade_pnl"] = pnl_krw
            if pnl_krw < result["worst_trade_pnl"]:
                result["worst_trade_pnl"] = pnl_krw
            
            # 코인별 집계
            if coin not in result["by_coin"]:
                result["by_coin"][coin] = {"trades": 0, "wins": 0, "pnl_krw": 0, "pnl_pct": 0}
            result["by_coin"][coin]["trades"] += 1
            result["by_coin"][coin]["pnl_krw"] += pnl_krw
            result["by_coin"][coin]["pnl_pct"] += pnl_pct
            if pnl_krw >= 0:
                result["by_coin"][coin]["wins"] += 1
            
            # 전략별 집계
            if strategy not in result["by_strategy"]:
                result["by_strategy"][strategy] = {"trades": 0, "wins": 0, "pnl_krw": 0, "pnl_pct": 0}
            result["by_strategy"][strategy]["trades"] += 1
            result["by_strategy"][strategy]["pnl_krw"] += pnl_krw
            result["by_strategy"][strategy]["pnl_pct"] += pnl_pct
            if pnl_krw >= 0:
                result["by_strategy"][strategy]["wins"] += 1
        
        # 평균 계산
        total = result["total_trades"]
        if total > 0:
            result["win_rate"] = round(result["wins"] / total * 100, 1)
            result["avg_pnl_krw"] = round(result["total_pnl_krw"] / total, 0)
            result["avg_pnl_pct"] = round(total_pnl_pct / total, 2)
            result["avg_holding_hours"] = round(total_holding_hours / total, 2)
        
        # MDD 계산
        result["mdd_pct"] = self._calculate_mdd(pnl_sequence)
        
        # 최대 연속 손실 계산
        result["max_losing_streak"] = self._calculate_max_losing_streak(pnl_sequence)
        
        # 코인별/전략별 승률 계산
        for coin_data in result["by_coin"].values():
            if coin_data["trades"] > 0:
                coin_data["win_rate"] = round(coin_data["wins"] / coin_data["trades"] * 100, 1)
        
        for strat_data in result["by_strategy"].values():
            if strat_data["trades"] > 0:
                strat_data["win_rate"] = round(strat_data["wins"] / strat_data["trades"] * 100, 1)
        
        # 정리 (내부용 필드 제거)
        del result["_trades"]
        
        return result
    
    def _calculate_mdd(self, pnl_sequence: List[float]) -> float:
        """
        🆕 v5.2.1b: MDD (Maximum Drawdown) 계산
        
        Args:
            pnl_sequence: 손익 시퀀스 (KRW)
        
        Returns:
            MDD 퍼센트 (음수)
        """
        if not pnl_sequence:
            return 0.0
        
        cumulative = 0.0
        peak = 0.0
        max_drawdown = 0.0
        
        for pnl in pnl_sequence:
            cumulative += pnl
            if cumulative > peak:
                peak = cumulative
            drawdown = cumulative - peak
            if drawdown < max_drawdown:
                max_drawdown = drawdown
        
        # 퍼센트로 변환 (peak 기준)
        if peak > 0:
            mdd_pct = (max_drawdown / peak) * 100
        else:
            mdd_pct = 0.0
        
        return round(mdd_pct, 2)
    
    def _calculate_max_losing_streak(self, pnl_sequence: List[float]) -> int:
        """
        🆕 v5.2.1b: 최대 연속 손실 횟수 계산
        
        Args:
            pnl_sequence: 손익 시퀀스 (KRW)
        
        Returns:
            최대 연속 손실 횟수
        """
        if not pnl_sequence:
            return 0
        
        max_streak = 0
        current_streak = 0
        
        for pnl in pnl_sequence:
            if pnl < 0:
                current_streak += 1
                max_streak = max(max_streak, current_streak)
            else:
                current_streak = 0
        
        return max_streak
    
    def _format_holding_time(self, hours: float) -> str:
        """
        🆕 v5.2.1b: 보유 시간 포맷팅
        
        Args:
            hours: 시간 (소수점)
        
        Returns:
            포맷된 문자열 (예: "2시간 34분")
        """
        if hours <= 0:
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
    
    # ================================================================
    # 🆕 v5.3.1c: 확신도 분석 메서드
    # ================================================================
    def get_confidence_stats(self, days: int = 30) -> Dict:
        """
        🆕 v5.3.1c: 확신도별 상세 통계
        
        확신도 구간별 승률, 평균손익, 거래 수를 분석하여
        최적의 확신도 임계값을 결정하는 데 도움을 줍니다.
        
        Args:
            days: 분석 기간 (기본 30일)
        
        Returns:
            확신도별 통계 딕셔너리
        """
        cutoff = datetime.now() - timedelta(days=days)
        
        # 확신도 구간 정의 (5% 단위)
        buckets = {
            "50% 미만": {"min": 0.0, "max": 0.50, "trades": [], "wins": 0, "losses": 0, "total_pnl_krw": 0, "total_pnl_pct": 0},
            "50~55%": {"min": 0.50, "max": 0.55, "trades": [], "wins": 0, "losses": 0, "total_pnl_krw": 0, "total_pnl_pct": 0},
            "55~60%": {"min": 0.55, "max": 0.60, "trades": [], "wins": 0, "losses": 0, "total_pnl_krw": 0, "total_pnl_pct": 0},
            "60~65%": {"min": 0.60, "max": 0.65, "trades": [], "wins": 0, "losses": 0, "total_pnl_krw": 0, "total_pnl_pct": 0},
            "65~70%": {"min": 0.65, "max": 0.70, "trades": [], "wins": 0, "losses": 0, "total_pnl_krw": 0, "total_pnl_pct": 0},
            "70~75%": {"min": 0.70, "max": 0.75, "trades": [], "wins": 0, "losses": 0, "total_pnl_krw": 0, "total_pnl_pct": 0},
            "75~80%": {"min": 0.75, "max": 0.80, "trades": [], "wins": 0, "losses": 0, "total_pnl_krw": 0, "total_pnl_pct": 0},
            "80~85%": {"min": 0.80, "max": 0.85, "trades": [], "wins": 0, "losses": 0, "total_pnl_krw": 0, "total_pnl_pct": 0},
            "85~90%": {"min": 0.85, "max": 0.90, "trades": [], "wins": 0, "losses": 0, "total_pnl_krw": 0, "total_pnl_pct": 0},
            "90% 이상": {"min": 0.90, "max": 1.01, "trades": [], "wins": 0, "losses": 0, "total_pnl_krw": 0, "total_pnl_pct": 0},
        }
        
        # 청산된 거래만 필터링
        analyzed_trades = 0
        for trade in self.trades:
            if trade["status"] != "closed":
                continue
            
            exit_time_str = trade.get("exit_time")
            if not exit_time_str:
                continue
            
            try:
                exit_time = datetime.fromisoformat(exit_time_str)
                if exit_time < cutoff:
                    continue
            except:
                continue
            
            # ai_confidence 필드 확인
            conf = trade.get("ai_confidence")
            if conf is None:
                continue
            
            pnl_krw = trade.get("pnl_krw", 0) or 0
            pnl_pct = trade.get("pnl_pct", 0) or 0
            
            # 해당 구간에 추가
            for bucket_name, bucket_data in buckets.items():
                if bucket_data["min"] <= conf < bucket_data["max"]:
                    bucket_data["trades"].append(trade)
                    bucket_data["total_pnl_krw"] += pnl_krw
                    bucket_data["total_pnl_pct"] += pnl_pct
                    
                    if pnl_krw >= 0:
                        bucket_data["wins"] += 1
                    else:
                        bucket_data["losses"] += 1
                    
                    analyzed_trades += 1
                    break
        
        # 결과 계산
        result = {
            "period_days": days,
            "total_analyzed": analyzed_trades,
            "buckets": {},
            "recommendation": None,
        }
        
        for bucket_name, bucket_data in buckets.items():
            total = bucket_data["wins"] + bucket_data["losses"]
            
            if total == 0:
                continue
            
            win_rate = (bucket_data["wins"] / total) * 100
            avg_pnl_krw = bucket_data["total_pnl_krw"] / total
            avg_pnl_pct = bucket_data["total_pnl_pct"] / total
            
            result["buckets"][bucket_name] = {
                "trades": total,
                "wins": bucket_data["wins"],
                "losses": bucket_data["losses"],
                "win_rate": round(win_rate, 1),
                "total_pnl_krw": round(bucket_data["total_pnl_krw"], 0),
                "avg_pnl_krw": round(avg_pnl_krw, 0),
                "avg_pnl_pct": round(avg_pnl_pct, 2),
            }
        
        # 최적 임계값 추천
        result["recommendation"] = self._get_optimal_threshold_recommendation(result["buckets"])
        
        return result
    
    def _get_optimal_threshold_recommendation(self, buckets: Dict) -> Dict:
        """
        🆕 v5.3.1c: 최적 확신도 임계값 추천
        
        각 임계값 이상의 거래만 했을 때 예상 성과를 계산합니다.
        
        Args:
            buckets: 확신도별 통계
        
        Returns:
            추천 정보 딕셔너리
        """
        thresholds = [0.50, 0.55, 0.60, 0.65, 0.70, 0.75, 0.80]
        threshold_map = {
            0.50: ["50~55%", "55~60%", "60~65%", "65~70%", "70~75%", "75~80%", "80~85%", "85~90%", "90% 이상"],
            0.55: ["55~60%", "60~65%", "65~70%", "70~75%", "75~80%", "80~85%", "85~90%", "90% 이상"],
            0.60: ["60~65%", "65~70%", "70~75%", "75~80%", "80~85%", "85~90%", "90% 이상"],
            0.65: ["65~70%", "70~75%", "75~80%", "80~85%", "85~90%", "90% 이상"],
            0.70: ["70~75%", "75~80%", "80~85%", "85~90%", "90% 이상"],
            0.75: ["75~80%", "80~85%", "85~90%", "90% 이상"],
            0.80: ["80~85%", "85~90%", "90% 이상"],
        }
        
        results = []
        
        for threshold in thresholds:
            included_buckets = threshold_map.get(threshold, [])
            total_trades = 0
            total_wins = 0
            total_pnl_krw = 0
            total_pnl_pct = 0
            
            for bucket_name in included_buckets:
                if bucket_name in buckets:
                    b = buckets[bucket_name]
                    total_trades += b["trades"]
                    total_wins += b["wins"]
                    total_pnl_krw += b["total_pnl_krw"]
                    total_pnl_pct += b.get("avg_pnl_pct", 0) * b["trades"]
            
            if total_trades > 0:
                win_rate = (total_wins / total_trades) * 100
                avg_pnl_pct = total_pnl_pct / total_trades
                
                results.append({
                    "threshold": threshold,
                    "trades": total_trades,
                    "win_rate": round(win_rate, 1),
                    "avg_pnl_pct": round(avg_pnl_pct, 2),
                    "total_pnl_krw": round(total_pnl_krw, 0),
                })
        
        if not results:
            return {"message": "데이터 부족", "optimal_threshold": 0.65}
        
        # 최적 임계값: 승률 60% 이상 + 평균손익 양수 + 거래수 5건 이상
        optimal = None
        for r in results:
            if r["trades"] >= 5 and r["win_rate"] >= 60 and r["avg_pnl_pct"] > 0:
                if optimal is None or r["avg_pnl_pct"] > optimal["avg_pnl_pct"]:
                    optimal = r
        
        if optimal:
            return {
                "optimal_threshold": optimal["threshold"],
                "expected_win_rate": optimal["win_rate"],
                "expected_avg_pnl": optimal["avg_pnl_pct"],
                "expected_trades": optimal["trades"],
                "message": f"확신도 {optimal['threshold']:.0%} 이상 권장 (승률 {optimal['win_rate']:.1f}%, 평균손익 {optimal['avg_pnl_pct']:+.2f}%)",
                "all_thresholds": results,
            }
        else:
            # 데이터가 부족하면 기본값 65% 권장
            return {
                "optimal_threshold": 0.65,
                "message": "데이터 부족 - 기본값 65% 권장",
                "all_thresholds": results,
            }
    
    def print_confidence_report(self, days: int = 30):
        """
        🆕 v5.3.1c: 확신도 분석 리포트 출력 (콘솔용)
        
        Args:
            days: 분석 기간
        """
        stats = self.get_confidence_stats(days)
        
        print(f"\n{'='*70}")
        print(f"📊 확신도별 거래 성과 분석 (최근 {days}일)")
        print(f"{'='*70}")
        print(f"분석 거래: {stats['total_analyzed']}건")
        print(f"{'='*70}")
        print(f"{'확신도':<12} {'거래수':>8} {'승률':>10} {'평균손익':>12} {'총손익':>14}")
        print(f"{'='*70}")
        
        for bucket_name in ["50% 미만", "50~55%", "55~60%", "60~65%", "65~70%", "70~75%", "75~80%", "80~85%", "85~90%", "90% 이상"]:
            if bucket_name in stats["buckets"]:
                b = stats["buckets"][bucket_name]
                print(f"{bucket_name:<12} {b['trades']:>8}건 {b['win_rate']:>9.1f}% {b['avg_pnl_pct']:>+11.2f}% {b['total_pnl_krw']:>+13,.0f}")
        
        print(f"{'='*70}")
        
        rec = stats.get("recommendation", {})
        if rec:
            print(f"\n💡 권장: {rec.get('message', 'N/A')}")
            
            if "all_thresholds" in rec:
                print(f"\n📈 임계값별 예상 성과:")
                for t in rec["all_thresholds"]:
                    marker = "👉" if t["threshold"] == rec.get("optimal_threshold") else "  "
                    print(f"  {marker} {t['threshold']:.0%} 이상: {t['trades']}건, 승률 {t['win_rate']:.1f}%, 평균 {t['avg_pnl_pct']:+.2f}%")
        
        print()
