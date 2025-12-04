#!/bin/bash
# Phoenix v5.1.0c - 상태 확인

echo "📊 Phoenix v5.1.0c 상태"
echo "================================================"

systemctl status phoenix_v5.service --no-pager

echo ""
echo "================================================"
echo "📁 디스크 사용량:"
du -sh logs/ data/ 2>/dev/null || echo "디렉토리 없음"
