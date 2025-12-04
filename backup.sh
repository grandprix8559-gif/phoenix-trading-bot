#!/bin/bash
# =========================================================
# Phoenix v5.0 백업 스크립트
# 사용법: ./backup.sh
# =========================================================

# 설정
PHOENIX_DIR="/root/phoenix_v5_run"
BACKUP_DIR="/root/phoenix_backups"
DATE=$(date +%Y%m%d_%H%M%S)
BACKUP_NAME="phoenix_backup_${DATE}"

# 색상
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m' # No Color

echo -e "${GREEN}========================================${NC}"
echo -e "${GREEN}  Phoenix v5.0 백업 시작${NC}"
echo -e "${GREEN}========================================${NC}"
echo ""

# 백업 디렉토리 생성
if [ ! -d "$BACKUP_DIR" ]; then
    mkdir -p "$BACKUP_DIR"
    echo -e "${YELLOW}[INFO]${NC} 백업 폴더 생성: $BACKUP_DIR"
fi

# Phoenix 디렉토리 확인
if [ ! -d "$PHOENIX_DIR" ]; then
    echo -e "${RED}[ERROR]${NC} Phoenix 디렉토리 없음: $PHOENIX_DIR"
    exit 1
fi

# 백업 생성
echo -e "${YELLOW}[1/4]${NC} 압축 중..."
cd /root
tar -czf "${BACKUP_DIR}/${BACKUP_NAME}.tar.gz" \
    --exclude='phoenix_v5_run/venv' \
    --exclude='phoenix_v5_run/logs/*.log' \
    --exclude='phoenix_v5_run/__pycache__' \
    --exclude='phoenix_v5_run/bot/__pycache__' \
    --exclude='phoenix_v5_run/bot/*/__pycache__' \
    phoenix_v5_run/

if [ $? -eq 0 ]; then
    echo -e "${GREEN}[2/4]${NC} 압축 완료: ${BACKUP_NAME}.tar.gz"
else
    echo -e "${RED}[ERROR]${NC} 압축 실패"
    exit 1
fi

# 백업 크기 확인
BACKUP_SIZE=$(du -h "${BACKUP_DIR}/${BACKUP_NAME}.tar.gz" | cut -f1)
echo -e "${GREEN}[3/4]${NC} 백업 크기: ${BACKUP_SIZE}"

# 오래된 백업 정리 (7일 이상)
echo -e "${YELLOW}[4/4]${NC} 오래된 백업 정리 (7일 이상)..."
find "$BACKUP_DIR" -name "phoenix_backup_*.tar.gz" -mtime +7 -delete 2>/dev/null
OLD_COUNT=$(find "$BACKUP_DIR" -name "phoenix_backup_*.tar.gz" | wc -l)
echo -e "${GREEN}[INFO]${NC} 현재 백업 파일: ${OLD_COUNT}개"

# 완료
echo ""
echo -e "${GREEN}========================================${NC}"
echo -e "${GREEN}  백업 완료!${NC}"
echo -e "${GREEN}========================================${NC}"
echo -e "파일: ${BACKUP_DIR}/${BACKUP_NAME}.tar.gz"
echo -e "크기: ${BACKUP_SIZE}"
echo ""

# 백업 목록 표시
echo -e "${YELLOW}[백업 목록]${NC}"
ls -lh "$BACKUP_DIR"/*.tar.gz 2>/dev/null | tail -5
