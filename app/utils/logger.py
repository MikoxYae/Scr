import logging
import sys

def get_logger(name: str = "scraper_bot") -> logging.Logger:
    logger = logging.getLogger(name)
    if logger.handlers:
        return logger
    logger.setLevel(logging.INFO)
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(logging.Formatter(
        "[%(asctime)s] %(levelname)s — %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S"
    ))
    logger.addHandler(handler)
    return logger

logger = get_logger()
