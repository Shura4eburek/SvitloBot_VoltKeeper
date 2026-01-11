import logging
import io
import sys

log_stream = io.StringIO()

def setup_logging():
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(levelname)s - %(message)s',
        handlers=[
            logging.StreamHandler(sys.stdout),
            logging.StreamHandler(log_stream)
        ]
    )

def get_log_stream():
    return log_stream