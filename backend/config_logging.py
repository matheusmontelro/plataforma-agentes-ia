import logging
import logging.handlers
import os
from datetime import datetime

from backend.runtime_settings import LOG_DIR as RUNTIME_LOG_DIR

# Create logs directory if it doesn't exist
LOGS_DIR = str(RUNTIME_LOG_DIR)
os.makedirs(LOGS_DIR, exist_ok=True)

def setup_logging(name, filename):
    """Configure logging with rotation and file output"""
    logger = logging.getLogger(name)
    logger.setLevel(logging.INFO)

    # Create file handler with rotation
    log_file = os.path.join(LOGS_DIR, filename)
    file_handler = logging.handlers.RotatingFileHandler(
        log_file,
        maxBytes=10*1024*1024,  # 10MB
        backupCount=5
    )

    # Create formatter
    formatter = logging.Formatter(
        '%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    file_handler.setFormatter(formatter)

    # Add handler to logger
    logger.addHandler(file_handler)

    # Also add console handler for debugging
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)

    return logger

# Create specific loggers
task_logger = setup_logging('task_system', 'task_system.log')
reminder_logger = setup_logging('task_reminders', 'task_reminders.log')
api_logger = setup_logging('task_api', 'task_api.log')
