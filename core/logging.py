import logging
import os

def setup_logging():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(name)s | %(levelname)s | %(message)s"
    )
    logging.getLogger("pyrogram").setLevel(logging.ERROR)
