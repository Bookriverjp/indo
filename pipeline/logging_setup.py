import logging
import sys
from pathlib import Path

LOGGER_NAME = "daibutsuame"
_FORMAT = "%(asctime)s %(levelname)s %(message)s"


def setup_logging(log_file: Path) -> logging.Logger:
    """画面と episodes/<id>/logs/pipeline.log の両方へ出すロガーを返す。"""
    logger = logging.getLogger(LOGGER_NAME)
    logger.setLevel(logging.INFO)
    logger.propagate = False
    close_logging(logger)

    log_file.parent.mkdir(parents=True, exist_ok=True)
    file_handler = logging.FileHandler(log_file, encoding="utf-8")
    file_handler.setFormatter(logging.Formatter(_FORMAT))
    console = logging.StreamHandler(sys.stdout)
    console.setFormatter(logging.Formatter("%(message)s"))
    logger.addHandler(file_handler)
    logger.addHandler(console)
    return logger


def close_logging(logger: logging.Logger) -> None:
    """ハンドラを外して閉じる。Windowsでログファイルがロックされたままにならないようにする。"""
    for handler in list(logger.handlers):
        logger.removeHandler(handler)
        handler.close()
