# -*- coding: utf-8 -*-
"""
Phoenix v5.3.0 — PriceFeed (Phase 1 캐시 모듈 적용)

🔥 v5.3.0 변경:
- bot.utils.cache 모듈 사용 (price_cache, ohlcv_cache)
- PriceStore 내부 캐시 → 통합 캐시 활용
- 캐시 통계 기능 추가

🔧 v5.2.2 기능 유지:
- 주봉(1w) 타임프레임 지원
- 1h/4h/일봉/주봉 OHLCV 지원
- Adaptive Interval (시장 활성도 기반)
"""

import time
import threading
import pandas as pd
from typing import Dict, Optional, List
from datetime import datetime

from bot.utils.logger import get_logger

# 🆕 v5.3.0: 새 캐시 모듈 임포트
from bot.utils.cache import price_cache, ohlcv_cache

logger = get_logger("PriceFeed")


# =========================================================
# 가격 저장소 (v5.3.0 캐시 모듈 활용)
# =========================================================
class PriceStore:
    """가격 및 OHLCV 저장소 (v5.3.0 캐시 모듈 활용)"""
    
    PRICE_MAX_AGE = 60
    PRICE_CACHE_TTL = 30      # 가격 캐시 TTL (30초)
    OHLCV_CACHE_TTL = 60      # OHLCV 캐시 TTL (60초)
    OHLCV_LONG_CACHE_TTL = 300  # 장기 OHLCV 캐시 TTL (5분)
    
    def __init__(self):
        # 🆕 v5.3.0: 로컬 캐시 최소화, 타임스탬프만 유지
        self.price_timestamps: Dict[str, float] = {}
        self.balance: Dict = {}
        self.lock = threading.Lock()
        self.last_update = 0
    
    def set_price(self, symbol: str, price: float):
        """🔥 v5.3.0: 새 캐시 모듈 사용"""
        with self.lock:
            # 캐시에 저장
            price_cache.set(f"price:{symbol}", price, ttl=self.PRICE_CACHE_TTL)
            self.price_timestamps[symbol] = time.time()
            self.last_update = time.time()
    
    def get_price(self, symbol: str) -> Optional[float]:
        """🔥 v5.3.0: 새 캐시 모듈 사용"""
        return price_cache.get(f"price:{symbol}")
    
    def get_price_age(self, symbol: str) -> float:
        with self.lock:
            ts = self.price_timestamps.get(symbol, 0)
            return time.time() - ts if ts > 0 else float('inf')
    
    def get_all_prices(self) -> Dict[str, float]:
        """모든 가격 조회 (캐시에서)"""
        result = {}
        with self.lock:
            for symbol in self.price_timestamps.keys():
                price = price_cache.get(f"price:{symbol}")
                if price is not None:
                    result[symbol] = price
        return result
    
    @property
    def prices(self) -> Dict[str, float]:
        """호환성: prices 속성"""
        return self.get_all_prices()
    
    def get_last_update_age(self) -> float:
        with self.lock:
            return time.time() - self.last_update if self.last_update > 0 else float('inf')
    
    def set_ohlcv(self, symbol: str, timeframe: str, df: pd.DataFrame):
        """🔥 v5.3.0: 새 캐시 모듈 사용"""
        if df is None:
            return
        
        cache_key = f"ohlcv:{symbol}:{timeframe}"
        
        # 장기 타임프레임은 더 긴 TTL
        if timeframe in ["1h", "4h", "1d", "1w"]:
            ttl = self.OHLCV_LONG_CACHE_TTL
        else:
            ttl = self.OHLCV_CACHE_TTL
        
        ohlcv_cache.set(cache_key, df, ttl=ttl)
    
    def get_ohlcv(self, symbol: str, timeframe: str) -> Optional[pd.DataFrame]:
        """🔥 v5.3.0: 새 캐시 모듈 사용"""
        cache_key = f"ohlcv:{symbol}:{timeframe}"
        df = ohlcv_cache.get(cache_key)
        
        if df is not None:
            return df.copy()
        return None
    
    def set_balance(self, balance: Dict):
        with self.lock:
            self.balance = balance
    
    def get_balance(self) -> Dict:
        with self.lock:
            return dict(self.balance)
    
    def get_free_krw(self) -> float:
        with self.lock:
            return self.balance.get("KRW", {}).get("free", 0)
    
    def get_cache_stats(self) -> Dict:
        """🆕 v5.3.0: 캐시 통계"""
        return {
            "price_cache": price_cache.stats(),
            "ohlcv_cache": ohlcv_cache.stats(),
        }


# =========================================================
# REST 전용 PriceFeed (v5.3.0 캐시 모듈 적용)
# =========================================================
class BithumbPriceFeed:
    """빗썸 REST 전용 PriceFeed (v5.3.0 캐시 모듈 적용)"""
    
    # Adaptive Interval 설정
    PRICE_UPDATE_ACTIVE = 10
    PRICE_UPDATE_QUIET = 30
    ACTIVE_HOURS = (9, 24)
    
    OHLCV_UPDATE_INTERVAL = 60
    OHLCV_LONG_UPDATE_INTERVAL = 300  # 1h/4h/일봉/주봉 갱신 (5분)
    STATUS_LOG_INTERVAL = 300
    
    # 타임프레임 설정
    SHORT_TIMEFRAMES = ["30m", "15m", "5m"]
    LONG_TIMEFRAMES = ["1h", "4h", "1d", "1w"]
    
    def __init__(self, symbols: List[str], store: PriceStore, api=None, 
                 on_status_change=None):
        self.symbols = symbols
        self.store = store
        self.api = api
        self.on_status_change = on_status_change
        
        self.running = False
        self.last_price_update = 0
        self.last_ohlcv_update = 0
        self.last_long_ohlcv_update = 0
        self.last_status_log = 0
        
        # 통계
        self.total_updates = 0
        self.failed_updates = 0
        self.start_time = 0
        self.saved_calls = 0
        
        # 스레드
        self._price_thread: Optional[threading.Thread] = None
        self._ohlcv_thread: Optional[threading.Thread] = None
    
    # ---------------------------------------------------------
    # Adaptive Interval 계산
    # ---------------------------------------------------------
    def _get_price_interval(self) -> int:
        """현재 시간대에 맞는 갱신 간격 반환"""
        try:
            import pytz
            kst = pytz.timezone('Asia/Seoul')
            hour = datetime.now(kst).hour
        except:
            hour = datetime.now().hour
        
        if self.ACTIVE_HOURS[0] <= hour < self.ACTIVE_HOURS[1]:
            return self.PRICE_UPDATE_ACTIVE
        else:
            self.saved_calls += 1
            return self.PRICE_UPDATE_QUIET
    
    # ---------------------------------------------------------
    # 시작/중지
    # ---------------------------------------------------------
    def start(self):
        if self.running:
            logger.warning("[PriceFeed] 이미 실행 중")
            return
        
        self.running = True
        self.start_time = time.time()
        
        self._price_thread = threading.Thread(target=self._run_price_updater, daemon=True)
        self._price_thread.start()
        
        self._ohlcv_thread = threading.Thread(target=self._run_ohlcv_updater, daemon=True)
        self._ohlcv_thread.start()
        
        logger.info(f"[PriceFeed v5.3.0] REST 전용 모드 시작 - {len(self.symbols)}개 심볼 (Phase 1 캐시 적용)")
    
    def stop(self):
        logger.info("[PriceFeed] 중지 요청...")
        self.running = False
        logger.info("[PriceFeed] 중지됨")
    
    # ---------------------------------------------------------
    # 가격 갱신 루프
    # ---------------------------------------------------------
    def _run_price_updater(self):
        time.sleep(1)
        self._update_all_prices()
        
        while self.running:
            try:
                now = time.time()
                interval = self._get_price_interval()
                
                if now - self.last_price_update >= interval:
                    self._update_all_prices()
                    self.last_price_update = now
                
                if now - self.last_status_log >= self.STATUS_LOG_INTERVAL:
                    self._log_status()
                    self.last_status_log = now
                    
            except Exception as e:
                logger.error(f"[가격 갱신 오류] {e}")
            
            time.sleep(2)
    
    def _update_all_prices(self):
        if not self.api:
            return
        
        success = 0
        failed = 0
        
        for symbol in self.symbols:
            try:
                ticker = self.api.fetch_ticker(symbol)
                if ticker and ticker.get("last"):
                    price = float(ticker["last"])
                    self.store.set_price(symbol, price)
                    success += 1
            except Exception as e:
                failed += 1
                logger.debug(f"[REST] {symbol} 오류: {e}")
            
            time.sleep(0.15)
        
        self.total_updates += success
        self.failed_updates += failed
        
        logger.debug(f"[REST] 가격 갱신: {success}/{len(self.symbols)} 성공")
    
    # ---------------------------------------------------------
    # OHLCV 갱신 루프
    # ---------------------------------------------------------
    def _run_ohlcv_updater(self):
        time.sleep(3)
        self._update_all_ohlcv()
        self._update_long_ohlcv()
        
        while self.running:
            try:
                now = time.time()
                
                # 단기 OHLCV (30m/15m/5m) - 60초마다
                if now - self.last_ohlcv_update >= self.OHLCV_UPDATE_INTERVAL:
                    self._update_all_ohlcv()
                    self.last_ohlcv_update = now
                
                # 장기 OHLCV (1h/4h/1d/1w) - 5분마다
                if now - self.last_long_ohlcv_update >= self.OHLCV_LONG_UPDATE_INTERVAL:
                    self._update_long_ohlcv()
                    self.last_long_ohlcv_update = now
                
            except Exception as e:
                logger.error(f"[OHLCV 갱신 오류] {e}")
            
            time.sleep(5)
    
    def _update_all_ohlcv(self):
        """단기 OHLCV 갱신 (30m/15m/5m)"""
        if not self.api:
            return
        
        success = 0
        
        for symbol in self.symbols:
            for tf in self.SHORT_TIMEFRAMES:
                try:
                    df = self.api.fetch_ohlcv(symbol, tf)
                    if df is not None and not df.empty:
                        self.store.set_ohlcv(symbol, tf, df)
                        success += 1
                except Exception as e:
                    logger.debug(f"[OHLCV] {symbol} {tf} 오류: {e}")
                
                time.sleep(0.15)
        
        logger.debug(f"[OHLCV] 단기(30m/15m/5m) 갱신: {success}개")
    
    def _update_long_ohlcv(self):
        """장기 OHLCV 갱신 (1h/4h/1d/1w)"""
        if not self.api:
            return
        
        success = 0
        
        for symbol in self.symbols:
            for tf in ["1h", "4h"]:
                try:
                    df = self.api.fetch_ohlcv(symbol, tf)
                    if df is not None and not df.empty:
                        self.store.set_ohlcv(symbol, tf, df)
                        success += 1
                except:
                    pass
                time.sleep(0.15)
            
            # 일봉 변환 (4h → 1d)
            try:
                df4h = self.store.get_ohlcv(symbol, "4h")
                if df4h is not None and len(df4h) >= 6:
                    daily = self._convert_4h_to_daily(df4h)
                    if daily is not None:
                        self.store.set_ohlcv(symbol, "1d", daily)
                        success += 1
            except:
                pass
            
            # 주봉 변환 (1d → 1w)
            try:
                daily = self.store.get_ohlcv(symbol, "1d")
                if daily is not None and len(daily) >= 7:
                    weekly = self._convert_daily_to_weekly(daily)
                    if weekly is not None:
                        self.store.set_ohlcv(symbol, "1w", weekly)
                        success += 1
            except:
                pass
        
        # BTC 장기 OHLCV (별도 처리)
        if "BTC/KRW" not in self.symbols:
            for tf in ["1h", "4h"]:
                try:
                    df = self.api.fetch_ohlcv("BTC/KRW", tf)
                    if df is not None and not df.empty:
                        self.store.set_ohlcv("BTC/KRW", tf, df)
                except:
                    pass
                time.sleep(0.15)
            
            # BTC 일봉 변환
            try:
                btc4h = self.store.get_ohlcv("BTC/KRW", "4h")
                if btc4h is not None and len(btc4h) >= 6:
                    btc_daily = self._convert_4h_to_daily(btc4h)
                    if btc_daily is not None:
                        self.store.set_ohlcv("BTC/KRW", "1d", btc_daily)
            except:
                pass
            
            # BTC 주봉 변환
            try:
                btc_daily = self.store.get_ohlcv("BTC/KRW", "1d")
                if btc_daily is not None and len(btc_daily) >= 7:
                    btc_weekly = self._convert_daily_to_weekly(btc_daily)
                    if btc_weekly is not None:
                        self.store.set_ohlcv("BTC/KRW", "1w", btc_weekly)
            except:
                pass
        
        logger.debug(f"[OHLCV] 장기(1h/4h/1d/1w) 갱신 완료: {success}개")

    def _convert_4h_to_daily(self, df4h: pd.DataFrame) -> Optional[pd.DataFrame]:
        """4시간봉 → 일봉 변환"""
        try:
            if df4h is None or len(df4h) < 6:
                return None
            
            df = df4h.copy()
            
            if 'timestamp' in df.columns:
                df['timestamp'] = pd.to_datetime(df['timestamp'])
                df.set_index('timestamp', inplace=True)
            elif not isinstance(df.index, pd.DatetimeIndex):
                try:
                    df.index = pd.to_datetime(df.index)
                except:
                    return None
            
            daily = df.resample('D').agg({
                'open': 'first',
                'high': 'max',
                'low': 'min',
                'close': 'last',
                'volume': 'sum'
            }).dropna()
            
            if len(daily) > 30:
                daily = daily.tail(30)
            
            return daily.reset_index()
            
        except Exception as e:
            logger.error(f"[4h→Daily 변환 오류] {e}")
            return None

    def _convert_daily_to_weekly(self, df_daily: pd.DataFrame) -> Optional[pd.DataFrame]:
        """일봉 → 주봉 변환"""
        try:
            if df_daily is None or len(df_daily) < 7:
                return None
            
            df = df_daily.copy()
            
            if 'timestamp' in df.columns:
                df['timestamp'] = pd.to_datetime(df['timestamp'])
                df.set_index('timestamp', inplace=True)
            elif not isinstance(df.index, pd.DatetimeIndex):
                try:
                    df.index = pd.to_datetime(df.index)
                except:
                    return None
            
            weekly = df.resample('W-MON').agg({
                'open': 'first',
                'high': 'max',
                'low': 'min',
                'close': 'last',
                'volume': 'sum'
            }).dropna()
            
            if len(weekly) > 12:
                weekly = weekly.tail(12)
            
            return weekly.reset_index()
            
        except Exception as e:
            logger.error(f"[Daily→Weekly 변환 오류] {e}")
            return None
    
    # ---------------------------------------------------------
    # 상태 로깅
    # ---------------------------------------------------------
    def _log_status(self):
        uptime = time.time() - self.start_time
        hours = int(uptime // 3600)
        mins = int((uptime % 3600) // 60)
        
        # 🆕 v5.3.0: 캐시 통계 추가
        cache_stats = self.store.get_cache_stats()
        price_stats = cache_stats.get("price_cache", {})
        ohlcv_stats = cache_stats.get("ohlcv_cache", {})
        
        price_hit_rate = price_stats.get("hit_rate", "0%")
        ohlcv_hit_rate = ohlcv_stats.get("hit_rate", "0%")
        
        cached = len(self.store.price_timestamps)
        interval = self._get_price_interval()
        
        logger.info(
            f"[PriceFeed v5.3.0] REST모드 (interval={interval}s), "
            f"prices={cached}/{len(self.symbols)}, "
            f"updates={self.total_updates}, "
            f"failed={self.failed_updates}, "
            f"cache_hit: price={price_hit_rate}, ohlcv={ohlcv_hit_rate}, "
            f"uptime={hours}h{mins}m"
        )
    
    # ---------------------------------------------------------
    # 외부 인터페이스
    # ---------------------------------------------------------
    def get_price(self, symbol: str) -> Optional[float]:
        return self.store.get_price(symbol)
    
    def get_price_safe(self, symbol: str, max_age: float = 120) -> Optional[float]:
        age = self.store.get_price_age(symbol)
        if age > max_age:
            return None
        return self.store.get_price(symbol)
    
    def get_ohlcv(self, symbol: str, timeframe: str) -> Optional[pd.DataFrame]:
        return self.store.get_ohlcv(symbol, timeframe)
    
    def fetch_price_now(self, symbol: str) -> Optional[float]:
        if self.api:
            try:
                ticker = self.api.fetch_ticker(symbol)
                if ticker and ticker.get("last"):
                    price = float(ticker["last"])
                    self.store.set_price(symbol, price)
                    return price
            except Exception as e:
                logger.error(f"[즉시 조회 오류] {symbol}: {e}")
        return self.store.get_price(symbol)
    
    def is_connected(self) -> bool:
        return self.running
    
    def get_state(self):
        from enum import Enum
        class ConnectionState(Enum):
            CONNECTED = "connected"
            DISCONNECTED = "disconnected"
        return ConnectionState.CONNECTED if self.running else ConnectionState.DISCONNECTED
    
    def get_stats(self) -> Dict:
        cache_stats = self.store.get_cache_stats()
        return {
            "total_updates": self.total_updates,
            "failed_updates": self.failed_updates,
            "saved_calls": self.saved_calls,
            "uptime_sec": time.time() - self.start_time if self.start_time else 0,
            "mode": "REST",
            "current_interval": self._get_price_interval(),
            "timeframes": self.SHORT_TIMEFRAMES + self.LONG_TIMEFRAMES,
            "cache_stats": cache_stats,  # 🆕 v5.3.0
        }
    
    def get_health_status(self) -> Dict:
        return {
            "state": "connected" if self.running else "disconnected",
            "connected": self.running,
            "last_update_age_sec": round(self.store.get_last_update_age(), 1),
            "reconnect_count": 0,
            "symbols_count": len(self.symbols),
            "prices_cached": len(self.store.price_timestamps),
            "stale_count": 0,
            "stats": self.get_stats(),
        }
    
    def get_detailed_status(self) -> str:
        status = self.get_health_status()
        stats = status.get("stats", {})
        
        uptime = stats.get("uptime_sec", 0)
        hours = int(uptime // 3600)
        mins = int((uptime % 3600) // 60)
        
        interval = stats.get("current_interval", 10)
        mode_str = "활발" if interval == 10 else "조용"
        
        # 🆕 v5.3.0: 캐시 통계
        cache_stats = stats.get("cache_stats", {})
        price_stats = cache_stats.get("price_cache", {})
        ohlcv_stats = cache_stats.get("ohlcv_cache", {})
        
        lines = [
            "🔌 <b>PriceFeed v5.3.0 상태</b>",
            "",
            f"상태: 🟢 REST 모드 (안정)",
            f"현재 모드: {mode_str} ({interval}초 간격)",
            f"마지막 데이터: {status['last_update_age_sec']:.0f}초 전",
            "",
            "📊 통계",
            f"• 총 갱신: {stats.get('total_updates', 0):,}회",
            f"• 실패: {stats.get('failed_updates', 0):,}회",
            f"• 절약된 호출: {stats.get('saved_calls', 0):,}회",
            f"• 현재 세션: {hours}시간 {mins}분",
            "",
            "💾 캐시 (v5.3.0)",
            f"• 가격 히트율: {price_stats.get('hit_rate', '0%')}",
            f"• OHLCV 히트율: {ohlcv_stats.get('hit_rate', '0%')}",
            "",
            "📡 구독",
            f"• 심볼: {status['symbols_count']}개",
            f"• 캐시된 가격: {status['prices_cached']}개",
            f"• 타임프레임: 5m/15m/30m + 1h/4h/1d/1w",
        ]
        
        return "\n".join(lines)
