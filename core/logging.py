import logging
import logging.config
import os

def setup_logging():
    """Configure logging from logging.conf if present, else basic config."""
    if os.path.exists('logging.conf'):
        logging.config.fileConfig('logging.conf')
    else:
        logging.basicConfig(
            level=logging.INFO,
            format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
        )
    # Set specific library loggers to less verbose
    logging.getLogger("pyrogram").setLevel(logging.ERROR)
    logging.getLogger("aiohttp").setLevel(logging.ERROR)
    logging.getLogger("pymongo").setLevel(logging.WARNING)
    logging.info("Logging configured")
