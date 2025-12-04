# Phoenix v5.3.0 — VPS 배포 가이드

> **작성일:** 2025-12-04
> **버전:** v5.3.0 (리팩토링 완료)
> **VPS:** 72.61.117.18

---

## 1. 개요

이 가이드는 Phoenix v5.3.0 리팩토링 코드를 VPS에 배포하는 절차를 설명합니다.

### 1.1 배포 전략

**권장:** 점진적 마이그레이션
- 기존 코드 유지하면서 새 모듈 추가
- 모듈별로 테스트 후 전환
- 문제 발생 시 즉시 롤백 가능

---

## 2. 사전 준비

### 2.1 로컬 테스트

```bash
# 테스트 실행
cd /path/to/phoenix_v5_run
python tests/run_all_tests.py

# 예상 결과: 모든 테스트 통과
```

### 2.2 파일 준비

다음 파일이 포함된 압축 파일 준비:

```
phoenix_v5_3_0_phase1_2_3_4.tar.gz
├── bot/utils/          # Phase 1
├── bot/core/indicators/ # Phase 2
├── bot/core/ai/        # Phase 3
├── bot/api/            # Phase 4
├── tests/              # Phase 5
└── docs/               # 마이그레이션 가이드
```

---

## 3. 배포 절차

### 3.1 VPS 접속

```bash
ssh root@72.61.117.18
```

### 3.2 봇 중지

```bash
systemctl stop phoenix_v5.service
systemctl status phoenix_v5.service  # 중지 확인
```

### 3.3 백업

```bash
# 반드시 /root에서 실행
cd /root
./backup.sh

# 또는 수동 백업
cd /root
tar -czvf phoenix_backups/phoenix_backup_$(date +%Y%m%d_%H%M%S).tar.gz \
    phoenix_v5_run/

# 백업 확인
ls -la phoenix_backups/
```

### 3.4 파일 업로드

```bash
# 로컬에서 (별도 터미널)
scp phoenix_v5_3_0_phase1_2_3_4.tar.gz root@72.61.117.18:/root/phoenix_v5_run/
```

### 3.5 파일 배치

```bash
cd /root/phoenix_v5_run

# 압축 해제
tar -xzvf phoenix_v5_3_0_phase1_2_3_4.tar.gz

# 파일 확인
ls -la bot/utils/
ls -la bot/core/indicators/
ls -la bot/core/ai/
ls -la bot/api/
```

### 3.6 테스트 실행

```bash
cd /root/phoenix_v5_run

# 가상환경 활성화
source venv/bin/activate

# 테스트 실행
python tests/run_all_tests.py

# 모든 테스트 통과 확인
```

### 3.7 봇 재시작

```bash
systemctl restart phoenix_v5.service
systemctl status phoenix_v5.service
```

### 3.8 로그 모니터링

```bash
# 실시간 로그
journalctl -u phoenix_v5.service -f

# 최근 50줄
journalctl -u phoenix_v5.service -n 50 --no-pager
```

---

## 4. 검증 체크리스트

### 4.1 필수 확인 사항

```
□ 봇 상태 정상 (systemctl status)
□ 텔레그램 /status 응답
□ 텔레그램 /balance 응답
□ 에러 로그 없음
□ 가격 데이터 수신 정상
```

### 4.2 기능 테스트

```
□ /signal SOL 정상 응답
□ /positions 정상 표시
□ /pivot SOL 정상 응답
□ MODE 전환 정상
```

### 4.3 텔레그램 명령어

```bash
# 봇 상태
/status

# 잔고 확인
/balance

# 포지션 확인
/positions

# 신호 분석
/signal SOL

# 피봇 포인트
/pivot SOL
```

---

## 5. 롤백 절차

문제 발생 시 즉시 롤백:

### 5.1 봇 중지

```bash
systemctl stop phoenix_v5.service
```

### 5.2 백업 복원

```bash
cd /root

# 최신 백업 확인
ls -lt phoenix_backups/ | head -5

# 복원
cd /root/phoenix_v5_run
tar -xzvf /root/phoenix_backups/phoenix_backup_YYYYMMDD_HHMMSS.tar.gz --strip-components=1
```

### 5.3 재시작

```bash
systemctl restart phoenix_v5.service
journalctl -u phoenix_v5.service -f
```

---

## 6. 점진적 마이그레이션

### 6.1 Phase별 활성화

각 Phase를 순차적으로 활성화하여 안정성 확인:

**Week 1: Phase 1 (캐시/유틸리티)**
```python
# 기존 코드에서 새 캐시 사용
from bot.utils.cache import price_cache
```

**Week 2: Phase 4 (API 최적화)**
```python
# 기존 bithumb_ccxt_api.py에서 새 모듈 활용
from bot.api import round_qty, round_to_tick
```

**Week 3: Phase 2 (지표 통합)**
```python
# strategy_engine.py, ai_decision.py에서 새 지표 모듈 활용
from bot.core.indicators import calculate_indicators
```

**Week 4: Phase 3 (AI 모듈)**
```python
# ai_decision.py를 새 모듈로 대체
from bot.core.ai import AIDecisionEngine
```

### 6.2 각 Phase 검증

```bash
# Phase 활성화 후
systemctl restart phoenix_v5.service
journalctl -u phoenix_v5.service -f  # 에러 확인

# 24시간 모니터링 후 다음 Phase 진행
```

---

## 7. 성능 모니터링

### 7.1 메모리 사용량

```bash
# 프로세스 메모리
ps aux | grep python | grep main.py

# 시스템 전체
free -h
```

### 7.2 CPU 사용량

```bash
top -p $(pgrep -f "main.py")
```

### 7.3 캐시 상태 확인

텔레그램에서:
```
/status
```

로그에서:
```bash
journalctl -u phoenix_v5.service | grep -i "cache"
```

---

## 8. 트러블슈팅

### 8.1 임포트 오류

```
ModuleNotFoundError: No module named 'bot.utils.cache'
```

**해결:**
```bash
# 파일 존재 확인
ls -la /root/phoenix_v5_run/bot/utils/cache.py

# __init__.py 확인
ls -la /root/phoenix_v5_run/bot/utils/__init__.py
```

### 8.2 순환 참조

```
ImportError: cannot import name 'X' from partially initialized module
```

**해결:**
- 지연 임포트 사용
- 함수 내부에서 임포트

### 8.3 캐시 불일치

```
KeyError: 'balance'
```

**해결:**
```bash
# 캐시 초기화
# 봇 재시작
systemctl restart phoenix_v5.service
```

### 8.4 Rate Limit

```
429 Too Many Requests
```

**해결:**
- 로그에서 Rate Limit 통계 확인
- 갱신 간격 조정

---

## 9. 유지보수

### 9.1 정기 백업

```bash
# crontab에 추가
0 0 * * * /root/backup.sh
```

### 9.2 로그 정리

```bash
# 7일 이상 로그 삭제
journalctl --vacuum-time=7d
```

### 9.3 업데이트 절차

1. 로컬에서 테스트 완료
2. VPS에 파일 업로드
3. 봇 중지 → 백업 → 배치 → 테스트 → 재시작
4. 모니터링 (최소 24시간)

---

## 10. 연락처

문제 발생 시:
1. 로그 확인
2. 롤백 실행
3. 원인 분석
4. 수정 후 재배포

---

*최종 업데이트: 2025-12-04*
*버전: Phoenix v5.3.0*
