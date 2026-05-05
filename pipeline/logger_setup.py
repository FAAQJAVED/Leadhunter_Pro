"""
pipeline.logger_setup — Dual console + rotating file logging.
"""

from __future__ import annotations

import logging
import logging.handlers
import os
from datetime import datetime
from pathlib import Path

from config import LOG_DIR


def setup_logging(level: int = logging.INFO) -> logging.Logger:
    """
    Configure the root 'lead_engine' logger with:
      - Console handler  — INFO+ with colour-coded levels
      - File handler     — DEBUG+ rotating daily file in logs/

    Returns the root engine logger.
    """
    os.makedirs(LOG_DIR, exist_ok=True)

    logger = logging.getLogger('lead_engine')
    logger.setLevel(logging.DEBUG)

    if logger.handlers:
        return logger  # idempotent — already configured

    date_str = datetime.now().strftime('%Y-%m-%d')
    log_path = Path(LOG_DIR) / f'scraper_{date_str}.log'

    file_fmt = logging.Formatter(
        fmt='%(asctime)s | %(levelname)-8s | %(name)-28s | %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S',
    )
    file_handler = logging.handlers.TimedRotatingFileHandler(
        filename=log_path,
        when='midnight',
        backupCount=14,
        encoding='utf-8',
    )
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(file_fmt)
    logger.addHandler(file_handler)

    console_handler = logging.StreamHandler()
    console_handler.setLevel(level)
    console_handler.setFormatter(_ColouredFormatter())
    logger.addHandler(console_handler)

    logger.info("Logging initialised → %s", log_path)
    return logger


_COLOURS = {
    'DEBUG':    '\033[36m',
    'INFO':     '\033[32m',
    'WARNING':  '\033[33m',
    'ERROR':    '\033[31m',
    'CRITICAL': '\033[35m',
}
_RESET = '\033[0m'


class _ColouredFormatter(logging.Formatter):
    _fmt  = '%(asctime)s %(colour)s%(levelname)-8s%(reset)s %(message)s'
    _date = '%H:%M:%S'

    def format(self, record: logging.LogRecord) -> str:
        colour = _COLOURS.get(record.levelname, '')
        record.colour = colour
        record.reset  = _RESET if colour else ''
        formatter = logging.Formatter(self._fmt, datefmt=self._date)
        return formatter.format(record)
