# -*- coding: utf-8 -*-
"""
Phoenix v5.3.1 — 빗썸 예측차트 모듈

빗썸 AI 예측차트 알고리즘을 직접 구현하여
Phoenix AI 판단의 보조 지표로 활용

알고리즘 원리:
- 직전 5,000개 캔들 데이터 분석
- 이전 캔들 고가(High) 돌파 빈도 → 상승 확률
- 이전 캔들 저가(Low) 하회 빈도 → 하락 확률
- 정확도 70% 이상 코인만 AI 판단에 활용

🔥 v5.3.1 기능:
- 개별 코인 예측 (get_prediction)
- BTC 추세 분석 보조 (get_btc_prediction)
- AI 프롬프트 통합 (get_prediction_for_ai)
- 정확도 기반 필터링 (70%+)
"""

import time
import pandas as pd
from typing import Dict, Optional, List, Tuple
from dataclasses import dataclass
from datetime import datetime

from bot.utils.logger import get_logger
from bot.utils.cache import CacheManager

logger = get_logger("BithumbPredictor")


# =========================================================
# 설정값
# =========================================================

# 분석 설정
LOOKBACK_CANDLES = 5000      # 분석할 캔들 수 (빗썸 기준)
MIN_CANDLES = 500            # 최소 필요 캔들 수
ACCURACY_THRESHOLD = 0.70    # 정확도 임계값 (70%)
HIGH_ACCURACY_THRESHOLD = 0.80  # 높은 정확도 임계값 (80%)

# 캐시 설정
PREDICTION_CACHE_TTL = 900   # 예측 캐시 15분
ACCURACY_CACHE_TTL = 3600    # 정확도 캐시 1시간

# 캐시 인스턴스
prediction_cache = CacheManager(default_ttl=PREDICTION_CACHE_TTL, name="bithumb_pred")
accuracy_cache = CacheManager(default_ttl=ACCURACY_CACHE_TTL, name="bithumb_acc")


# =========================================================
# 데이터 클래스
# =========================================================

@dataclass
class PredictionResult:
    """예측 결과"""
    symbol: str
    timeframe: str
    up_probability: float      # 상승 확률 (0~100)
    down_probability: float    # 하락 확률 (0~100)
    signal: str                # 'bullish', 'bearish', 'neutral'
    signal_strength: float     # 신호 강도 (상승-하락 차이)
    accuracy: float            # 예측 정확도 (0~100)
    is_reliable: bool          # 신뢰 가능 여부 (정확도 70%+)
    is_high_accuracy: bool     # 높은 정확도 (80%+)
    candles_analyzed: int      # 분석된 캔들 수
    timestamp: datetime
    
    def to_dict(self) -> Dict:
        return {
            "symbol": self.symbol,
            "timeframe": self.timeframe,
            "up_prob": round(self.up_probability, 1),
            "down_prob": round(self.down_probability, 1),
            "signal": self.signal,
            "signal_strength": round(self.signal_strength, 1),
            "accuracy": round(self.accuracy, 1),
            "is_reliable": self.is_reliable,
            "is_high_accuracy": self.is_high_accuracy,
            "candles": self.candles_analyzed,
        }
    
    def to_ai_prompt(self) -> str:
        """AI 프롬프트용 문자열 생성"""
        if not self.is_reliable:
            return ""
        
        reliability = "높음" if self.is_high_accuracy else "보통"
        signal_kr = {
            "bullish": "상승우세",
            "bearish": "하락우세", 
            "neutral": "중립"
        }.get(self.signal, self.signal)
        
        return (
            f"빗썸예측(정확도{self.accuracy:.0f}%): "
            f"상승{self.up_probability:.0f}% 하락{self.down_probability:.0f}% "
            f"→ {signal_kr}({self.signal_strength:+.0f}%p)"
        )


@dataclass
class BTCPredictionContext:
    """BTC 예측 컨텍스트 (시장 분석용)"""
    up_probability: float
    down_probability: float
    signal: str
    signal_strength: float
    accuracy: float
    is_reliable: bool
    market_bias: str  # 'risk_on', 'risk_off', 'neutral'
    
    def to_dict(self) -> Dict:
        return {
            "btc_up_prob": round(self.up_probability, 1),
            "btc_down_prob": round(self.down_probability, 1),
            "btc_signal": self.signal,
            "btc_strength": round(self.signal_strength, 1),
            "btc_accuracy": round(self.accuracy, 1),
            "btc_reliable": self.is_reliable,
            "market_bias": self.market_bias,
        }
    
    def to_ai_prompt(self) -> str:
        """BTC 분석용 AI 프롬프트"""
        if not self.is_reliable:
            return ""
        
        bias_kr = {
            "risk_on": "위험선호(알트유리)",
            "risk_off": "위험회피(알트불리)",
            "neutral": "중립"
        }.get(self.market_bias, self.market_bias)
        
        return (
            f"BTC예측(정확도{self.accuracy:.0f}%): "
            f"상승{self.up_probability:.0f}% 하락{self.down_probability:.0f}% "
            f"→ {bias_kr}"
        )


# =========================================================
# 핵심 계산 클래스
# =========================================================

class BithumbPredictor:
    """
    빗썸 예측차트 알고리즘 구현
    
    빗썸 공식 알고리즘:
    - 상승 확률 = (다음 캔들이 이전 캔들 고가를 돌파한 횟수) / 전체 캔들 수
    - 하락 확률 = (다음 캔들이 이전 캔들 저가를 하회한 횟수) / 전체 캔들 수
    """
    
    _instance = None
    
    def __new__(cls, *args, **kwargs):
        """싱글톤 패턴"""
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance
    
    def __init__(self, api=None):
        if self._initialized:
            return
            
        self.api = api
        self._initialized = True
        logger.info("[BithumbPredictor v5.3.1] 초기화 완료")
    
    def set_api(self, api):
        """API 인스턴스 설정"""
        self.api = api
        logger.debug("[BithumbPredictor] API 설정됨")
    
    # =========================================================
    # 핵심 계산 메서드
    # =========================================================
    
    def _calculate_probabilities(self, df: pd.DataFrame) -> Tuple[float, float]:
        """
        상승/하락 확률 계산 (빗썸 알고리즘)
        
        Args:
            df: OHLCV DataFrame (high, low 컬럼 필수)
            
        Returns:
            (상승확률, 하락확률) 튜플 (0~100 범위)
        """
        if df is None or len(df) < 2:
            return 50.0, 50.0
        
        # 이전 캔들의 고가/저가
        df = df.copy()
        df['prev_high'] = df['high'].shift(1)
        df['prev_low'] = df['low'].shift(1)
        
        # NaN 제거 (첫 번째 행)
        df = df.dropna()
        
        if len(df) == 0:
            return 50.0, 50.0
        
        # 상승 확률: 이전 캔들 고가를 돌파한 비율
        up_breaks = (df['high'] > df['prev_high']).sum()
        up_prob = (up_breaks / len(df)) * 100
        
        # 하락 확률: 이전 캔들 저가를 하회한 비율
        down_breaks = (df['low'] < df['prev_low']).sum()
        down_prob = (down_breaks / len(df)) * 100
        
        return up_prob, down_prob
    
    def _calculate_accuracy(self, df: pd.DataFrame) -> float:
        """
        예측 정확도 계산 (간소화된 백테스트)
        
        최근 100개 캔들 샘플링으로 예측 정확도 검증
        
        Args:
            df: OHLCV DataFrame
            
        Returns:
            정확도 (0~100)
        """
        if df is None or len(df) < 200:
            return 50.0
        
        correct = 0
        total = 0
        
        # 최근 100개 중 20개 샘플링 (성능 최적화)
        sample_indices = range(len(df) - 100, len(df) - 1, 5)
        
        for i in sample_indices:
            if i < MIN_CANDLES:
                continue
            
            # 해당 시점까지의 데이터로 예측
            hist_df = df.iloc[:i]
            up_prob, down_prob = self._calculate_probabilities(hist_df)
            
            # 다음 캔들 실제 결과
            current_close = df.iloc[i]['close']
            next_close = df.iloc[i + 1]['close']
            actual_up = next_close > current_close
            
            # 예측 vs 실제
            predicted_up = up_prob > down_prob
            
            if predicted_up == actual_up:
                correct += 1
            total += 1
        
        if total == 0:
            return 50.0
        
        return (correct / total) * 100
    
    def _determine_signal(self, up_prob: float, down_prob: float) -> Tuple[str, float]:
        """신호 판단"""
        diff = up_prob - down_prob
        
        if diff > 10:
            return "bullish", diff
        elif diff < -10:
            return "bearish", diff
        else:
            return "neutral", diff
    
    def _determine_market_bias(self, btc_signal: str, btc_strength: float) -> str:
        """
        BTC 신호 기반 시장 분위기 판단
        
        - BTC 상승 예측 → 시장 위험선호 (알트코인 유리)
        - BTC 하락 예측 → 시장 위험회피 (알트코인 불리)
        """
        if btc_signal == "bullish" and btc_strength > 15:
            return "risk_on"
        elif btc_signal == "bearish" and btc_strength < -15:
            return "risk_off"
        else:
            return "neutral"
    
    # =========================================================
    # 메인 API
    # =========================================================
    
    def get_prediction(
        self, 
        symbol: str, 
        timeframe: str = "1h",
        force: bool = False,
    ) -> Optional[PredictionResult]:
        """
        특정 코인의 예측 결과 조회
        
        Args:
            symbol: 심볼 (예: SOL/KRW)
            timeframe: 타임프레임 (기본 1h)
            force: 캐시 무시
            
        Returns:
            PredictionResult 또는 None
        """
        if not self.api:
            logger.warning("[Predictor] API 미설정")
            return None
        
        # 캐시 확인
        cache_key = f"pred:{symbol}:{timeframe}"
        if not force:
            cached = prediction_cache.get(cache_key)
            if cached:
                return cached
        
        # OHLCV 데이터 조회
        try:
            df = self.api.fetch_ohlcv(symbol, timeframe, limit=LOOKBACK_CANDLES)
            if df is None or len(df) < MIN_CANDLES:
                logger.warning(f"[Predictor] {symbol} 데이터 부족: {len(df) if df is not None else 0}개")
                return None
        except Exception as e:
            logger.error(f"[Predictor] {symbol} OHLCV 조회 실패: {e}")
            return None
        
        # DataFrame 변환
        if isinstance(df, list):
            df = pd.DataFrame(df, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
        
        # 확률 계산
        up_prob, down_prob = self._calculate_probabilities(df)
        
        # 정확도 계산 (캐시 활용)
        accuracy_key = f"acc:{symbol}:{timeframe}"
        accuracy = accuracy_cache.get(accuracy_key)
        if accuracy is None:
            accuracy = self._calculate_accuracy(df)
            accuracy_cache.set(accuracy_key, accuracy)
        
        # 신호 판단
        signal, strength = self._determine_signal(up_prob, down_prob)
        
        # 결과 생성
        result = PredictionResult(
            symbol=symbol,
            timeframe=timeframe,
            up_probability=up_prob,
            down_probability=down_prob,
            signal=signal,
            signal_strength=strength,
            accuracy=accuracy,
            is_reliable=(accuracy >= ACCURACY_THRESHOLD * 100),
            is_high_accuracy=(accuracy >= HIGH_ACCURACY_THRESHOLD * 100),
            candles_analyzed=len(df),
            timestamp=datetime.now(),
        )
        
        # 캐시 저장
        prediction_cache.set(cache_key, result)
        
        logger.debug(
            f"[Predictor] {symbol} up={up_prob:.1f}% down={down_prob:.1f}% "
            f"acc={accuracy:.1f}% signal={signal}"
        )
        
        return result
    
    # =========================================================
    # BTC 추세 분석 (시장 컨텍스트)
    # =========================================================
    
    def get_btc_prediction(
        self, 
        timeframe: str = "1h",
        force: bool = False,
    ) -> Optional[BTCPredictionContext]:
        """
        BTC 예측으로 시장 분위기 분석
        
        Args:
            timeframe: 타임프레임
            force: 캐시 무시
            
        Returns:
            BTCPredictionContext 또는 None
        """
        # 캐시 확인
        cache_key = f"btc_context:{timeframe}"
        if not force:
            cached = prediction_cache.get(cache_key)
            if cached:
                return cached
        
        # BTC 예측 조회
        btc_result = self.get_prediction("BTC/KRW", timeframe, force)
        
        if not btc_result:
            return None
        
        # 시장 분위기 판단
        market_bias = self._determine_market_bias(
            btc_result.signal, 
            btc_result.signal_strength
        )
        
        result = BTCPredictionContext(
            up_probability=btc_result.up_probability,
            down_probability=btc_result.down_probability,
            signal=btc_result.signal,
            signal_strength=btc_result.signal_strength,
            accuracy=btc_result.accuracy,
            is_reliable=btc_result.is_reliable,
            market_bias=market_bias,
        )
        
        # 캐시 저장
        prediction_cache.set(cache_key, result)
        
        logger.info(
            f"[BTC Predictor] up={result.up_probability:.1f}% "
            f"down={result.down_probability:.1f}% bias={market_bias}"
        )
        
        return result
    
    def get_btc_context_for_ai(self, timeframe: str = "1h") -> str:
        """
        AI BTC Context에 추가할 예측 정보
        
        Returns:
            AI 프롬프트용 BTC 예측 문자열
        """
        btc_ctx = self.get_btc_prediction(timeframe)
        
        if not btc_ctx or not btc_ctx.is_reliable:
            return ""
        
        return btc_ctx.to_ai_prompt()
    
    # =========================================================
    # AI 통합 메서드
    # =========================================================
    
    def get_prediction_for_ai(
        self, 
        symbol: str, 
        timeframe: str = "1h",
        include_btc: bool = True,
    ) -> str:
        """
        AI 프롬프트용 종합 예측 정보
        
        Args:
            symbol: 코인 심볼
            timeframe: 타임프레임
            include_btc: BTC 예측 포함 여부
            
        Returns:
            AI 프롬프트용 문자열 (정확도 70% 미만이면 빈 문자열)
        """
        parts = []
        
        # 개별 코인 예측
        result = self.get_prediction(symbol, timeframe)
        if result and result.is_reliable:
            parts.append(result.to_ai_prompt())
        
        # BTC 예측 (시장 분위기)
        if include_btc and symbol != "BTC/KRW":
            btc_info = self.get_btc_context_for_ai(timeframe)
            if btc_info:
                parts.append(btc_info)
        
        return " | ".join(parts) if parts else ""
    
    # =========================================================
    # 배치 및 통계
    # =========================================================
    
    def get_predictions_batch(
        self, 
        symbols: List[str], 
        timeframe: str = "1h",
    ) -> Dict[str, PredictionResult]:
        """여러 코인 일괄 예측"""
        results = {}
        
        for symbol in symbols:
            result = self.get_prediction(symbol, timeframe)
            if result:
                results[symbol] = result
            time.sleep(0.05)  # Rate limit 방지
        
        return results
    
    def get_reliable_coins(
        self, 
        symbols: List[str], 
        timeframe: str = "1h",
    ) -> List[str]:
        """정확도 70%+ 코인 목록 반환"""
        results = self.get_predictions_batch(symbols, timeframe)
        
        return [
            symbol for symbol, result in results.items()
            if result.is_reliable
        ]
    
    def get_accuracy_ranking(
        self, 
        symbols: List[str], 
        timeframe: str = "1h",
    ) -> List[Tuple[str, float]]:
        """코인별 정확도 순위"""
        results = self.get_predictions_batch(symbols, timeframe)
        
        ranking = [
            (symbol, result.accuracy)
            for symbol, result in results.items()
        ]
        
        return sorted(ranking, key=lambda x: x[1], reverse=True)
    
    def get_stats(self) -> Dict:
        """통계 정보"""
        return {
            "prediction_cache": prediction_cache.stats(),
            "accuracy_cache": accuracy_cache.stats(),
            "thresholds": {
                "accuracy": ACCURACY_THRESHOLD * 100,
                "high_accuracy": HIGH_ACCURACY_THRESHOLD * 100,
            },
            "settings": {
                "lookback_candles": LOOKBACK_CANDLES,
                "min_candles": MIN_CANDLES,
                "cache_ttl_prediction": PREDICTION_CACHE_TTL,
                "cache_ttl_accuracy": ACCURACY_CACHE_TTL,
            }
        }
    
    def clear_cache(self):
        """캐시 초기화"""
        prediction_cache.clear()
        accuracy_cache.clear()
        logger.info("[BithumbPredictor] 캐시 초기화됨")


# =========================================================
# 글로벌 인스턴스
# =========================================================

predictor = BithumbPredictor()


# =========================================================
# 편의 함수
# =========================================================

def get_predictor() -> BithumbPredictor:
    """글로벌 인스턴스 반환"""
    return predictor


def get_prediction(symbol: str, timeframe: str = "1h") -> Optional[PredictionResult]:
    """예측 조회 (단축 함수)"""
    return predictor.get_prediction(symbol, timeframe)


def get_btc_prediction(timeframe: str = "1h") -> Optional[BTCPredictionContext]:
    """BTC 예측 조회 (단축 함수)"""
    return predictor.get_btc_prediction(timeframe)


def get_prediction_for_ai(symbol: str, timeframe: str = "1h") -> str:
    """AI용 예측 정보 (단축 함수)"""
    return predictor.get_prediction_for_ai(symbol, timeframe)
