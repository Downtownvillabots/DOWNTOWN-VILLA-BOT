\# DOWNTOWN VILLA BOT – Architecture Documentation



\## Project Structure





DOWNTOWN\_VILLA/

├── bot.py # Main entry point – starts bot, loads plugins

├── config.py # Central configuration (all env variables)

├── requirements.txt # Python dependencies

├── logging.conf # Logging configuration file

│

├── core/ # Shared core services

│ ├── init.py

│ ├── permissions.py # Admin/owner/sudo permission helpers

│ ├── helpers.py # Caption rendering, metadata extraction, human\_size

│ ├── logging.py # Central logging setup

│ └── sessions.py # Per-user session management

│

├── database/ # Database layer

│ ├── init.py

│ ├── connection.py # MongoDB connection manager (user DB + media DB pool)

│ ├── users.py # User/group/premium/verification/settings DB functions

│ └── files.py # Media file DB functions (unlimited DB support)

│

├── plugins/ # All feature plugins (auto-loaded by Pyrogram)

│ ├── auto\_filter.py # Search \& auto-filter system

│ ├── indexing.py # File indexing from channels/groups

│ ├── admin\_panel.py # /admin dashboard

│ ├── superbroadcast.py # Multi-channel release distribution

│ ├── premium.py # Premium subscription system

│ ├── verification.py # 3-step verification system

│ ├── broadcast.py # Standard broadcast to users/groups

│ ├── movie\_updates.py # Auto-post new file updates to channel

│ ├── request\_handler.py # User request logging

│ └── misc.py # General commands (start, help, stats, etc.)

│

└── utils/ # (Optional) Additional utility modules

└── init.py







\## Key Concepts



\### 1. Configuration (`config.py`)

\- All environment variables are read here.

\- Feature flags control which plugins are active.

\- Admin permissions (`OWNER\_IDS`, `ADMIN\_IDS`, `SUDO\_IDS`).

\- Channel groups are separated by purpose.

\- Central logging levels and channel IDs.



\### 2. Database Layer

\- \*\*`connection.py`\*\* – Manages connections to the primary user database and unlimited media database pool.

\- \*\*`users.py`\*\* – All user, group, premium, verification, and settings operations.

\- \*\*`files.py`\*\* – All media file operations (save, search, delete) across unlimited databases.

\- Plugins do \*\*not\*\* write raw MongoDB queries; they call these functions.



\### 3. Plugin System

\- Each feature lives in its own file under `plugins/`.

\- Pyrogram auto-loads every `.py` file in `plugins/`.

\- To add a new feature: create `plugins/new\_feature.py`, import from `config`, `core`, and `database` as needed.

\- No changes to `bot.py` or existing plugins are required.



\### 4. Logging

\- Every important function logs its action and any errors.

\- Logs appear in Render console and (if configured) Telegram admin panel logs.

\- `LOG\_LEVEL` controls verbosity.



\### 5. Security

\- Admin checks are centralized in `core/permissions.py`.

\- Callback/command verification is required for admin actions.

\- Sensitive credentials are never exposed in user-facing messages.



\## How to Add a New Feature



1\. Create `plugins/new\_feature.py`.

2\. Import shared services:

&#x20;  ```python

&#x20;  from config import \*

&#x20;  from core.permissions import is\_admin

&#x20;  from core.helpers import render\_caption, human\_size

&#x20;  from database.users import get\_user, add\_user



Register handlers using @Client.on\_message(...) and @Client.on\_callback\_query(...).



Push to GitHub – Render auto-deploys.





bot.py

&#x20; ├── config.py

&#x20; ├── core/logging.py

&#x20; ├── database/connection.py

&#x20; └── plugins/ (auto-loaded)

&#x20;      ├── auto\_filter.py

&#x20;      ├── indexing.py

&#x20;      ├── admin\_panel.py

&#x20;      ├── superbroadcast.py

&#x20;      ├── premium.py

&#x20;      ├── verification.py

&#x20;      ├── broadcast.py

&#x20;      ├── movie\_updates.py

&#x20;      ├── request\_handler.py

&#x20;      └── misc.py





Startup Sequence

bot.py imports config.py and calls validate\_config().



core/logging.py sets up logging.



database/connection.py initializes user DB and media DB pool.



Pyrogram starts and loads all plugins in plugins/.



Bot is ready.



Shutdown

idle() keeps bot running until manually stopped.



On SIGTERM, Pyrogram gracefully shuts down.



/start works in PM

□ /admin opens dashboard

□ Search works in groups and PM

□ Indexing from channel works

□ /superbroadcast shows dashboard and distributes

□ Premium /plan shows plans

□ Verification flow works (if enabled)

□ /broadcast sends to users

□ Movie updates post to channel

