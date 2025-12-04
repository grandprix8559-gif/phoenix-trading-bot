# 🐦‍🔥 Phoenix v5.1.0c Trading Bot

AI 기반 빗썸 자동매매 봇

## 🚀 빠른 시작

### 1. 압축 해제 및 설치
```bash
# 압축 해제
unzip phoenix_v5_complete.zip -d /root/phoenix_v5_run
cd /root/phoenix_v5_run

# 원클릭 설치
chmod +x install.sh
./install.sh
```

### 2. API 키 설정
```bash
nano .env
```

필수 설정 항목:
- `TELEGRAM_BOT_TOKEN` - 텔레그램 봇 토큰
- `TELEGRAM_CHAT_ID` - 텔레그램 채팅 ID
- `BITHUMB_API_KEY` - 빗썸 API 키
- `BITHUMB_SECRET_KEY` - 빗썸 시크릿 키
- `OPENAI_API_KEY` - OpenAI API 키

### 3. 봇 실행
```bash
./start.sh
```

## 📋 명령어

| 명령어 | 설명 |
|--------|------|
| `./start.sh` | 봇 시작 |
| `./stop.sh` | 봇 중지 |
| `./restart.sh` | 봇 재시작 |
| `./logs.sh` | 실시간 로그 |
| `./status.sh` | 상태 확인 |

## 📱 텔레그램 명령어

| 명령어 | 설명 |
|--------|------|
| `/status` | 봇 상태 확인 |
| `/balance` | 잔고 조회 |
| `/positions` | 보유 포지션 |
| `/signal` | AI 신호 분석 |
| `/scalp` | 단타모드 ON/OFF |
| `/sync` | 빗썸 동기화 |
| `/help` | 도움말 |

## ⚙️ 설정

### 운영 모드
- **SEMI** (권장): 매수/손절 시 승인 필요
- **AUTO**: 모든 거래 자동 실행

### 자본 분배
- 메인 전략: 80%
- 단타 전략: 20%

### 단타모드 설정
- 익절: 0.6%
- 손절: 0.8%
- 타임아웃: 4시간
- 일일 한도: 30회

## 📂 디렉토리 구조

```
phoenix_v5_run/
├── main.py              # 진입점
├── config.py            # 설정
├── .env                 # API 키 (비공개)
├── positions.json       # 포지션 데이터
├── bot/                 # 봇 코드
│   ├── api/            # 빗썸 API
│   ├── core/           # 핵심 로직
│   ├── telegram/       # 텔레그램 UI
│   └── utils/          # 유틸리티
├── data/               # 거래 기록
└── logs/               # 로그
```

## ⚠️ 주의사항

1. **실거래 전 테스트**: 소액으로 먼저 테스트하세요
2. **API 키 보안**: `.env` 파일을 절대 공유하지 마세요
3. **손실 한도**: 일일 손실 5%, 드로우다운 10% 자동 차단
4. **SEMI 모드 권장**: 자동보다 반자동이 안전합니다

## 📖 문서

상세 기술 명세는 `PHOENIX_RULEBOOK_v5_1_0c.md` 참조

---

**버전**: v5.1.0c  
**최종 업데이트**: 2025-12-02
