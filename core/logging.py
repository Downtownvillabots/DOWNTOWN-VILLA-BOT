import logging
import logging.config
import os

def setup_logging():
    config_path = os.path.join(os.path.dirname(__file__), '..', 'logging.conf')
    if os.path.exists(config_path):
        logging.config.fileConfig(config_path)
    else:
        logging.basicConfig(level=logging.INFO)
    logging.getLogger("pyrogram").setLevel(logging.ERROR)