# -*- coding: utf-8 -*-
"""
Phoenix v4.4 — Chart Engine (WebSocket + CCXT Hybrid)
- WebSocket OHLCV 우선 사용, 없으면 CCXT fetch_ohlcv fallback
- 매수/평단/전략 TP/SL + AI TP/SL(비율 → 가격 변환) 표시
- Trailing Stop (highest_price, trigger) 시각화
- 텔레그램 전송용 PNG 생성
"""

import os
from datetime import datetime

import matplotlib.pyplot as plt
import pandas as pd

from bot.utils.logger import get_logger

logger = get_logger("ChartEngine")

try:
    plt.rcParams["font.family"] = "DejaVu Sans"
except Exception as e:
    logger.warning(f"폰트 설정 실패: {e}")


class ChartEngine:
    def __init__(self, api, position_manager, price_feed=None):
        self.api = api
        self.pm = position_manager
        self.pf = price_feed
        self.save_path = "data/charts"
        os.makedirs(self.save_path, exist_ok=True)

    def load_ohlcv(self, symbol: str, tf: str = "30m", limit: int = 200):
        if self.pf and hasattr(self.pf, "get_ohlcv"):
            try:
                df = self.pf.get_ohlcv(symbol, tf)
                if df is not None and not df.empty:
                    df = df.copy()
                    if "ts" not in df.columns:
                        if "timestamp" in df.columns:
                            df = df.rename(columns={"timestamp": "ts"})
                        elif "time" in df.columns:
                            df = df.rename(columns={"time": "ts"})
                    if "ts" in df.columns:
                        if not pd.api.types.is_datetime64_any_dtype(df["ts"]):
                            df["ts"] = pd.to_datetime(df["ts"])
                        return df.tail(limit)
            except Exception as e:
                logger.error(f"[CHART OHLCV WS ERROR] {symbol}: {e}")

        try:
            df = self.api.fetch_ohlcv(symbol, timeframe=tf, limit=limit)
            if df is None or df.empty:
                return None
            df = df.reset_index()
            df = df.rename(columns={"timestamp": "ts"})
            if False:
                df = df.rename(columns={"timestamp": "ts"})
            return df
        except Exception as e:
            logger.error(f"[CHART OHLCV CCXT ERROR] {symbol}: {e}")
            return None

    def generate_chart(self, symbol: str, tf: str = "30m"):
        df = self.load_ohlcv(symbol, tf=tf, limit=200)
        if df is None or df.empty:
            logger.error(f"[CHART] OHLCV 없음: {symbol}")
            return None

        pos = self.pm.get_position(symbol) if self.pm else None
        has_pos = pos is not None

        fig, ax = plt.subplots(figsize=(12, 6))
        ax.plot(df["ts"], df["close"], label="Close Price", color="#00baff", linewidth=1.5)

        if has_pos:
            entry = pos["entry_price"]
            strat_tp = pos.get("tp")
            strat_sl = pos.get("sl")
            ai_tp_ratio = pos.get("ai_tp")
            ai_sl_ratio = pos.get("ai_sl")

            ai_tp_price = entry * (1 + ai_tp_ratio) if ai_tp_ratio else None
            ai_sl_price = entry * (1 - ai_sl_ratio) if ai_sl_ratio else None

            ax.axhline(entry, color="#00ff00", linestyle="--", linewidth=1.5, label=f"Entry {entry:,.0f}")

            if strat_tp:
                ax.axhline(strat_tp, color="#ffaa00", linestyle="--", linewidth=1.2, label=f"TP {strat_tp:,.0f}")
            if strat_sl:
                ax.axhline(strat_sl, color="#ff3300", linestyle="--", linewidth=1.2, label=f"SL {strat_sl:,.0f}")
            if ai_tp_price:
                ax.axhline(ai_tp_price, color="#33ddff", linestyle="-.", linewidth=1.3, label=f"AI TP {ai_tp_price:,.0f}")
            if ai_sl_price:
                ax.axhline(ai_sl_price, color="#ff66aa", linestyle="-.", linewidth=1.3, label=f"AI SL {ai_sl_price:,.0f}")

            trailing = pos.get("trailing", {}) or {}
            if trailing.get("enabled"):
                highest = trailing.get("highest_price", entry)
                offset = trailing.get("offset", 0.0)
                trigger_price = highest * (1 - offset)
                ax.axhline(highest, color="#8888ff", linestyle=":", linewidth=1.0, label=f"Trailing High {highest:,.0f}")
                ax.axhline(trigger_price, color="#ff88ff", linestyle=":", linewidth=1.0, label=f"Trailing Trigger {trigger_price:,.0f}")

        ax.set_title(f"{symbol} — {tf} Chart (Phoenix v5.0)", fontsize=14)
        ax.set_xlabel("Time")
        ax.set_ylabel("Price (KRW)")
        ax.legend(loc="upper left")
        ax.grid(True, linestyle="--", alpha=0.4)
        plt.tight_layout()

        fname = f"{symbol.replace('/', '_')}_{tf}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.png"
        fpath = os.path.join(self.save_path, fname)
        plt.savefig(fpath)
        plt.close(fig)
        logger.info(f"[CHART SAVED] {fpath}")
        return fpath

    def create_chart_for_telegram(self, symbol: str):
        img_path = self.generate_chart(symbol, tf="30m")
        if img_path is None:
            return f"📈 {symbol} 차트 생성 실패", None

        pos = self.pm.get_position(symbol) if self.pm else None
        if pos is None:
            return f"📈 {symbol} 30m 차트\n포지션 없음", img_path

        entry = pos["entry_price"]
        msg_lines = [f"📈 {symbol} 30m 차트", "", f"진입가: {entry:,.0f}₩", f"수량: {pos['qty']}"]
        if pos.get("tp"):
            msg_lines.append(f"TP: {pos['tp']:,.0f}₩")
        if pos.get("sl"):
            msg_lines.append(f"SL: {pos['sl']:,.0f}₩")
        if pos.get("ai_reason"):
            msg_lines.append(f"\n📘 AI: {pos['ai_reason']}")
        return "\n".join(msg_lines), img_path
