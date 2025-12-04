#!/bin/bash
# Phoenix v5.1.0c - 봇 재시작

echo "🔄 Phoenix v5.1.0c 재시작..."

sudo systemctl restart phoenix_v5.service
sleep 2

if systemctl is-active --quiet phoenix_v5.service; then
    echo "✅ Phoenix 재시작 완료"
else
    echo "❌ 재시작 실패 - 로그 확인: ./logs.sh"
fi
