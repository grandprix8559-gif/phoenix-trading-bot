# -*- coding: utf-8 -*-
"""
Phoenix v5.0.5 — Logger Utility

🔥 v5.0.5 수정사항:
- TimedRotatingFileHandler 적용 (매일 자정 로테이션)
- 30일간 로그 보관 후 자동 삭제
- KST 타임존 적용
"""

import os
import logging
from datetime import datetime
from logging.handlers import TimedRotatingFileHandler

# KST 타임존
try:
    import pytz
    KST = pytz.timezone('Asia/Seoul')
except ImportError:
    KST = None


class KSTFormatter(logging.Formatter):
    """KST 타임존 포맷터"""
    
    def formatTime(self, record, datefmt=None):
        if KST:
            dt = datetime.fromtimestamp(record.created, KST)
        else:
            dt = datetime.fromtimestamp(record.created)
        
        if datefmt:
            return dt.strftime(datefmt)
        return dt.strftime("%Y-%m-%d %H:%M:%S")


def get_logger(name: str) -> logging.Logger:
    """로거 생성 (v5.0.5 로테이션 + KST)"""
    logger = logging.getLogger(name)
    
    if logger.handlers:
        return logger
    
    logger.setLevel(logging.DEBUG)
    
    # 콘솔 핸들러
    console = logging.StreamHandler()
    console.setLevel(logging.INFO)
    console.setFormatter(KSTFormatter(
        "[%(asctime)s] [%(name)s] %(levelname)s: %(message)s",
        datefmt="%H:%M:%S"
    ))
    logger.addHandler(console)
    
    # 파일 핸들러 (로테이션)
    log_dir = os.getenv("LOG_DIR", "logs")
    os.makedirs(log_dir, exist_ok=True)
    
    log_file = os.path.join(log_dir, "phoenix.log")
    
    # TimedRotatingFileHandler: 매일 자정 로테이션, 30일 보관
    file_handler = TimedRotatingFileHandler(
        filename=log_file,
        when="midnight",
        interval=1,
        backupCount=30,  # 최근 30일 보관
        encoding="utf-8"
    )
    file_handler.suffix = "%Y%m%d"  # phoenix.log.20251130 형식
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(KSTFormatter(
        "[%(asctime)s] [%(name)s] %(levelname)s: %(message)s"
    ))
    logger.addHandler(file_handler)
    
    return logger
