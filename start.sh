#!/bin/bash
# Phoenix v5.1.0c - 봇 시작

echo "🚀 Phoenix v5.1.0c 시작..."

if systemctl is-active --quiet phoenix_v5.service; then
    echo "⚠️  이미 실행 중입니다"
    systemctl status phoenix_v5.service --no-pager
else
    sudo systemctl start phoenix_v5.service
    sleep 2
    
    if systemctl is-active --quiet phoenix_v5.service; then
        echo "✅ Phoenix 시작됨"
    else
        echo "❌ 시작 실패 - 로그 확인: ./logs.sh"
    fi
fi
