#!/bin/bash
# ============================================================
# Phoenix v5.1.0c 원클릭 설치 스크립트
# ============================================================
# 사용법: chmod +x install.sh && ./install.sh
# ============================================================

set -e

# 색상 정의
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

echo -e "${BLUE}"
echo "============================================================"
echo "  🐦‍🔥 Phoenix v5.1.0c 원클릭 설치"
echo "============================================================"
echo -e "${NC}"

# 현재 디렉토리 확인
INSTALL_DIR=$(pwd)
echo -e "${YELLOW}📁 설치 디렉토리: ${INSTALL_DIR}${NC}"

# 1. Python 버전 확인
echo -e "\n${BLUE}[1/7] Python 버전 확인...${NC}"
if command -v python3 &> /dev/null; then
    PYTHON_VERSION=$(python3 --version 2>&1 | awk '{print $2}')
    PYTHON_MAJOR=$(echo $PYTHON_VERSION | cut -d. -f1)
    PYTHON_MINOR=$(echo $PYTHON_VERSION | cut -d. -f2)
    
    if [ "$PYTHON_MAJOR" -ge 3 ] && [ "$PYTHON_MINOR" -ge 9 ]; then
        echo -e "${GREEN}✅ Python $PYTHON_VERSION 확인됨${NC}"
    else
        echo -e "${RED}❌ Python 3.9 이상 필요 (현재: $PYTHON_VERSION)${NC}"
        exit 1
    fi
else
    echo -e "${RED}❌ Python3가 설치되어 있지 않습니다${NC}"
    echo "Ubuntu: sudo apt install python3 python3-pip python3-venv"
    exit 1
fi

# 2. 가상환경 생성
echo -e "\n${BLUE}[2/7] 가상환경 생성...${NC}"
if [ -d "venv" ]; then
    echo -e "${YELLOW}⚠️  기존 venv 발견 - 삭제 후 재생성${NC}"
    rm -rf venv
fi

python3 -m venv venv
source venv/bin/activate
echo -e "${GREEN}✅ 가상환경 생성 완료${NC}"

# 3. pip 업그레이드 및 의존성 설치
echo -e "\n${BLUE}[3/7] 의존성 설치...${NC}"
pip install --upgrade pip > /dev/null 2>&1
pip install -r requirements.txt
echo -e "${GREEN}✅ 의존성 설치 완료${NC}"

# 4. pytz 추가 설치 (누락된 경우)
pip install pytz > /dev/null 2>&1

# 5. 디렉토리 생성
echo -e "\n${BLUE}[4/7] 디렉토리 구조 생성...${NC}"
mkdir -p data logs data/charts
echo -e "${GREEN}✅ 디렉토리 생성 완료${NC}"

# 6. positions.json 초기화 (없는 경우)
echo -e "\n${BLUE}[5/7] 설정 파일 초기화...${NC}"
if [ ! -f "positions.json" ]; then
    echo '{"positions": {}, "sl_hold_until": {}}' > positions.json
fi

if [ ! -f "data/scalp_positions.json" ]; then
    echo '{"positions": {}, "daily_stats": {}}' > data/scalp_positions.json
fi

if [ ! -f "data/trades.json" ]; then
    echo '[]' > data/trades.json
fi

if [ ! -f "data/daily_summary.json" ]; then
    echo '{}' > data/daily_summary.json
fi

if [ ! -f "data/ai_history.json" ]; then
    echo '[]' > data/ai_history.json
fi

echo -e "${GREEN}✅ 설정 파일 초기화 완료${NC}"

# 7. .env 파일 확인
echo -e "\n${BLUE}[6/7] .env 파일 확인...${NC}"
if [ ! -f ".env" ]; then
    if [ -f ".env.example" ]; then
        cp .env.example .env
        echo -e "${YELLOW}⚠️  .env 파일 생성됨 - API 키를 설정하세요!${NC}"
    else
        echo -e "${RED}⚠️  .env.example 파일이 없습니다${NC}"
    fi
else
    echo -e "${GREEN}✅ .env 파일 존재함${NC}"
fi

# 8. systemd 서비스 등록
echo -e "\n${BLUE}[7/7] systemd 서비스 등록...${NC}"
if [ -f "phoenix_v5.service" ]; then
    # 서비스 파일 내 경로 업데이트
    sed -i "s|WorkingDirectory=.*|WorkingDirectory=${INSTALL_DIR}|g" phoenix_v5.service
    sed -i "s|ExecStart=.*|ExecStart=${INSTALL_DIR}/venv/bin/python main.py|g" phoenix_v5.service
    
    # 서비스 파일 복사
    sudo cp phoenix_v5.service /etc/systemd/system/
    sudo systemctl daemon-reload
    sudo systemctl enable phoenix_v5.service
    echo -e "${GREEN}✅ systemd 서비스 등록 완료${NC}"
else
    echo -e "${YELLOW}⚠️  phoenix_v5.service 파일 없음 - 수동 등록 필요${NC}"
fi

# 스크립트 실행 권한 부여
chmod +x *.sh 2>/dev/null || true

# 완료 메시지
echo -e "\n${GREEN}"
echo "============================================================"
echo "  ✅ Phoenix v5.1.0c 설치 완료!"
echo "============================================================"
echo -e "${NC}"
echo -e "${YELLOW}📝 다음 단계:${NC}"
echo ""
echo "  1. API 키 설정:"
echo "     nano .env"
echo ""
echo "  2. 봇 시작:"
echo "     ./start.sh"
echo ""
echo "  3. 로그 확인:"
echo "     ./logs.sh"
echo ""
echo -e "${BLUE}🔧 사용 가능한 명령어:${NC}"
echo "  ./start.sh   - 봇 시작"
echo "  ./stop.sh    - 봇 중지"
echo "  ./restart.sh - 봇 재시작"
echo "  ./logs.sh    - 실시간 로그"
echo ""
echo -e "${YELLOW}⚠️  반드시 .env 파일에 API 키를 설정하세요!${NC}"
echo ""
