import logging
import sys
import traceback
from pathlib import Path

def exe_dir() -> Path:
    # Always anchor logs to the folder where the app is started from:
    # - frozen EXE: folder containing the EXE
    # - source run: folder containing main.py (sys.argv[0])
    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        return Path(sys.executable).resolve().parent
    return Path(sys.argv[0]).resolve().parent

def setup_session_logs(app_name: str = "TRX_Cat_control"):
    log_dir = exe_dir() / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)

    actions_path = log_dir / "actions.log"
    errors_path  = log_dir / "error.log"

    # Session-Logs: beim Start löschen
    for p in (actions_path, errors_path):
        try:
            if p.exists():
                p.unlink()
        except Exception:
            pass

    # Logger: actions
    actions_logger = logging.getLogger("actions")
    actions_logger.setLevel(logging.INFO)
    actions_logger.propagate = False
    # avoid duplicate handlers on hot-reload / multiple inits
    actions_logger.handlers.clear()
    ah = logging.FileHandler(actions_path, encoding="utf-8")
    ah.setFormatter(logging.Formatter("%(asctime)s | %(message)s"))
    actions_logger.addHandler(ah)

    # Logger: errors
    errors_logger = logging.getLogger("errors")
    errors_logger.setLevel(logging.ERROR)
    errors_logger.propagate = False
    errors_logger.handlers.clear()
    eh = logging.FileHandler(errors_path, encoding="utf-8")
    eh.setFormatter(logging.Formatter("%(asctime)s | %(levelname)s | %(message)s"))
    errors_logger.addHandler(eh)

    # Global Exception Hook -> in error.log
    def excepthook(exc_type, exc_value, exc_tb):
        tb = "".join(traceback.format_exception(exc_type, exc_value, exc_tb))
        errors_logger.error("UNCAUGHT EXCEPTION\n%s", tb)

    sys.excepthook = excepthook

    return actions_logger, errors_logger, actions_path, errors_path
