# 🔥 Phoenix Trading Bot v5.3.3

> AI 기반 빗썸(Bithumb) KRW 마켓 암호화폐 자동 트레이딩 봇

![Version](https://img.shields.io/badge/version-5.3.3-blue)
![Python](https://img.shields.io/badge/python-3.9+-green)
![License](https://img.shields.io/badge/license-MIT-orange)
![Status](https://img.shields.io/badge/status-active-success)

## ✨ 주요 기능

| 기능 | 설명 |
|:---|:---|
| 🧠 **GPT-4o-mini AI 분석** | 시장 분석 및 매매 판단 |
| 📊 **다층 리스크 관리** | SL/TP, 서킷브레이커, 일일 한도 |
| 📱 **텔레그램 제어** | 실시간 알림 + SEMI 모드 승인 |
| 🕯️ **캔들 패턴 감지** | 잉걸핑, 해머, 도지 자동 감지 |
| 🔮 **빗썸 예측차트** | 5000개 캔들 기반 확률 분석 |
| 💰 **동적 TP/SL** | ATR + BTC 모드 기반 자동 조절 |

## 🚀 빠른 시작

### 1. 설치

```bash
# 클론
git clone https://github.com/grandprix8559-gif/phoenix-trading-bot.git
cd phoenix-trading-bot

# 원클릭 설치
chmod +x install.sh
./install.sh
```

### 2. 환경 설정

```bash
nano .env
```

```env
# 필수 설정
TELEGRAM_BOT_TOKEN=your_telegram_bot_token
TELEGRAM_CHAT_ID=your_chat_id
BITHUMB_API_KEY=your_bithumb_api_key
BITHUMB_SECRET_KEY=your_bithumb_secret_key
OPENAI_API_KEY=your_openai_api_key
```

### 3. 실행

```bash
./start.sh
```

## 📱 텔레그램 명령어

| 카테고리 | 명령어 | 설명 |
|:---|:---|:---|
| **정보** | `/status` | 봇 상태, MODE, 포지션 수 |
| | `/balance` | KRW 및 코인 잔고 |
| | `/positions` | 현재 보유 포지션 상세 |
| | `/risk` | 일일 손실, 서킷브레이커 상태 |
| **매매** | `/mode` | AUTO ↔ SEMI 전환 |
| | `/close [코인]` | 특정 코인 수동 청산 |
| | `/close_all` | 전체 포지션 청산 |
| **분석** | `/signal [코인]` | AI + 전략 신호 분석 |
| | `/pivot [코인]` | 피봇 포인트 지지/저항 |
| | `/analyze [코인]` | GPT-4o-mini 심층 분석 |
| **시스템** | `/sync` | 빗썸 잔고 동기화 |
| | `/help` | 도움말 |

## ⚙️ 운영 모드

| 모드 | 설명 | 권장 |
|:---:|:---|:---:|
| **SEMI** | 매수/손절 시 텔레그램 승인 필요 | ✅ **권장** |
| **AUTO** | 모든 거래 자동 실행 | ⚠️ 주의 |

## 📊 리스크 관리

| 항목 | 설정값 | 설명 |
|:---|:---:|:---|
| 일일 손실 한도 | **5%** | 도달 시 자동 차단 |
| 드로우다운 한도 | **10%** | 서킷브레이커 발동 |
| 최대 포지션 | **4개** | 동시 보유 한도 |
| 단일 비중 상한 | **40%** | 절대 초과 금지 |
| AI SL 범위 | **2~5%** | 동적 손절 |
| 최대 DCA | **3회** | 추가 매수 한도 |

## 📁 디렉토리 구조

```
phoenix-trading-bot/
├── main.py                  # 진입점
├── config.py                # 설정
├── bot/
│   ├── api/                 # 빗썸 API (CCXT)
│   ├── core/                # 핵심 로직
│   │   ├── ai/              # AI 모듈 (GPT-4o-mini)
│   │   │   ├── decision_engine.py
│   │   │   ├── prompt_builder.py
│   │   │   └── response_parser.py
│   │   └── indicators/      # 기술적 지표
│   │       └── candle_patterns.py
│   ├── telegram/            # 텔레그램 UI
│   └── utils/               # 유틸리티
├── data/                    # 운영 데이터
└── docs/                    # 문서
```

## 🔧 코인 풀 (20종)

```python
COIN_POOL = [
    # 메이저 (2종)
    "ETH/KRW", "XRP/KRW",
    
    # 중소형 알트 (10종)
    "SOL/KRW", "SUI/KRW", "SEI/KRW", "ONDO/KRW", 
    "ENS/KRW", "ENA/KRW", "HBAR/KRW", "KAIA/KRW",
    "WLD/KRW", "LINK/KRW",
    
    # 밈코인 (6종)
    "DOGE/KRW", "SHIB/KRW", "PEPE/KRW", "BONK/KRW",
    "MOODENG/KRW", "PENGU/KRW",
    
    # 기타 (2종)
    "SAND/KRW", "TRX/KRW",
]
```

## ⚠️ 주의사항

1. **실거래 전 테스트**: 소액으로 먼저 테스트하세요
2. **API 키 보안**: `.env` 파일을 절대 공유하지 마세요
3. **SEMI 모드 권장**: 자동보다 반자동이 안전합니다
4. **손실 책임**: 모든 거래 손실은 사용자 책임입니다

## 📚 문서

- [운영 규칙서 (Rulebook)](docs/RULEBOOK.md)
- [변경 이력 (Changelog)](docs/CHANGELOG.md)

## 📜 라이선스

MIT License - 자유롭게 사용 가능하나 손실 책임은 사용자에게 있습니다.

---

**버전**: v5.3.3  
**최종 업데이트**: 2025-12-05
