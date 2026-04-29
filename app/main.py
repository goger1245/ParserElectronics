from __future__ import annotations

import sys
from pathlib import Path

# Запуск как файла (app\main.py) не кладёт корень проекта в sys.path — добавляем вручную.
_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from core.logger import setup_logging
from ui.gui import run_gui


def main() -> None:
    setup_logging()
    run_gui()


if __name__ == "__main__":
    main()
