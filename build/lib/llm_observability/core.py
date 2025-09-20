import logging
import json
import os

def get_logger(name: str):
    logger = logging.getLogger(name)
    logger.setLevel(logging.INFO)

    log_format = os.environ.get("LOG_FORMAT", "text")
    log_dest = os.environ.get("LOG_DEST", "stderr")

    if log_dest == "stdout":
        handler = logging.StreamHandler()
    else:
        handler = logging.StreamHandler() # default to stderr

    if log_format == "json":
        formatter = JsonFormatter()
    else:
        formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')

    handler.setFormatter(formatter)

    if not logger.handlers:
        logger.addHandler(handler)

    return logger

class JsonFormatter(logging.Formatter):
    def format(self, record):
        log_record = {
            "timestamp": self.formatTime(record, self.datefmt),
            "name": record.name,
            "level": record.levelname,
            "message": record.getMessage(),
        }
        if record.exc_info:
            log_record['exc_info'] = self.formatException(record.exc_info)

        # Add extra fields
        if hasattr(record, 'extra'):
            log_record.update(record.extra)

        return json.dumps(log_record)