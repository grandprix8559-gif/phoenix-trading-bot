# -*- coding: utf-8 -*-
"""
Phoenix v5.1.0 — AI 포트폴리오 최적화 모듈 (시장 데이터 기반 동적 추천)

v5.1.0 개선사항:
- 카테고리별 코인 분류 (메이저/중소형/밈코인)
- 실시간 시장 데이터 수집 (24h 변동률, 거래량, RSI)
- 개선된 프롬프트 (카테고리 제약 + 시장 데이터)
- 변동성 기반 동적 비중 할당
"""

from typing import Dict, List, Optional
import json
import requests
import pandas as pd
from datetime import datetime

from config import Config, COIN_CATEGORIES
from bot.utils.logger import get_logger

logger = get_logger("Portfolio")

# =========================================================
# 개선된 System Prompt (v5.1.0)
# =========================================================
SYSTEM_PROMPT = """
너는 Phoenix v5.1.0 암호화폐 트레이딩 봇의 포트폴리오 AI다.

## 목표
실시간 시장 데이터를 기반으로 **단타/스윙 트레이딩에 최적화된** 포트폴리오를 구성한다.

## 포트폴리오 구성 규칙 (필수)
1. **메이저 (ETH, XRP)**: 정확히 1개 선택 (비중 15~25%)
2. **중소형 알트**: 1~2개 선택 (비중 25~40%)
3. **밈코인**: 정확히 1개 선택 (비중 20~35%)
4. **총 코인 수**: 3~4개
5. **비중 합계**: 정확히 1.0

## 코인 선정 기준 (우선순위)
1. **24시간 변동률 2% 이상** 우선 (단타 수익 기회)
2. **거래량 상위** 코인 우선 (유동성 확보)
3. **RSI 30~65** 범위 우선 (과매수 회피)
4. 같은 카테고리 내에서 변동률 높은 코인 선택

## 비중 결정 기준
- 변동률 높을수록 비중 ↑
- RSI가 30~50이면 비중 ↑ (상승 여력)
- 거래량 많을수록 비중 ↑

## 출력 형식 (JSON만, 다른 텍스트 금지)
{
  "portfolio": [
    {"symbol": "ETH", "weight": 0.20, "category": "major", "reason": "거래량 1위, 안정적"},
    {"symbol": "SUI", "weight": 0.30, "category": "midcap", "reason": "24h +8.5%, RSI 45"},
    {"symbol": "PEPE", "weight": 0.30, "category": "meme", "reason": "24h +12.3%, RSI 52"},
    {"symbol": "ENS", "weight": 0.20, "category": "midcap", "reason": "24h +5.2%, RSI 38"}
  ],
  "market_comment": "현재 시장 상황 한줄 요약"
}
"""


class PortfolioOptimizer:
    """
    gpt-4o 기반 포트폴리오 추천기 (시장 데이터 기반 동적 추천)

    v5.1.0 개선:
    - 실시간 시장 데이터 수집
    - 카테고리별 코인 분류
    - 변동성 기반 동적 비중 할당
    """

    def __init__(self, api=None):
        self.api = api
        self.api_key: str = (Config.OPENAI_API_KEY or "").strip()
        
        # 캐시 (하루 1번만 AI 호출)
        self._last_date: Optional[str] = None
        self._last_portfolio: Optional[Dict[str, float]] = None
        self._last_market_comment: Optional[str] = None

        if not self.api_key:
            logger.warning("OPENAI_API_KEY 미설정 - AI 포트폴리오 비활성화, 균등 분배 사용")

    # ------------------------------------------------------------------ #
    # 시장 데이터 수집
    # ------------------------------------------------------------------ #
    def _fetch_market_data(self) -> Dict:
        """전체 코인풀 시장 데이터 수집"""
        market_data = {}
        
        if self.api is None:
            logger.warning("API 객체 없음 - 시장 데이터 수집 불가")
            return market_data
        
        for symbol in Config.COIN_POOL:
            try:
                # 티커 정보
                ticker = self.api.fetch_ticker(symbol)
                
                # OHLCV로 RSI 계산
                ohlcv = self.api.fetch_ohlcv(symbol, "1h", limit=20)
                df = pd.DataFrame(ohlcv, columns=["timestamp", "open", "high", "low", "close", "volume"])
                
                rsi_val = self._calculate_rsi(df["close"])
                
                market_data[symbol] = {
                    "price": ticker.get("last", 0),
                    "change_24h": ticker.get("percentage", 0) / 100,  # 소수점으로
                    "volume_krw": ticker.get("quoteVolume", 0),
                    "rsi": rsi_val,
                }
                
            except Exception as e:
                logger.warning(f"[MARKET DATA] {symbol} 수집 실패: {e}")
                market_data[symbol] = {
                    "price": 0,
                    "change_24h": 0,
                    "volume_krw": 0,
                    "rsi": 50,
                }
        
        return market_data

    def _calculate_rsi(self, close_series, period: int = 14) -> float:
        """RSI 계산"""
        try:
            delta = close_series.diff()
            gain = delta.where(delta > 0, 0).rolling(period).mean()
            loss = (-delta.where(delta < 0, 0)).rolling(period).mean()
            rs = gain / loss.replace(0, 1e-9)
            rsi = 100 - (100 / (1 + rs))
            return float(rsi.iloc[-1])
        except:
            return 50.0

    # ------------------------------------------------------------------ #
    # 프롬프트 생성
    # ------------------------------------------------------------------ #
    def _format_category_data(self, market_data: Dict, category: str) -> str:
        """카테고리별 시장 데이터 포맷팅"""
        coins = COIN_CATEGORIES.get(category, [])
        lines = []
        
        for coin in coins:
            symbol = f"{coin}/KRW"
            data = market_data.get(symbol, {})
            
            change_24h = data.get("change_24h", 0) * 100
            volume_krw = data.get("volume_krw", 0) / 1_000_000  # 백만원 단위
            rsi = data.get("rsi", 50)
            
            emoji = "🔥" if abs(change_24h) >= 5 else "📈" if change_24h > 0 else "📉"
            
            lines.append(
                f"- {coin}: {emoji} {change_24h:+.1f}% | 거래량 {volume_krw:.0f}백만 | RSI {rsi:.0f}"
            )
        
        return "\n".join(lines) if lines else "- 데이터 없음"

    def _build_user_prompt(self, market_data: Dict) -> str:
        """시장 데이터 포함 프롬프트 생성"""
        max_coins = Config.MAX_ACTIVE_COINS
        
        prompt = f"""
## 현재 시장 데이터 (KST 기준)

### 메이저
{self._format_category_data(market_data, "major")}

### 중소형 알트
{self._format_category_data(market_data, "midcap")}

### 밈코인
{self._format_category_data(market_data, "meme")}

### 기타
{self._format_category_data(market_data, "other")}

---

위 데이터를 분석하여 다음 조건에 맞는 포트폴리오를 구성해주세요:

1. 메이저에서 1개 선택 (거래량/안정성 고려)
2. 중소형에서 1~2개 선택 (변동률 높은 순)
3. 밈코인에서 1개 선택 (변동률 높은 순, RSI 30~65 우선)
4. 총 3~{max_coins}개, 비중 합계 1.0

**변동률이 높고 RSI가 적정 범위(30~65)인 코인에 더 높은 비중을 할당하세요.**
**RSI 70 이상은 과매수 구간이므로 피하세요.**

출력은 반드시 JSON 하나로만:
{{
  "portfolio": [
    {{"symbol": "ETH", "weight": 0.20, "category": "major", "reason": "..."}},
    ...
  ],
  "market_comment": "시장 상황 한줄 요약"
}}
        """.strip()
        
        return prompt

    def _build_fallback_prompt(self, coins: List[str]) -> str:
        """시장 데이터 없을 때 기존 방식 프롬프트"""
        max_coins = Config.MAX_ACTIVE_COINS
        base_symbols = [c.split("/")[0].upper() for c in coins]
        
        prompt = f"""
다음 코인 리스트에서 {max_coins}개 이하를 선택해서 단기 트레이딩용 포트폴리오를 구성해 주세요.

코인 리스트: {", ".join(base_symbols)}

조건:
- 반드시 1~{max_coins}개의 코인을 선택한다.
- 각 코인 weight 는 0.1 ~ 0.5 사이에서 합이 정확히 1.0 이 되도록 할 것.
- 전략들은 모두 빗썸 KRW 마켓 기준:
  - Phoenix v3.2: 30분봉 추세 추종
  - BB Scalping: 5분봉 스캘핑
  - VWAP Reversal: 15분봉 반전
- 이 전략들에 무난히 맞는 코인 위주로 선택하되,
  너무 비슷한 코인만 몰리지 않도록 분산을 고려한다.

출력은 반드시 JSON 하나로만:
{{
  "portfolio": [
    {{"symbol": "SOL", "weight": 0.25}},
    ...
  ]
}}
        """.strip()
        
        return prompt

    # ------------------------------------------------------------------ #
    # 기본 균등 분배
    # ------------------------------------------------------------------ #
    def _equal_weight(self, coins: List[str]) -> Dict[str, float]:
        """단순 균등분배 포트폴리오"""
        coins = [c.upper() for c in coins]
        if not coins:
            return {}
        w = round(1.0 / len(coins), 4)
        return {c: w for c in coins}

    def _category_balanced_fallback(self) -> Dict[str, float]:
        """카테고리 균형 잡힌 fallback 포트폴리오"""
        portfolio = {}
        
        # 메이저 1개 (25%)
        if COIN_CATEGORIES.get("major"):
            major = COIN_CATEGORIES["major"][0]
            portfolio[f"{major}/KRW"] = 0.25
        
        # 중소형 2개 (각 25%)
        midcaps = COIN_CATEGORIES.get("midcap", [])[:2]
        for coin in midcaps:
            portfolio[f"{coin}/KRW"] = 0.25
        
        # 밈 1개 (25%)
        if COIN_CATEGORIES.get("meme"):
            meme = COIN_CATEGORIES["meme"][0]
            portfolio[f"{meme}/KRW"] = 0.25
        
        # 정규화
        if portfolio:
            total = sum(portfolio.values())
            portfolio = {k: v / total for k, v in portfolio.items()}
        
        return portfolio

    # ------------------------------------------------------------------ #
    # gpt-4o 호출 (Chat Completions API)
    # ------------------------------------------------------------------ #
    def _call_gpt4o(self, coins: List[str], market_data: Optional[Dict] = None) -> Dict[str, float]:
        """
        /v1/chat/completions 엔드포인트를 직접 호출해서
        {symbol: weight} 딕셔너리 반환.
        실패 시 예외 발생 → 상위에서 fallback 처리.
        """
        max_coins = Config.MAX_ACTIVE_COINS
        url = "https://api.openai.com/v1/chat/completions"

        # 시장 데이터 유무에 따라 프롬프트 선택
        if market_data:
            user_prompt = self._build_user_prompt(market_data)
        else:
            user_prompt = self._build_fallback_prompt(coins)

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

        payload = {
            "model": Config.OPENAI_MODEL,
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ],
            "response_format": {"type": "json_object"},
            "temperature": 0.3,
            "max_tokens": 600,
        }

        r = requests.post(url, headers=headers, data=json.dumps(payload), timeout=30)
        if r.status_code != 200:
            raise RuntimeError(f"HTTP {r.status_code}: {r.text}")

        resp = r.json()
        try:
            txt = resp["choices"][0]["message"]["content"]
        except Exception as e:
            raise ValueError(f"응답 파싱 실패: {e}, raw={resp}")

        data = json.loads(txt)
        items = data.get("portfolio", [])
        
        # 시장 코멘트 저장
        self._last_market_comment = data.get("market_comment", "")
        
        result: Dict[str, float] = {}
        total = 0.0

        # base_symbols 기준으로 유효성 체크
        base_symbols = [c.split("/")[0].upper() for c in coins]
        valid_set = set(base_symbols)

        for item in items:
            sym_raw = str(item.get("symbol", "")).upper()
            w = float(item.get("weight", 0.0))
            
            # reason과 category 로깅
            reason = item.get("reason", "")
            category = item.get("category", "unknown")

            if sym_raw in valid_set and w > 0:
                sym_full = f"{sym_raw}/KRW"
                result[sym_full] = result.get(sym_full, 0.0) + w
                total += w
                logger.debug(f"  [{category}] {sym_raw}: {w*100:.1f}% - {reason}")

        if not result:
            raise ValueError(f"AI 응답에서 유효한 포트폴리오를 찾지 못함: {data}")

        # 정규화 (합계 1.0 보정)
        result = {k: v / total for k, v in result.items()}

        # 코인 수가 너무 많으면 상위 max_coins 개만 사용
        if len(result) > max_coins:
            sorted_items = sorted(result.items(), key=lambda x: x[1], reverse=True)
            result = dict(sorted_items[:max_coins])
            s = sum(result.values())
            result = {k: v / s for k, v in result.items()}

        return result

    # ------------------------------------------------------------------ #
    # 퍼블릭 인터페이스
    # ------------------------------------------------------------------ #
    def recommend_portfolio(self, coins: List[str]) -> Dict[str, float]:
        """
        코인 리스트를 받아서 {코인: 비중} dict 반환
        - 실시간 시장 데이터 기반 동적 추천
        - 실패 시 카테고리 균형 fallback
        """
        coins = [c.upper() for c in coins]
        if not coins:
            return {}

        max_coins = Config.MAX_ACTIVE_COINS

        # API 키 없으면 카테고리 균형 fallback
        if not self.api_key:
            pf = self._category_balanced_fallback()
            if not pf:
                pf = self._equal_weight(coins[:max_coins])
            logger.info(
                "AI 비활성화 → Fallback 포트폴리오: "
                + ", ".join(f"{k} {v*100:.1f}%" for k, v in pf.items())
            )
            return pf

        try:
            # 시장 데이터 수집
            market_data = self._fetch_market_data()
            
            if market_data:
                logger.info(f"시장 데이터 수집 완료: {len(market_data)}개 코인")
            else:
                logger.warning("시장 데이터 없음 - 기존 방식으로 진행")
            
            # AI 호출
            result = self._call_gpt4o(coins, market_data if market_data else None)
            
            # 결과 로깅
            log_msg = "AI 포트폴리오: " + ", ".join(f"{k} {v*100:.1f}%" for k, v in result.items())
            if self._last_market_comment:
                log_msg += f" | 📊 {self._last_market_comment}"
            logger.info(log_msg)
            
            return result

        except Exception as e:
            logger.error(f"AI 포트폴리오 추천 실패: {e}")
            
            # 카테고리 균형 fallback 시도
            pf = self._category_balanced_fallback()
            if not pf:
                pf = self._equal_weight(coins[:max_coins])
            
            logger.info(
                "Fallback 포트폴리오: "
                + ", ".join(f"{k} {v*100:.1f}%" for k, v in pf.items())
            )
            return pf

    # ------------------------------------------------------------------ #
    # 하루 한 번만 포트폴리오 계산
    # ------------------------------------------------------------------ #
    def get_today_portfolio(self, coins: List[str]) -> Dict[str, float]:
        """
        같은 날에는 이전에 계산한 포트폴리오 재사용
        날짜 바뀌면 새로 recommend_portfolio() 호출
        """
        today = datetime.now().date().isoformat()

        if self._last_date == today and self._last_portfolio:
            return self._last_portfolio

        pf = self.recommend_portfolio(coins)
        self._last_date = today
        self._last_portfolio = pf
        return pf

    def get_last_market_comment(self) -> str:
        """마지막 시장 코멘트 반환"""
        return self._last_market_comment or ""

    def force_refresh(self, coins: List[str]) -> Dict[str, float]:
        """캐시 무시하고 강제 새로고침"""
        self._last_date = None
        self._last_portfolio = None
        return self.recommend_portfolio(coins)


# 👇 호환용 alias
AIPortfolioOptimizer = PortfolioOptimizer
