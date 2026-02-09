"""Simple performance monitoring for the Flask app."""

import psutil
import time
import logging
from functools import wraps

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def log_performance(func):
    """Decorator to log function execution time."""
    @wraps(func)
    def wrapper(*args, **kwargs):
        start_time = time.time()
        result = func(*args, **kwargs)
        duration = time.time() - start_time
        if duration > 1.0:  # Log if takes more than 1 second
            logger.warning(f"{func.__name__} took {duration:.2f}s")
        return result
    return wrapper

def get_memory_usage():
    """Get current memory usage in MB."""
    process = psutil.Process()
    return process.memory_info().rss / 1024 / 1024

def log_memory():
    """Log current memory usage."""
    memory_mb = get_memory_usage()
    logger.info(f"Memory usage: {memory_mb:.2f} MB")
    return memory_mb
