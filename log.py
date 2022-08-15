import logging
from config import LOG_LEVEL


def get_logger():
    logger = logging.getLogger()
    level = logging.DEBUG
    if LOG_LEVEL == "info":
        level = logging.INFO
    elif LOG_LEVEL == "error":
        level = logging.ERROR

    logger.setLevel(level)
    ch = logging.StreamHandler()
    fh = logging.FileHandler("api.log")
    formatter = logging.Formatter(
        "%(asctime)s - %(module)s - %(funcName)s - line:%(lineno)d - %(levelname)s - %(message)s"
    )

    ch.setFormatter(formatter)
    fh.setFormatter(formatter)
    logger.addHandler(ch)  # 将日志输出至屏幕
    logger.addHandler(fh)  # 将日志输出至文件

    return logger


log = get_logger()
