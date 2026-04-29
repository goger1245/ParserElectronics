from __future__ import annotations

import os
import subprocess
import sys

from core.logger import get_logger


logger = get_logger(__name__)

CAMOUFOX_SKIP_FETCH_ENV = "PARSER_SKIP_CAMOUFOX_FETCH"


def ensure_camoufox_browser() -> None:
    if os.getenv(CAMOUFOX_SKIP_FETCH_ENV, "").strip().lower() in {"1", "true", "yes"}:
        return

    try:
        result = subprocess.run(
            [sys.executable, "-m", "camoufox", "version"],
            check=True,
            timeout=30,
            capture_output=True,
            text=True,
        )
        if "Installed" in result.stdout and "Yes" not in result.stdout:
            logger.info("Camoufox package есть, но browser не установлен")
            _fetch_camoufox_browser()
    except Exception:
        logger.info("Camoufox browser не найден, запускаю camoufox fetch")
        _fetch_camoufox_browser()


def _fetch_camoufox_browser() -> None:
    subprocess.run(
        [sys.executable, "-m", "camoufox", "fetch"],
        check=True,
        timeout=1200,
    )

