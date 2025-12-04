#!/bin/bash
# Phoenix v5.1.0c - 실시간 로그

echo "📋 Phoenix v5.1.0c 로그 (Ctrl+C로 종료)"
echo "================================================"

journalctl -u phoenix_v5.service -f --no-pager -n 100
