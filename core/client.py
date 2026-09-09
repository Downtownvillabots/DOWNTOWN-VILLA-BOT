from pyrogram import Client
from core.config import API_ID, API_HASH, BOT_TOKEN, SESSION

class VillaClient(Client):
    """Custom Client for DOWNTOWN VILLA BOT."""
    def __init__(self):
        super().__init__(
            name=SESSION,
            api_id=API_ID,
            api_hash=API_HASH,
            bot_token=BOT_TOKEN,
            workers=50,
            plugins=dict(root="plugins"),
            sleep_threshold=5,
        )

    async def start(self):
        await super().start()
        # Additional startup logic can be added here later
