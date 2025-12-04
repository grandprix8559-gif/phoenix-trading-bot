#!/bin/bash
# Phoenix v5.1.0c - 봇 중지

echo "🛑 Phoenix v5.1.0c 중지..."

if systemctl is-active --quiet phoenix_v5.service; then
    sudo systemctl stop phoenix_v5.service
    sleep 2
    echo "✅ Phoenix 중지됨"
else
    echo "⚠️  이미 중지 상태입니다"
fi
