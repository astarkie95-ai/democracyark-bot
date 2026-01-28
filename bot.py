import os
import csv
import time
import traceback
import io
import re
import random
from datetime import datetime, timedelta, timezone
from dataclasses import dataclass
from typing import Dict, Optional, List, Tuple, Set, Any

import discord
from discord import app_commands
from discord.ext import commands, tasks

import aiohttp  # ✅ NEW: Nitrado API calls

from flask import Flask
from threading import Thread

# ✅ PATCH: used for poll edit locks
import asyncio

# ✅ NEW: database (Neon Postgres)
import asyncpg
from urllib.parse import urlparse, urlunparse, parse_qsl, urlencode

# ✅ FIX: proper SSL handling for asyncpg / Neon
import ssl as ssl_lib

# -----------------------
# ENV
# -----------------------
DISCORD_TOKEN = os.getenv("DISCORD_TOKEN", "").strip()
GUILD_ID = os.getenv("GUILD_ID", "").strip()  # optional: faster slash command sync

PINS_CSV_PATH = os.getenv("PINS_CSV_PATH", "pins.csv")         # pool (unclaimed)
CLAIMS_CSV_PATH = os.getenv("CLAIMS_CSV_PATH", "claims.csv")   # state (claimed now)
RESETS_CSV_PATH = os.getenv("RESETS_CSV_PATH", "resets.csv")   # admin reset log

# ✅ NEW: channel locks for slash commands (set these in Railway Variables)
# Copy channel ID in Discord (Developer Mode):
# - CLAIM_CHANNEL_ID = #claim-starter-kit channel ID
# - VOTE_CHANNEL_ID  = #vote channel ID
CLAIM_CHANNEL_ID = os.getenv("CLAIM_CHANNEL_ID", "").strip()
VOTE_CHANNEL_ID = os.getenv("VOTE_CHANNEL_ID", "").strip()
# - WELCOME_CHANNEL_ID = #welcome channel ID
WELCOME_CHANNEL_ID = os.getenv("WELCOME_CHANNEL_ID", "").strip()
WELCOME_MESSAGE_ENV = os.getenv("WELCOME_MESSAGE", "").strip()

# ✅ NEW: ticket system env (set these in Railway Variables)
TICKETS_CATEGORY_ID = os.getenv("TICKETS_CATEGORY_ID", "").strip()
TICKET_PANEL_CHANNEL_ID = os.getenv("TICKET_PANEL_CHANNEL_ID", "").strip()
TICKET_LOG_CHANNEL_ID = os.getenv("TICKET_LOG_CHANNEL_ID", "").strip()
STAFF_ROLE_IDS_ENV = os.getenv("STAFF_ROLE_IDS", "").strip()

TICKET_ONE_OPEN_PER_USER = os.getenv("TICKET_ONE_OPEN_PER_USER", "true").strip().lower() in ("1", "true", "yes", "y", "on")
try:
    TICKET_TRANSCRIPT_MAX_MESSAGES = int(os.getenv("TICKET_TRANSCRIPT_MAX_MESSAGES", "5000").strip() or "5000")
except Exception:
    TICKET_TRANSCRIPT_MAX_MESSAGES = 5000
TICKET_NAME_PREFIX = os.getenv("TICKET_NAME_PREFIX", "ticket").strip() or "ticket"

# ✅ NEW: Neon Postgres connection string (set this in Railway Variables)
# Example: postgresql://user:pass@host/db?sslmode=require
DATABASE_URL = os.getenv("DATABASE_URL", "").strip()

# ✅ NEW: Nitrado restart (Owners-only)
NITRADO_TOKEN = os.getenv("NITRADO_TOKEN", "").strip()
NITRADO_SERVICE_ID = os.getenv("NITRADO_SERVICE_ID", "").strip()  # e.g. 18512293
RESTART_LOG_CHANNEL_ID = os.getenv("RESTART_LOG_CHANNEL_ID", "").strip()

# ✅ NEW: Nitrado live status module + offline/online alerts
SERVER_STATUS_CHANNEL_ID = os.getenv("SERVER_STATUS_CHANNEL_ID", "1465902095327821845").strip()# #server-status channel id
SERVER_STATUS_MESSAGE_ID = os.getenv("SERVER_STATUS_MESSAGE_ID", "").strip()     # message id to keep editing (optional)
SERVER_ANNOUNCE_CHANNEL_ID = os.getenv("SERVER_ANNOUNCE_CHANNEL_ID", "").strip() # (legacy) alerts channel id (optional)
SERVER_ALERTS_CHANNEL_ID = os.getenv("SERVER_ALERTS_CHANNEL_ID", "1465903053461786698").strip()# dedicated alerts channel id (optional)

# ✅ NEW: ping roles (use IDs, not names)
# Default pings: Owner/Admin/Moderator/Members (you can override in Railway)
SERVER_PING_ROLE_IDS = os.getenv(
    "SERVER_PING_ROLE_IDS",
    "1461514415559147725,1461514871396106404,1461515030800629915,1465022269456646336",
).strip()

# Back-compat (optional): single role id or role names (not recommended)
SERVER_PING_ROLE_ID = os.getenv("SERVER_PING_ROLE_ID", "").strip()
SERVER_PING_ROLE_NAMES = os.getenv("SERVER_PING_ROLE_NAMES", "").strip()

# (Optional) Set SERVER_ALERTS_CHANNEL_ID to post status change alerts to a dedicated channel.


# Status poll interval in seconds (default 60)
NITRADO_STATUS_POLL_SECONDS = os.getenv("NITRADO_STATUS_POLL_SECONDS", "60").strip()

# Owners role (ONLY this role can use /restartdemocracy)
# You can override this in Railway by setting OWNERS_ROLE_ID, otherwise it uses your saved ID.
OWNERS_ROLE_ID_ENV = os.getenv("OWNERS_ROLE_ID", "").strip()
OWNERS_ROLE_ID = int(OWNERS_ROLE_ID_ENV) if OWNERS_ROLE_ID_ENV.isdigit() else 1461514415559147725

DEFAULT_WELCOME_MESSAGE = (
    "Welcome to Democracy Ark, {mention}! Please read the rules and treat others with respect."
)
WELCOME_MESSAGE = WELCOME_MESSAGE_ENV or DEFAULT_WELCOME_MESSAGE

# ✅ FIX: show in logs whether Railway actually has DATABASE_URL (flush so Railway shows it immediately)
print("BOOT: bot.py loaded", flush=True)
print("BOOT: DATABASE_URL set =", "YES" if bool(DATABASE_URL) else "NO", flush=True)

if not DISCORD_TOKEN:
    raise RuntimeError("DISCORD_TOKEN missing. Put it in Railway Variables.")

# -----------------------
# Tiny web server (Railway health)
# -----------------------
app = Flask(__name__)

@app.get("/")
def home():
    return "OK", 200

def run_web():
    port = int(os.getenv("PORT", "8080"))
    app.run(host="0.0.0.0", port=port)

Thread(target=run_web, daemon=True).start()

# -----------------------
# Discord bot setup
# -----------------------
intents = discord.Intents.default()
intents.members = True

class DemocracyBot(commands.Bot):
    async def setup_hook(self) -> None:
        # ✅ FIX: ensure DB init runs during startup (before on_ready)
        print("BOOT: setup_hook starting", flush=True)
        try:
            await db_init()
        except Exception:
            print("DB init exception:", traceback.format_exc(), flush=True)

        try:
            await load_state()
            print(
                f"Loaded state: pins={len(PINS_POOL)} claims={len(CLAIMS)} (DB={'yes' if DB_POOL else 'no'})",
                flush=True,
            )
        except Exception:
            print("State load failed:", traceback.format_exc(), flush=True)

        # ✅ Ticket system: register persistent views so buttons/selects work after restarts
        try:
            self.add_view(TicketPanelView())
            self.add_view(TicketControlsView())
            print("TICKETS: persistent views registered", flush=True)
        except Exception:
            print("TICKETS: failed to register views:", traceback.format_exc(), flush=True)

bot = DemocracyBot(command_prefix="!", intents=intents)  # prefix irrelevant, we use slash

# -----------------------
# ✅ NEW: Database globals
# -----------------------
DB_POOL: Optional[asyncpg.Pool] = None
LAST_DB_URL: str = ""

def _normalize_database_url(url: str) -> Tuple[str, bool]:
    """
    Neon often provides ?sslmode=require. asyncpg doesn't accept sslmode in the URL.
    We strip sslmode from the URL and return whether SSL should be enabled.
    """
    if not url:
        return "", False

    raw = url.strip()
    if raw.lower().startswith("psql"):
        raw = raw[len("psql"):].strip()
    if raw and raw[0] in ("'", '"') and raw[-1] == raw[0]:
        raw = raw[1:-1]
    url = raw.strip()

    # ✅ FIX: asyncpg prefers postgresql:// not postgres://
    if url.startswith("postgres://"):
        url = "postgresql://" + url[len("postgres://"):]

    try:
        u = urlparse(url)
        q = dict(parse_qsl(u.query, keep_blank_values=True))

        # Default to SSL unless explicitly disabled.
        ssl_required = True
        sslmode = (q.get("sslmode") or "").lower().strip()
        if sslmode in ("require", "verify-ca", "verify-full"):
            ssl_required = True
        if sslmode in ("disable", "allow", "prefer"):
            ssl_required = False

        # Remove params asyncpg doesn't accept
        if "sslmode" in q:
            q.pop("sslmode", None)
        if "channel_binding" in q:
            q.pop("channel_binding", None)

        new_query = urlencode(q) if q else ""
        new_u = u._replace(query=new_query)
        return urlunparse(new_u), ssl_required
    except Exception:
        # If parsing fails, just return original and let connection attempt decide
        return url, True

def _sanitize_dsn(url: str) -> str:
    if not url:
        return ""
    try:
        u = urlparse(url)
        netloc = u.netloc
        if "@" in netloc:
            auth, host = netloc.split("@", 1)
            if ":" in auth:
                user, _ = auth.split(":", 1)
                auth = f"{user}:***"
            netloc = f"{auth}@{host}"
        return urlunparse(u._replace(netloc=netloc))
    except Exception:
        return "<invalid dsn>"

def _safe_db_info(url: str) -> Tuple[str, str]:
    if not url:
        return "", ""
    try:
        u = urlparse(url)
        host = u.hostname or ""
        dbname = (u.path or "").lstrip("/")
        return host, dbname
    except Exception:
        return "", ""

async def db_init() -> None:
    """
    Create pool + ensure tables exist.
    If DATABASE_URL isn't set, we will fall back to CSV (existing behavior).
    """
    global DB_POOL, LAST_DB_URL

    # ✅ FIX: helps you see if db_init is actually running
    print("DB: init starting…", flush=True)

    if not DATABASE_URL:
        print("DB: DATABASE_URL not set. Using CSV files (non-persistent on some hosts).", flush=True)
        DB_POOL = None
        return

    clean_url, ssl_required = _normalize_database_url(DATABASE_URL)
    LAST_DB_URL = clean_url
    print("DB: normalized scheme =", urlparse(clean_url).scheme, flush=True)
    print("DB: ssl_required =", ssl_required, flush=True)
    print("DB: dsn =", _sanitize_dsn(clean_url), flush=True)

    # ✅ FIX: asyncpg expects an SSL context (more reliable than True/False)
    ssl_ctx = ssl_lib.create_default_context() if ssl_required else None

    try:
        DB_POOL = await asyncpg.create_pool(
            dsn=clean_url,
            ssl=ssl_ctx,
            min_size=1,
            max_size=5,
            command_timeout=30,
            timeout=15,
        )
        print("✅ DB: Connected to Postgres (Neon).", flush=True)

        async with DB_POOL.acquire() as conn:
            # Create tables if they don't exist (starter pins system)
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS pins_pool (
                    box INTEGER PRIMARY KEY,
                    pin TEXT NOT NULL
                );
            """)
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS claims (
                    user_id BIGINT PRIMARY KEY,
                    box INTEGER NOT NULL UNIQUE,
                    pin TEXT NOT NULL,
                    claimed_at BIGINT NOT NULL
                );
            """)
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS resets (
                    reset_at BIGINT NOT NULL,
                    admin_id BIGINT NOT NULL,
                    box INTEGER NOT NULL,
                    user_id BIGINT NOT NULL,
                    pin TEXT NOT NULL,
                    reason TEXT
                );
            """)

            # ✅ NEW: Ticket system tables
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS tickets (
                    id BIGSERIAL PRIMARY KEY
                  , guild_id BIGINT NOT NULL
                  , channel_id BIGINT UNIQUE
                  , owner_id BIGINT NOT NULL
                  , ticket_type TEXT NOT NULL
                  , status TEXT NOT NULL
                  , priority TEXT NOT NULL
                  , assigned_to BIGINT
                  , subject TEXT
                  , details TEXT
                  , created_at BIGINT NOT NULL
                  , updated_at BIGINT NOT NULL
                  , closed_at BIGINT
                );
            """)
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS ticket_events (
                    id BIGSERIAL PRIMARY KEY
                  , ticket_id BIGINT NOT NULL
                  , at BIGINT NOT NULL
                  , actor_id BIGINT NOT NULL
                  , event TEXT NOT NULL
                  , data TEXT
                );
            """)
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS ticket_notes (
                    id BIGSERIAL PRIMARY KEY
                  , ticket_id BIGINT NOT NULL
                  , at BIGINT NOT NULL
                  , author_id BIGINT NOT NULL
                  , note TEXT NOT NULL
                );
            """)
            print("✅ DB: tables ensured.", flush=True)
            print("✅ DB: ticket tables ensured.", flush=True)

    except Exception:
        print(
            "❌ DB: Postgres init failed, falling back to CSV:\n"
            f"{traceback.format_exc()}",
            flush=True,
        )
        DB_POOL = None

async def db_load_pins_pool() -> Dict[int, "BoxPin"]:
    pool: Dict[int, BoxPin] = {}
    if DB_POOL is None:
        return pool
    async with DB_POOL.acquire() as conn:
        rows = await conn.fetch("SELECT box, pin FROM pins_pool;")
        for r in rows:
            try:
                b = int(r["box"])
                p = str(r["pin"]).strip()
                if p:
                    pool[b] = BoxPin(box=b, pin=p)
            except Exception:
                continue
    return pool

async def db_save_pins_pool(pool: Dict[int, "BoxPin"]) -> None:
    if DB_POOL is None:
        return
    async with DB_POOL.acquire() as conn:
        async with conn.transaction():
            await conn.execute("TRUNCATE TABLE pins_pool;")
            for box in sorted(pool.keys()):
                await conn.execute(
                    "INSERT INTO pins_pool (box, pin) VALUES ($1, $2);",
                    int(box),
                    str(pool[box].pin),
                )

async def db_load_claims_state() -> Dict[int, Tuple[int, str]]:
    claims: Dict[int, Tuple[int, str]] = {}
    if DB_POOL is None:
        return claims
    async with DB_POOL.acquire() as conn:
        rows = await conn.fetch("SELECT user_id, box, pin FROM claims;")
        for r in rows:
            try:
                uid = int(r["user_id"])
                box = int(r["box"])
                pin = str(r["pin"]).strip()
                if uid and pin:
                    claims[uid] = (box, pin)
            except Exception:
                continue
    return claims

async def db_save_claims_state(claims: Dict[int, Tuple[int, str]]) -> None:
    if DB_POOL is None:
        return
    now = int(time.time())
    async with DB_POOL.acquire() as conn:
        async with conn.transaction():
            await conn.execute("TRUNCATE TABLE claims;")
            for uid, (box, pin) in sorted(claims.items(), key=lambda x: x[0]):
                await conn.execute(
                    "INSERT INTO claims (user_id, box, pin, claimed_at) VALUES ($1, $2, $3, $4);",
                    int(uid),
                    int(box),
                    str(pin),
                    now,
                )

async def db_append_reset_log(admin_id: int, box: int, user_id: int, pin: str, reason: str = "") -> None:
    if DB_POOL is None:
        return
    async with DB_POOL.acquire() as conn:
        await conn.execute(
            "INSERT INTO resets (reset_at, admin_id, box, user_id, pin, reason) VALUES ($1,$2,$3,$4,$5,$6);",
            int(time.time()),
            int(admin_id),
            int(box),
            int(user_id),
            str(pin),
            str(reason) if reason is not None else "",
        )

# -----------------------
# Data models
# -----------------------
@dataclass
class BoxPin:
    box: int
    pin: str

# In-memory pool: box -> pin (ONLY unclaimed)
PINS_POOL: Dict[int, BoxPin] = {}
# In-memory claims: user_id -> (box, pin)
CLAIMS: Dict[int, Tuple[int, str]] = {}

# -----------------------
# Helpers: permissions
# -----------------------
def is_admin(interaction: discord.Interaction) -> bool:
    if not interaction.guild or not interaction.user:
        return False
    if isinstance(interaction.user, discord.Member):
        p = interaction.user.guild_permissions
        return p.administrator or p.manage_guild or p.manage_channels
    return False

def _parse_id_set(csv_ids: str) -> Set[int]:
    out: Set[int] = set()
    for part in (csv_ids or "").split(","):
        part = part.strip()
        if part.isdigit():
            out.add(int(part))
    return out

# Default staff roles (Owner/Admin/Moderator) — used for /serverpanel if STAFF_ROLE_IDS isn't set
_DEFAULT_STAFF_ROLE_IDS: Set[int] = {1461514415559147725, 1461514871396106404, 1461515030800629915}

STAFF_ROLE_IDS: Set[int] = _parse_id_set(STAFF_ROLE_IDS_ENV) or set(_DEFAULT_STAFF_ROLE_IDS)

def is_staff_member(member: discord.Member) -> bool:
    # Staff if has any configured staff role OR has admin perms
    try:
        if member.guild_permissions.administrator or member.guild_permissions.manage_guild or member.guild_permissions.manage_channels:
            return True
    except Exception:
        pass
    if not STAFF_ROLE_IDS:
        return False
    for r in getattr(member, "roles", []):
        if r and r.id in STAFF_ROLE_IDS:
            return True
    return False


def _parse_id_list(s: str) -> List[int]:
    out: List[int] = []
    for part in (s or "").split(","):
        part = part.strip()
        if not part:
            continue
        if part.isdigit():
            out.append(int(part))
    # de-dupe, preserve order
    seen = set()
    uniq: List[int] = []
    for x in out:
        if x not in seen:
            seen.add(x)
            uniq.append(x)
    return uniq

def _build_server_ping(guild: discord.Guild) -> str:
    """Return a ping string for server alerts (role mentions), or empty string."""
    role_ids: List[int] = _parse_id_list(SERVER_PING_ROLE_IDS)

    # Back-compat: single role id
    if not role_ids and _is_digit_id(SERVER_PING_ROLE_ID):
        role_ids = [int(SERVER_PING_ROLE_ID)]

    mentions: List[str] = []

    # Preferred: role IDs
    for rid in role_ids:
        role = guild.get_role(rid)
        if role:
            mentions.append(role.mention)
        else:
            mentions.append(f"<@&{rid}>")

    # Back-compat: role names (optional)
    if not mentions and SERVER_PING_ROLE_NAMES:
        wanted = {n.strip().lower() for n in SERVER_PING_ROLE_NAMES.split(",") if n.strip()}
        for role in getattr(guild, "roles", []):
            if role and role.name and role.name.strip().lower() in wanted:
                mentions.append(role.mention)

    return (" ".join(mentions) + " ") if mentions else ""
# =====================================================================
# ✅ NEW: Nitrado restart system (Owners-only) - /restartdemocracy
# =====================================================================

_last_restart_at: int = 0
RESTART_COOLDOWN_SECONDS: int = 5 * 60  # 5 minutes

def _is_digit_id(s: str) -> bool:
    return bool(s and s.isdigit())

def is_owner_member(member: discord.Member) -> bool:
    """Owners-only gate for /restartdemocracy."""
    try:
        for r in getattr(member, "roles", []):
            if r and r.id == int(OWNERS_ROLE_ID):
                return True
    except Exception:
        pass
    return False

async def _restart_log(guild: discord.Guild, text: str) -> None:
    if not _is_digit_id(RESTART_LOG_CHANNEL_ID):
        return
    ch = guild.get_channel(int(RESTART_LOG_CHANNEL_ID))
    if isinstance(ch, discord.TextChannel):
        try:
            await ch.send(text)
        except Exception:
            pass

async def nitrado_restart_call() -> Tuple[bool, str]:
    """
    Calls Nitrado API to restart the gameserver.
    Requires:
      - NITRADO_TOKEN
      - NITRADO_SERVICE_ID (numeric)
    """
    if not NITRADO_TOKEN:
        return False, "NITRADO_TOKEN missing in Railway Variables."
    if not _is_digit_id(NITRADO_SERVICE_ID):
        return False, "NITRADO_SERVICE_ID missing/invalid in Railway Variables."

    url = f"https://api.nitrado.net/services/{NITRADO_SERVICE_ID}/gameservers/restart"
    headers = {
        "Authorization": f"Bearer {NITRADO_TOKEN}",
        "Accept": "application/json",
    }

    try:
        async with aiohttp.ClientSession(headers=headers, timeout=aiohttp.ClientTimeout(total=20)) as session:
            async with session.post(url) as resp:
                body = await resp.text()
                if 200 <= resp.status < 300:
                    return True, "Restart request sent to Nitrado."
                return False, f"Nitrado API error {resp.status}: {body[:300]}"
    except Exception as e:
        return False, f"Request failed: {repr(e)}"

async def nitrado_start_call() -> Tuple[bool, str]:
    """
    Calls Nitrado API to start the gameserver.
    Requires:
      - NITRADO_TOKEN
      - NITRADO_SERVICE_ID (numeric)
    """
    if not NITRADO_TOKEN:
        return False, "NITRADO_TOKEN missing in Railway Variables."
    if not _is_digit_id(NITRADO_SERVICE_ID):
        return False, "NITRADO_SERVICE_ID missing/invalid in Railway Variables."

    url = f"https://api.nitrado.net/services/{NITRADO_SERVICE_ID}/gameservers/start"
    headers = {
        "Authorization": f"Bearer {NITRADO_TOKEN}",
        "Accept": "application/json",
    }

    try:
        async with aiohttp.ClientSession(headers=headers, timeout=aiohttp.ClientTimeout(total=20)) as session:
            async with session.post(url) as resp:
                body = await resp.text()
                if 200 <= resp.status < 300:
                    return True, "Start request sent to Nitrado."
                return False, f"Nitrado API error {resp.status}: {body[:300]}"
    except Exception as e:
        return False, f"Request failed: {repr(e)}"


async def nitrado_stop_call() -> Tuple[bool, str]:
    """
    Calls Nitrado API to stop the gameserver.
    Requires:
      - NITRADO_TOKEN
      - NITRADO_SERVICE_ID (numeric)
    """
    if not NITRADO_TOKEN:
        return False, "NITRADO_TOKEN missing in Railway Variables."
    if not _is_digit_id(NITRADO_SERVICE_ID):
        return False, "NITRADO_SERVICE_ID missing/invalid in Railway Variables."

    url = f"https://api.nitrado.net/services/{NITRADO_SERVICE_ID}/gameservers/stop"
    headers = {
        "Authorization": f"Bearer {NITRADO_TOKEN}",
        "Accept": "application/json",
    }

    try:
        async with aiohttp.ClientSession(headers=headers, timeout=aiohttp.ClientTimeout(total=20)) as session:
            async with session.post(url) as resp:
                body = await resp.text()
                if 200 <= resp.status < 300:
                    return True, "Stop request sent to Nitrado."
                return False, f"Nitrado API error {resp.status}: {body[:300]}"
    except Exception as e:
        return False, f"Request failed: {repr(e)}"

class RestartMessageModal(discord.ui.Modal, title="Restart Democracy Ark"):
    restart_message = discord.ui.TextInput(
        label="Restart announcement message",
        style=discord.TextStyle.paragraph,
        required=True,
        max_length=1000,
        placeholder="e.g. Restarting in 2 minutes — please log out safely!",
    )

    def __init__(self, requester_id: int):
        super().__init__()
        self.requester_id = requester_id

    async def on_submit(self, interaction: discord.Interaction):
        # Only the requester can use this modal response flow
        if not interaction.guild or not interaction.user:
            try:
                await interaction.response.send_message("❌ Server context required.", ephemeral=True)
            except Exception:
                pass
            return

        msg = str(self.restart_message.value or "").strip()
        if not msg:
            msg = "Restarting soon — please log out safely!"

        view = RestartConfirmView(requester_id=self.requester_id, announcement=msg)

        # Show a preview + confirm buttons (keeps your safety confirm step)
        try:
            await interaction.response.send_message(
                "⚠️ **Restart Democracy Ark now?**\n"
                "This will reboot the server via Nitrado and kick players.\n\n"
                f"**Announcement preview:**\n> {msg[:800]}\n\n"
                "Press **Confirm restart** to proceed.",
                view=view,
                ephemeral=True,
            )
        except Exception:
            pass


class RestartConfirmView(discord.ui.View):
    def __init__(self, requester_id: int, announcement: str):
        super().__init__(timeout=30)
        self.requester_id = requester_id
        self.announcement = (announcement or "").strip()

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        # Only the person who ran the command can confirm/cancel
        return bool(interaction.user and interaction.user.id == self.requester_id)

    @discord.ui.button(label="Confirm restart", style=discord.ButtonStyle.danger)
    async def confirm(self, interaction: discord.Interaction, _: discord.ui.Button):
        global _last_restart_at, _LAST_MANUAL_RESTART

        now = int(time.time())
        if now - _last_restart_at < RESTART_COOLDOWN_SECONDS:
            wait = RESTART_COOLDOWN_SECONDS - (now - _last_restart_at)
            try:
                await interaction.response.edit_message(content=f"⏳ Cooldown active. Try again in {wait}s.", view=None)
            except Exception:
                pass
            return

        # Defer quickly
        try:
            await interaction.response.defer(ephemeral=True)
        except Exception:
            pass

        # ✅ NEW: Announce restart publicly (optional)
        try:
            if interaction.guild:
                await _announce_restart(interaction.guild, self.announcement, interaction.user)
        except Exception:
            pass

        ok, msg = await nitrado_restart_call()
        if ok:
            _last_restart_at = now

            # record for the status module (so it can show last manual restart)
            if interaction.user:
                _LAST_MANUAL_RESTART = {
                    "at": int(time.time()),
                    "by_id": int(interaction.user.id),
                    "by_name": str(interaction.user),
                    "message": self.announcement,
                }

            try:
                await interaction.followup.send("🔄 **Restart requested.** Nitrado will reboot the server shortly.", ephemeral=True)
            except Exception:
                pass

            if interaction.guild:
                await _restart_log(
                    interaction.guild,
                    f"🔄 Server restart requested by {interaction.user} (`{interaction.user.id}`).",
                )
        else:
            try:
                await interaction.followup.send(f"❌ {msg}", ephemeral=True)
            except Exception:
                pass

    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.secondary)
    async def cancel(self, interaction: discord.Interaction, _: discord.ui.Button):
        try:
            await interaction.response.edit_message(content="Cancelled.", view=None)
        except Exception:
            pass


# =====================================================================
# ✅ NEW: Nitrado Status + Scheduled Warnings (server-status module)
# =====================================================================

_STATUS_TASKS_STARTED: bool = False
_STATUS_LAST_RAW: str = ""
_STATUS_LAST_ANNOUNCE_AT: int = 0
_LAST_MANUAL_RESTART: Optional[Dict[str, Any]] = None
_STATUS_MESSAGE_ID_RUNTIME: int = int(SERVER_STATUS_MESSAGE_ID) if _is_digit_id(SERVER_STATUS_MESSAGE_ID) else 0

def _primary_guild() -> Optional[discord.Guild]:
    if GUILD_ID and GUILD_ID.isdigit():
        return bot.get_guild(int(GUILD_ID))
    if bot.guilds:
        return bot.guilds[0]
    return None

def _status_badge(raw: str) -> str:
    raw = (raw or "").lower().strip()
    if raw in ("started", "running", "online"):
        return "🟢 ONLINE"
    if raw in ("restarting", "starting", "stopping"):
        return "🟠 RESTARTING"
    if raw in ("stopped", "offline"):
        return "🔴 OFFLINE"
    return "⚪ UNKNOWN"

async def _get_text_channel(guild: discord.Guild, channel_id_str: str) -> Optional[discord.TextChannel]:
    if not _is_digit_id(channel_id_str):
        return None
    ch = guild.get_channel(int(channel_id_str))
    if isinstance(ch, discord.TextChannel):
        return ch
    try:
        fetched = await bot.fetch_channel(int(channel_id_str))
        return fetched if isinstance(fetched, discord.TextChannel) else None
    except Exception:
        return None

async def nitrado_status_call() -> Tuple[bool, Dict[str, Any]]:
    """
    Fetch gameserver status via Nitrado API.
    Returns: (ok, payload)
    """
    if not NITRADO_TOKEN or not _is_digit_id(NITRADO_SERVICE_ID):
        return False, {"error": "Nitrado not configured (NITRADO_TOKEN / NITRADO_SERVICE_ID)."}
    url = f"https://api.nitrado.net/services/{NITRADO_SERVICE_ID}/gameservers"
    headers = {"Authorization": f"Bearer {NITRADO_TOKEN}", "Accept": "application/json"}

    try:
        async with aiohttp.ClientSession(headers=headers, timeout=aiohttp.ClientTimeout(total=20)) as session:
            async with session.get(url) as resp:
                data = await resp.json(content_type=None)

        # Nitrado's response nesting can vary; try to be defensive:
        gs = {}
        if isinstance(data, dict):
            gs = (((data.get("data") or {}).get("gameserver")) or ((data.get("data") or {}).get("game_server")) or (data.get("data") or {})) or {}
        query = gs.get("query") if isinstance(gs, dict) else None
        if not isinstance(query, dict):
            query = {}

        status_raw = str(gs.get("status") or "unknown").lower().strip() if isinstance(gs, dict) else "unknown"
        hostname = (gs.get("hostname") if isinstance(gs, dict) else None) or (query.get("hostname") if isinstance(query, dict) else None)
        game = (gs.get("game") if isinstance(gs, dict) else None) or (gs.get("game_short") if isinstance(gs, dict) else None)
        map_name = (gs.get("map") if isinstance(gs, dict) else None) or (query.get("map") if isinstance(query, dict) else None)
        ip = (gs.get("ip") if isinstance(gs, dict) else None) or (query.get("ip") if isinstance(query, dict) else None)
        port = (gs.get("port") if isinstance(gs, dict) else None) or (query.get("port") if isinstance(query, dict) else None)

        players = query.get("player_current") or query.get("players")
        slots = query.get("player_max") or query.get("slots")

        # coerce
        def _to_int(x):
            try:
                return int(x)
            except Exception:
                return None

        payload = {
            "status": status_raw,
            "hostname": str(hostname) if hostname else None,
            "game": str(game) if game else None,
            "map": str(map_name) if map_name else None,
            "ip": str(ip) if ip else None,
            "port": _to_int(port),
            "players": _to_int(players),
            "slots": _to_int(slots),
        }
        return True, payload
    except Exception as e:
        return False, {"error": repr(e)}

def _build_status_embed(payload: Dict[str, Any]) -> discord.Embed:
    badge = _status_badge(str(payload.get("status") or "unknown"))
    now_utc = datetime.utcnow()

    module = (
        "```ansi\n"
        "⟦ DEMOCRACY ARK : LIVE SERVER MODULE ⟧\n"
        f"Status   : {badge}\n"
        f"Host     : {payload.get('hostname') or '—'}\n"
        f"Game     : {payload.get('game') or '—'}\n"
        f"Map      : {payload.get('map') or '—'}\n"
        f"Players  : {(payload.get('players') if payload.get('players') is not None else '—')}/{(payload.get('slots') if payload.get('slots') is not None else '—')}\n"
        f"Address  : {(payload.get('ip') or '—')}{(':' + str(payload.get('port'))) if payload.get('port') else ''}\n"
        f"Checked  : {now_utc.strftime('%Y-%m-%d %H:%M:%SZ')}\n"
        "```"
    )

    e = discord.Embed(
        title="📡 Democracy Bot — Nitrado Server Status",
        description=module,
    )

    if _LAST_MANUAL_RESTART:
        try:
            at = int(_LAST_MANUAL_RESTART.get("at") or 0)
            by_id = int(_LAST_MANUAL_RESTART.get("by_id") or 0)
            msg = str(_LAST_MANUAL_RESTART.get("message") or "")
            when = datetime.fromtimestamp(at, tz=timezone.utc) if at else None
            if when and by_id:
                e.add_field(
                    name="🔁 Last manual restart",
                    value=f"<@{by_id}> — {discord.utils.format_dt(when, style='R')}\n> {msg[:200]}",
                    inline=False,
                )
        except Exception:
            pass

    return e

async def _ensure_status_message(guild: discord.Guild) -> Optional[discord.Message]:
    global _STATUS_MESSAGE_ID_RUNTIME

    ch = await _get_text_channel(guild, SERVER_STATUS_CHANNEL_ID)
    if not ch:
        return None

    if _STATUS_MESSAGE_ID_RUNTIME:
        try:
            return await ch.fetch_message(int(_STATUS_MESSAGE_ID_RUNTIME))
        except Exception:
            pass

    # create new module message
    try:
        msg = await ch.send(embed=discord.Embed(title="📡 Democracy Bot — Starting up…"))
        _STATUS_MESSAGE_ID_RUNTIME = msg.id
        print(f"[NITRADO] New SERVER_STATUS_MESSAGE_ID = {msg.id} (save this in Railway Variables)", flush=True)
        return msg
    except Exception:
        return None

async def _announce_restart(guild: discord.Guild, message: str, requester: Optional[discord.abc.User]) -> None:
    # Announce channel: prefer SERVER_ANNOUNCE_CHANNEL_ID, fallback to SERVER_STATUS_CHANNEL_ID
    announce_id = SERVER_ANNOUNCE_CHANNEL_ID if _is_digit_id(SERVER_ANNOUNCE_CHANNEL_ID) else SERVER_STATUS_CHANNEL_ID
    ch = await _get_text_channel(guild, announce_id)
    if not ch:
        return

    ping = _build_server_ping(guild)

    e = discord.Embed(
        title="🔁 Server Restart",
        description=(message or "Restarting soon — please log out safely!"),
    )
    if requester:
        e.add_field(name="Requested by", value=f"{requester.mention} (`{requester.id}`)", inline=False)
    e.timestamp = datetime.utcnow()

    try:
        await ch.send(content=ping, embed=e)
    except Exception:
        pass

async def _announce_status_change(guild: discord.Guild, old_raw: str, new_raw: str) -> None:
    """Post a human-friendly alert when the server is going offline/online.

    Note: without a known schedule, we can't warn minutes *before* a Nitrado restart —
    we announce as soon as the API reports a transition to stopping/restarting/offline.
    """
    global _STATUS_LAST_ANNOUNCE_AT

    old_state = _status_badge(old_raw)
    new_state = _status_badge(new_raw)

    # Only announce when the badge meaningfully changes
    if old_state == new_state:
        return

    now = int(time.time())
    if now - _STATUS_LAST_ANNOUNCE_AT < 120:
        return  # anti-spam (2 mins)

    # Prefer a dedicated alerts channel if set, otherwise fallback to the status channel
    alerts_id = SERVER_ALERTS_CHANNEL_ID if _is_digit_id(SERVER_ALERTS_CHANNEL_ID) else (
        SERVER_ANNOUNCE_CHANNEL_ID if _is_digit_id(SERVER_ANNOUNCE_CHANNEL_ID) else SERVER_STATUS_CHANNEL_ID
    )
    ch = await _get_text_channel(guild, alerts_id)
    if not ch:
        return

    ping = _build_server_ping(guild)

    # Special messaging for the common cases you care about
    if old_state == "🟢 ONLINE" and new_state in ("🟠 RESTARTING", "🔴 OFFLINE"):
        msg = f"{ping}⚠️ **Server is going offline** ({new_state}). This usually means a Nitrado restart/shutdown has started."
    elif new_state == "🟢 ONLINE" and old_state in ("🟠 RESTARTING", "🔴 OFFLINE"):
        msg = f"{ping}✅ **Server is back online**."
    else:
        msg = f"{ping}Server status changed: **{old_state} → {new_state}**"

    try:
        await ch.send(msg)
        _STATUS_LAST_ANNOUNCE_AT = now
    except Exception:
        pass

@tasks.loop(seconds=60)
async def nitrado_status_loop():
    global _STATUS_LAST_RAW

    # Allow changing interval via env var on next deploy
    guild = _primary_guild()
    if not guild:
        return
    if not _is_digit_id(SERVER_STATUS_CHANNEL_ID):
        return

    ok, payload = await nitrado_status_call()
    if not ok:
        payload = payload or {}
        msg = await _ensure_status_message(guild)
        if msg:
            await msg.edit(
                embed=discord.Embed(
                    title="📡 Democracy Bot — Nitrado Server Status",
                    description=f"```ansi\n⟦ STATUS TEMPORARILY UNAVAILABLE ⟧\nError: {payload.get('error','unknown')}\n```",
                )
            )
        return

    # update status module
    msg = await _ensure_status_message(guild)
    if msg:
        await msg.edit(embed=_build_status_embed(payload))

    new_raw = str(payload.get("status") or "unknown").lower().strip()
    if _STATUS_LAST_RAW and new_raw != _STATUS_LAST_RAW:
        # Announce meaningful transitions
        await _announce_status_change(guild, _STATUS_LAST_RAW, new_raw)
    _STATUS_LAST_RAW = new_raw

@nitrado_status_loop.before_loop
async def _before_nitrado_status_loop():
    await bot.wait_until_ready()

def start_nitrado_status_tasks() -> None:
    global _STATUS_TASKS_STARTED

    if _STATUS_TASKS_STARTED:
        return
    _STATUS_TASKS_STARTED = True

    # Apply dynamic poll interval if set
    try:
        sec = int(NITRADO_STATUS_POLL_SECONDS) if str(NITRADO_STATUS_POLL_SECONDS).isdigit() else 60
    except Exception:
        sec = 60

    # tasks.loop interval is fixed at decoration time; if user changed env, we keep 60 until redeploy.
    # (We still read NITRADO_STATUS_POLL_SECONDS for future code changes; leave simple/stable.)
    try:
        if not nitrado_status_loop.is_running():
            nitrado_status_loop.start()
        print("NITRADO: status task started", flush=True)
    except Exception:
        print("NITRADO: failed to start tasks:", traceback.format_exc(), flush=True)




# -----------------------
# ✅ NEW: Server Control Panel (Start / Stop / Restart + message)
# -----------------------

class ServerActionModal(discord.ui.Modal):
    def __init__(self, requester_id: int, action: str):
        title = {
            "start": "Start Democracy Ark",
            "stop": "Stop Democracy Ark",
            "restart": "Restart Democracy Ark",
        }.get(action, "Server Action")
        super().__init__(title=title)
        self.requester_id = requester_id
        self.action = action

        self.message = discord.ui.TextInput(
            label="Announcement message",
            style=discord.TextStyle.paragraph,
            required=True,
            max_length=1000,
            placeholder="e.g. Restarting now — please log out safely!",
        )
        self.add_item(self.message)

    async def on_submit(self, interaction: discord.Interaction):
        if not interaction.guild or not interaction.user:
            try:
                await interaction.response.send_message("❌ Server context required.", ephemeral=True)
            except Exception:
                pass
            return

        if interaction.user.id != self.requester_id:
            try:
                await interaction.response.send_message("❌ Only the requester can use this form.", ephemeral=True)
            except Exception:
                pass
            return

        msg = str(self.message.value or "").strip()
        if not msg:
            msg = "Server action incoming."

        view = ServerActionConfirmView(requester_id=self.requester_id, action=self.action, announcement=msg)
        try:
            await interaction.response.send_message(
                f"⚠️ **Confirm {self.action.upper()}?**\n\n"
                f"**Announcement preview:**\n> {msg[:800]}",
                ephemeral=True,
                view=view,
            )
        except Exception:
            pass

class ServerActionConfirmView(discord.ui.View):
    def __init__(self, requester_id: int, action: str, announcement: str):
        super().__init__(timeout=30)
        self.requester_id = requester_id
        self.action = action
        self.announcement = (announcement or "").strip()

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        return bool(interaction.user and interaction.user.id == self.requester_id)

    @discord.ui.button(label="Confirm", style=discord.ButtonStyle.danger)
    async def confirm(self, interaction: discord.Interaction, _: discord.ui.Button):
        # Always ACK the interaction quickly, then do work.
        if not interaction.guild or not interaction.user or not isinstance(interaction.user, discord.Member):
            try:
                await interaction.response.edit_message(content="❌ Server context required.", view=None)
            except Exception:
                pass
            return

        if not is_staff_member(interaction.user):
            try:
                await interaction.response.edit_message(content="❌ Staff only.", view=None)
            except Exception:
                pass
            return

        # ✅ ACK immediately to avoid "This interaction failed"
        acked = False
        try:
            await interaction.response.edit_message(
                content=f"⏳ Working on **{self.action.upper()}**…",
                view=None,
            )
            acked = True
        except Exception:
            try:
                await interaction.response.defer(ephemeral=True, thinking=True)
                acked = True
            except Exception:
                acked = False

        if not acked:
            return

        # Announce publicly in server-alerts (or fallback)
        try:
            await _announce_server_action(interaction.guild, self.action, self.announcement, interaction.user)
        except Exception:
            pass

        # Call Nitrado action
        try:
            if self.action == "start":
                ok, msg = await nitrado_start_call()
            elif self.action == "stop":
                ok, msg = await nitrado_stop_call()
            else:
                ok, msg = await nitrado_restart_call()
        except Exception as e:
            ok, msg = False, f"{type(e).__name__}: {e}"

        # Log it (if configured)
        try:
            await _restart_log(
                interaction.guild,
                f"{self.action.upper()} by {interaction.user} ({interaction.user.id}) — {msg}",
            )
        except Exception:
            pass

        # Send final result to the admin (ephemeral)
        try:
            await interaction.followup.send(
                content=("✅ **Action triggered.** " if ok else "❌ **Action failed.** ") + str(msg),
                ephemeral=True,
            )
        except Exception:
            pass

    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.secondary)
    async def cancel(self, interaction: discord.Interaction, _: discord.ui.Button):
        try:
            await interaction.response.edit_message(content="Cancelled.", view=None)
        except Exception:
            pass

class ServerControlView(discord.ui.View):
    def __init__(self, requester_id: int):
        super().__init__(timeout=60)
        self.requester_id = requester_id

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        return bool(interaction.user and interaction.user.id == self.requester_id)

    @discord.ui.button(label="Start", style=discord.ButtonStyle.success)
    async def start_btn(self, interaction: discord.Interaction, _: discord.ui.Button):
        try:
            await interaction.response.send_modal(ServerActionModal(requester_id=self.requester_id, action="start"))
        except Exception as e:
            try:
                await interaction.response.send_message(f"❌ Could not open form: {repr(e)}", ephemeral=True)
            except Exception:
                pass

    @discord.ui.button(label="Stop", style=discord.ButtonStyle.secondary)
    async def stop_btn(self, interaction: discord.Interaction, _: discord.ui.Button):
        try:
            await interaction.response.send_modal(ServerActionModal(requester_id=self.requester_id, action="stop"))
        except Exception as e:
            try:
                await interaction.response.send_message(f"❌ Could not open form: {repr(e)}", ephemeral=True)
            except Exception:
                pass

    @discord.ui.button(label="Restart", style=discord.ButtonStyle.danger)
    async def restart_btn(self, interaction: discord.Interaction, _: discord.ui.Button):
        try:
            await interaction.response.send_modal(ServerActionModal(requester_id=self.requester_id, action="restart"))
        except Exception as e:
            try:
                await interaction.response.send_message(f"❌ Could not open form: {repr(e)}", ephemeral=True)
            except Exception:
                pass

async def _announce_server_action(guild: discord.Guild, action: str, message: str, requester: Optional[discord.Member] = None) -> None:
    # Alerts channel preference: SERVER_ALERTS_CHANNEL_ID -> legacy SERVER_ANNOUNCE_CHANNEL_ID -> status channel
    alerts_id = SERVER_ALERTS_CHANNEL_ID if _is_digit_id(SERVER_ALERTS_CHANNEL_ID) else (
        SERVER_ANNOUNCE_CHANNEL_ID if _is_digit_id(SERVER_ANNOUNCE_CHANNEL_ID) else SERVER_STATUS_CHANNEL_ID
    )
    ch = await _get_text_channel(guild, alerts_id)
    if not ch:
        return

    ping = _build_server_ping(guild)

    title = {
        "start": "🟢 Server Start",
        "stop": "🛑 Server Stop",
        "restart": "🔁 Server Restart",
    }.get(action, "🛠 Server Action")

    e = discord.Embed(
        title=title,
        description=(message or "Server action incoming."),
    )
    if requester:
        e.add_field(name="Requested by", value=f"{requester.mention} (`{requester.id}`)", inline=False)
    e.timestamp = datetime.utcnow()

    try:
        await ch.send(content=ping, embed=e)
    except Exception:
        pass
# -----------------------
# ✅ NEW: Helpers — enforce specific channels for commands
# -----------------------
def _only_in_channel(interaction: discord.Interaction, allowed_channel_id: str) -> bool:
    """
    Returns True if:
      - allowed_channel_id is NOT set (fails open), or
      - interaction is in allowed channel.
    """
    if not interaction.channel:
        return False
    if not allowed_channel_id or not allowed_channel_id.isdigit():
        return True  # If env var missing, don't block (so bot still works)
    return interaction.channel.id == int(allowed_channel_id)

async def _wrong_channel(interaction: discord.Interaction, channel_name: str):
    msg = f"❌ Please use this command in {channel_name}."
    if interaction.response.is_done():
        await interaction.followup.send(msg, ephemeral=True)
    else:
        await interaction.response.send_message(msg, ephemeral=True)

# -----------------------
# ✅ NEW: Helpers — generate NEW unique pin (used by /resetbox)
# -----------------------
def _all_pins_in_use() -> set:
    """Collect all pins currently in pool + currently claimed (to avoid duplicates)."""
    used = set()
    for bp in PINS_POOL.values():
        if bp.pin:
            used.add(str(bp.pin).strip())
    for _, (_, pin) in CLAIMS.items():
        if pin:
            used.add(str(pin).strip())
    return used

def generate_new_pin(length: int = 4, max_tries: int = 10000) -> str:
    """
    Generate a new numeric PIN not currently in use.
    Default is 4 digits (0000-9999). If you ever have lots of boxes, use length=5.
    """
    import random as _random

    used = _all_pins_in_use()

    for _ in range(max_tries):
        pin = "".join(str(_random.randint(0, 9)) for _ in range(length))
        if pin not in used:
            return pin

    # Fallback: time-based (very unlikely to collide; we still try to avoid duplicates)
    pin = str(int(time.time()))[-length:]
    if pin in used:
        pin = str(int(time.time() * 1000))[-length:]
    return pin

# -----------------------
# Helpers: CSV
# -----------------------
def ensure_file_exists(path: str, headers: List[str]) -> None:
    if os.path.exists(path):
        return
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(headers)

def load_pins_pool() -> Dict[int, BoxPin]:
    pool: Dict[int, BoxPin] = {}
    if not os.path.exists(PINS_CSV_PATH):
        return pool
    with open(PINS_CSV_PATH, "r", newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            try:
                box = int(str(row.get("box", "")).strip())
                pin = str(row.get("pin", "")).strip()
                if not pin:
                    continue
                pool[box] = BoxPin(box=box, pin=pin)
            except Exception:
                continue
    return pool

def save_pins_pool(pool: Dict[int, BoxPin]) -> None:
    ensure_file_exists(PINS_CSV_PATH, ["box", "pin"])
    with open(PINS_CSV_PATH, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["box", "pin"])
        for box in sorted(pool.keys()):
            w.writerow([box, pool[box].pin])

def load_claims_state() -> Dict[int, Tuple[int, str]]:
    """
    Load CURRENT claim state (not a forever log).
    claims.csv should represent who currently holds which box.
    """
    ensure_file_exists(CLAIMS_CSV_PATH, ["user_id", "box", "pin", "claimed_at"])
    claims: Dict[int, Tuple[int, str]] = {}
    with open(CLAIMS_CSV_PATH, "r", newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            try:
                uid = int(str(row.get("user_id", "")).strip())
                box = int(str(row.get("box", "")).strip())
                pin = str(row.get("pin", "")).strip()
                if uid and pin:
                    claims[uid] = (box, pin)
            except Exception:
                continue
    return claims

def save_claims_state(claims: Dict[int, Tuple[int, str]]) -> None:
    ensure_file_exists(CLAIMS_CSV_PATH, ["user_id", "box", "pin", "claimed_at"])
    with open(CLAIMS_CSV_PATH, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["user_id", "box", "pin", "claimed_at"])
        now = int(time.time())
        for uid, (box, pin) in sorted(claims.items(), key=lambda x: x[0]):
            w.writerow([uid, box, pin, now])

def append_reset_log(admin_id: int, box: int, user_id: int, pin: str, reason: str = "") -> None:
    ensure_file_exists(RESETS_CSV_PATH, ["reset_at", "admin_id", "box", "user_id", "pin", "reason"])
    with open(RESETS_CSV_PATH, "a", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow([int(time.time()), admin_id, box, user_id, pin, reason])

def pool_counts() -> str:
    return f"Available starter kits: **{len(PINS_POOL)}**"

# -----------------------
# ✅ NEW: persistence wrappers (DB preferred, CSV fallback)
# -----------------------
async def load_state() -> None:
    global PINS_POOL, CLAIMS
    if DB_POOL is not None:
        PINS_POOL = await db_load_pins_pool()
        CLAIMS = await db_load_claims_state()
        return

    # Fallback to CSV
    PINS_POOL = load_pins_pool()
    CLAIMS = load_claims_state()

async def save_pool_state() -> None:
    if DB_POOL is not None:
        await db_save_pins_pool(PINS_POOL)
    else:
        save_pins_pool(PINS_POOL)

async def save_claims_only() -> None:
    if DB_POOL is not None:
        await db_save_claims_state(CLAIMS)
    else:
        save_claims_state(CLAIMS)

async def log_reset(admin_id: int, box: int, user_id: int, pin: str, reason: str = "") -> None:
    if DB_POOL is not None:
        await db_append_reset_log(admin_id, box, user_id, pin, reason)
    else:
        append_reset_log(admin_id, box, user_id, pin, reason)

# -----------------------
# Boot load (CSV fallback will be used until DB is ready)
# -----------------------
PINS_POOL = load_pins_pool()
CLAIMS = load_claims_state()

# -----------------------
# Events
# -----------------------
@bot.event
async def on_ready():
    # ✅ FIX: confirm on_ready is actually firing (flush so Railway shows it)
    print("READY: on_ready fired", flush=True)

    print(f"Logged in as {bot.user} (id: {bot.user.id})", flush=True)

    try:
        if GUILD_ID.isdigit():
            guild = discord.Object(id=int(GUILD_ID))
            bot.tree.copy_global_to(guild=guild)
            synced = await bot.tree.sync(guild=guild)
            print(f"Synced {len(synced)} commands to guild {GUILD_ID}", flush=True)
        else:
            synced = await bot.tree.sync()
            print(f"Synced {len(synced)} global commands", flush=True)
    except Exception as e:
        print("Command sync failed:", repr(e), flush=True)

    # ✅ NEW: start Nitrado status/warn tasks (server-status module)
    try:
        start_nitrado_status_tasks()
    except Exception:
        print("NITRADO: start tasks failed:", traceback.format_exc(), flush=True)

def _render_welcome_message(mention: str) -> str:
    template = (WELCOME_MESSAGE or DEFAULT_WELCOME_MESSAGE).strip()
    if not template:
        template = DEFAULT_WELCOME_MESSAGE
    if "{mention}" in template:
        return template.replace("{mention}", mention)
    return f"{template} {mention}"

@bot.event
async def on_member_join(member: discord.Member):
    if not WELCOME_CHANNEL_ID or not WELCOME_CHANNEL_ID.isdigit():
        return
    if not member.guild:
        return
    channel = member.guild.get_channel(int(WELCOME_CHANNEL_ID))
    if channel is None:
        return
    try:
        # ✅ Keep ONLY the custom/template message (set via /setwelcome)
        await channel.send(_render_welcome_message(member.mention))
    except Exception as e:
        print("Welcome message failed:", repr(e), flush=True)

# -----------------------
# Old names (restored)
# -----------------------
@bot.tree.command(name="ping", description="Check if the bot is alive.")
async def ping(interaction: discord.Interaction):
    await interaction.response.send_message("Pong ✅", ephemeral=True)

# -----------------------
# ✅ Owners-only: restart Nitrado server
# -----------------------
@bot.tree.command(name="restartdemocracy", description="Owners only: restart the Nitrado ASA server.")
async def restartdemocracy(interaction: discord.Interaction):
    if not interaction.guild or not isinstance(interaction.user, discord.Member):
        await interaction.response.send_message("❌ Server context required.", ephemeral=True)
        return

    if not is_owner_member(interaction.user):
        await interaction.response.send_message("❌ Owners only.", ephemeral=True)
        return

    # ✅ NEW: modal popup to set the restart announcement message
    try:
        await interaction.response.send_modal(RestartMessageModal(requester_id=interaction.user.id))
    except Exception as e:
        await interaction.response.send_message(f"❌ Couldn't open the restart form: {repr(e)}", ephemeral=True)


@bot.tree.command(name="serverpanel", description="Staff: Start/Stop/Restart the Nitrado server with an announcement.")
async def serverpanel(interaction: discord.Interaction):
    if not interaction.guild or not isinstance(interaction.user, discord.Member):
        await interaction.response.send_message("❌ Server context required.", ephemeral=True)
        return

    if not is_staff_member(interaction.user):
        await interaction.response.send_message("❌ Staff only (Owner/Admin/Moderator).", ephemeral=True)
        return

    view = ServerControlView(requester_id=interaction.user.id)
    e = discord.Embed(
        title="🛠 Democracy Bot — Server Control Panel",
        description=(
            "Choose an action below. You will be asked for an announcement message, then asked to confirm.\n\n"
            "Actions:\n"
            "• **Start** — boots the server\n"
            "• **Stop** — shuts the server down\n"
            "• **Restart** — restarts the server"
        ),
    )
    try:
        await interaction.response.send_message(embed=e, ephemeral=True, view=view)
    except Exception:
        try:
            await interaction.response.send_message("❌ Could not open panel.", ephemeral=True)
        except Exception:
            pass

# -----------------------
# ✅ Admin: test welcome message
# -----------------------
@bot.tree.command(name="testwelcome", description="Admin: Send a test welcome message in the welcome channel.")
async def testwelcome(interaction: discord.Interaction):
    if not is_admin(interaction):
        await interaction.response.send_message("❌ Admins only.", ephemeral=True)
        return

    if not WELCOME_CHANNEL_ID or not WELCOME_CHANNEL_ID.isdigit():
        await interaction.response.send_message(
            "❌ WELCOME_CHANNEL_ID is not set or invalid.",
            ephemeral=True,
        )
        return

    if not interaction.guild:
        await interaction.response.send_message("❌ Server context required.", ephemeral=True)
        return

    channel = interaction.guild.get_channel(int(WELCOME_CHANNEL_ID))
    if channel is None:
        await interaction.response.send_message(
            "❌ Welcome channel not found. Check WELCOME_CHANNEL_ID.",
            ephemeral=True,
        )
        return

    try:
        # ✅ Keep ONLY the custom/template message (set via /setwelcome)
        await channel.send(_render_welcome_message(interaction.user.mention))
        await interaction.response.send_message("✅ Sent test welcome message.", ephemeral=True)
    except Exception as e:
        await interaction.response.send_message(f"❌ Failed to send welcome message: {repr(e)}", ephemeral=True)

# -----------------------
# ✅ Admin: set welcome message
# -----------------------
@bot.tree.command(name="setwelcome", description="Admin: Set the welcome message template.")
@app_commands.describe(message="Message template. Use {mention} for the user mention.")
async def setwelcome(interaction: discord.Interaction, message: str):
    if not is_admin(interaction):
        await interaction.response.send_message("❌ Admins only.", ephemeral=True)
        return

    new_message = message.strip()
    if not new_message:
        await interaction.response.send_message("❌ Message cannot be empty.", ephemeral=True)
        return

    global WELCOME_MESSAGE
    WELCOME_MESSAGE = new_message
    preview = _render_welcome_message(interaction.user.mention)
    await interaction.response.send_message(
        "✅ Welcome message updated. Preview:\n" + preview,
        ephemeral=True,
    )

# -----------------------
# ✅ FIX: DB status checker (safe, admin only)
# -----------------------
@bot.tree.command(name="dbstatus", description="Admin: Check database connection status.")
async def dbstatus(interaction: discord.Interaction):
    if not is_admin(interaction):
        await interaction.response.send_message("❌ Admins only.", ephemeral=True)
        return

    if DB_POOL is None:
        await interaction.response.send_message("DB: ❌ Not connected (using CSV fallback).", ephemeral=True)
        return

    try:
        async with DB_POOL.acquire() as conn:
            v = await conn.fetchval("SELECT 1;")
            tables = await conn.fetch(
                """
                SELECT table_name
                FROM information_schema.tables
                WHERE table_schema = 'public'
                  AND table_name IN ('pins_pool', 'claims', 'resets', 'tickets', 'ticket_events', 'ticket_notes');
                """
            )
        host, dbname = _safe_db_info(LAST_DB_URL or DATABASE_URL)
        found = {r["table_name"] for r in tables}
        missing = sorted({"pins_pool", "claims", "resets", "tickets", "ticket_events", "ticket_notes"} - found)
        table_line = "all present" if not missing else f"missing: {', '.join(missing)}"
        await interaction.response.send_message(
            "DB: ✅ Connected.\n"
            f"Host: `{host or 'unknown'}`\n"
            f"DB: `{dbname or 'unknown'}`\n"
            f"Tables: {table_line}\n"
            f"SELECT 1: {v}",
            ephemeral=True,
        )
    except Exception:
        await interaction.response.send_message(
            f"DB: ❌ Error:\n{traceback.format_exc()}",
            ephemeral=True,
        )

# -----------------------
# ADMIN: add pins into pool
# -----------------------
@bot.tree.command(name="addpins", description="Admin: Add ONE new starter kit pin into the pool.")
@app_commands.describe(box="Box number (e.g. 5)", pin="PIN code (e.g. 1234)")
async def addpins(interaction: discord.Interaction, box: int, pin: str):
    # ✅ lock starter-kit admin commands to claim channel too
    if not _only_in_channel(interaction, CLAIM_CHANNEL_ID):
        await _wrong_channel(interaction, "#claim-starter-kit")
        return

    if not is_admin(interaction):
        await interaction.response.send_message("❌ Admins only.", ephemeral=True)
        return

    pin = pin.strip()
    if not pin:
        await interaction.response.send_message("❌ Pin cannot be empty.", ephemeral=True)
        return

    if box in PINS_POOL:
        await interaction.response.send_message(
            f"❌ Box #{box} is already in the pool.\nPick another box number.",
            ephemeral=True
        )
        return

    # Block re-adding a box currently claimed
    for uid, (claimed_box, _) in CLAIMS.items():
        if claimed_box == box:
            await interaction.response.send_message(
                f"❌ Box #{box} is currently claimed.\nUse `/resetbox {box}` if you want to put it back.",
                ephemeral=True
            )
            return

    PINS_POOL[box] = BoxPin(box=box, pin=pin)
    await save_pool_state()

    await interaction.response.send_message(
        f"✅ Added starter kit to pool.\n**Box:** #{box}\n**PIN:** `{pin}`\n\n{pool_counts()}",
        ephemeral=True
    )

@bot.tree.command(name="addpinsbulk", description="Admin: Add MANY starter kit pins at once (one per line: box,pin).")
@app_commands.describe(lines="Paste lines like:\n1,1234\n2,5678\n3,9012")
async def addpinsbulk(interaction: discord.Interaction, lines: str):
    # ✅ lock starter-kit admin commands to claim channel too
    if not _only_in_channel(interaction, CLAIM_CHANNEL_ID):
        await _wrong_channel(interaction, "#claim-starter-kit")
        return

    if not is_admin(interaction):
        await interaction.response.send_message("❌ Admins only.", ephemeral=True)
        return

    added = 0
    skipped = 0

    for raw in lines.splitlines():
        raw = raw.strip()
        if not raw:
            continue
        parts = [p.strip() for p in raw.split(",", 1)]
        if len(parts) != 2 or not parts[0].isdigit() or not parts[1]:
            skipped += 1
            continue

        box = int(parts[0])
        pin = parts[1]

        if box in PINS_POOL:
            skipped += 1
            continue

        # don’t allow adding if currently claimed
        claimed = any(claimed_box == box for (claimed_box, _) in CLAIMS.values())
        if claimed:
            skipped += 1
            continue

        PINS_POOL[box] = BoxPin(box=box, pin=pin)
        added += 1

    await save_pool_state()

    await interaction.response.send_message(
        f"✅ Bulk add complete.\nAdded: **{added}** | Skipped: **{skipped}**\n\n{pool_counts()}",
        ephemeral=True
    )

@bot.tree.command(name="poolcount", description="Admin: Show how many starter kits are available.")
async def poolcount(interaction: discord.Interaction):
    # ✅ lock starter-kit admin commands to claim channel too
    if not _only_in_channel(interaction, CLAIM_CHANNEL_ID):
        await _wrong_channel(interaction, "#claim-starter-kit")
        return

    if not is_admin(interaction):
        await interaction.response.send_message("❌ Admins only.", ephemeral=True)
        return
    await interaction.response.send_message(pool_counts(), ephemeral=True)

# -----------------------
# ✅ ADMIN reset ONE box back into the pool
# -----------------------
@bot.tree.command(name="resetbox", description="Admin: Put a claimed box back into the pool (restores its PIN).")
@app_commands.describe(box="Box number to reset (e.g. 1)")
async def resetbox(interaction: discord.Interaction, box: int):
    # ✅ lock starter-kit admin commands to claim channel too
    if not _only_in_channel(interaction, CLAIM_CHANNEL_ID):
        await _wrong_channel(interaction, "#claim-starter-kit")
        return

    if not is_admin(interaction):
        await interaction.response.send_message("❌ Admins only.", ephemeral=True)
        return

    # If already available, nothing to do
    if box in PINS_POOL:
        await interaction.response.send_message(
            f"ℹ️ Box #{box} is already in the pool.\n{pool_counts()}",
            ephemeral=True
        )
        return

    # Find who claimed this box
    claimant_uid: Optional[int] = None
    claimant_pin: Optional[str] = None

    for uid, (claimed_box, pin) in CLAIMS.items():
        if claimed_box == box:
            claimant_uid = uid
            claimant_pin = pin
            break

    if claimant_uid is None or claimant_pin is None:
        await interaction.response.send_message(
            f"❌ I can’t find Box #{box} in current claims or pool.\n"
            f"It may never have been claimed, or your claims file got wiped.",
            ephemeral=True
        )
        return

    # ✅ FIX: Restore to pool with a NEW unique pin (NOT the old one)
    new_pin = generate_new_pin(length=4)
    PINS_POOL[box] = BoxPin(box=box, pin=new_pin)
    await save_pool_state()

    # Remove the claim (so they can claim again)
    CLAIMS.pop(claimant_uid, None)
    await save_claims_only()

    await log_reset(
        admin_id=interaction.user.id,
        box=box,
        user_id=claimant_uid,
        pin=new_pin,
        reason=f"admin resetbox | old_pin={claimant_pin} new_pin={new_pin}",
    )

    await interaction.response.send_message(
        f"✅ Reset complete.\n"
        f"Box **#{box}** has been returned to the pool with a NEW PIN: `{new_pin}`\n"
        f"Previous claimant user id: `{claimant_uid}`\n\n"
        f"{pool_counts()}",
        ephemeral=True
    )

# -----------------------
# Existing resetboxes (kept)
# -----------------------
@bot.tree.command(name="resetboxes", description="Admin: Clear ALL claims (everyone can claim again).")
async def resetboxes(interaction: discord.Interaction):
    # ✅ lock starter-kit admin commands to claim channel too
    if not _only_in_channel(interaction, CLAIM_CHANNEL_ID):
        await _wrong_channel(interaction, "#claim-starter-kit")
        return

    if not is_admin(interaction):
        await interaction.response.send_message("❌ Admins only.", ephemeral=True)
        return

    global CLAIMS
    CLAIMS = {}
    await save_claims_only()

    await interaction.response.send_message(
        "✅ Claims cleared.\n"
        "Note: This does NOT restore pins that were removed from the pool when claimed.\n"
        "If you need to restock, use `/addpins` or `/addpinsbulk`.",
        ephemeral=True
    )

# -----------------------
# PLAYER: claim a starter kit
# -----------------------
@bot.tree.command(name="claimstarter", description="Claim your starter kit PIN + assigned box number (one per person).")
async def claimstarter(interaction: discord.Interaction):
    if not interaction.user:
        return

    # ✅ lock starter-kit player command to claim channel
    if not _only_in_channel(interaction, CLAIM_CHANNEL_ID):
        await _wrong_channel(interaction, "#claim-starter-kit")
        return

    uid = interaction.user.id

    # One per person check
    if uid in CLAIMS:
        box, pin = CLAIMS[uid]
        await interaction.response.send_message(
            f"✅ You already claimed a kit.\n**Your box:** #{box}\n**Your PIN:** `{pin}`",
            ephemeral=True
        )
        return

    if not PINS_POOL:
        await interaction.response.send_message(
            "❌ No starter kits available right now.\nAsk an admin to add more using `/addpins` or `/addpinsbulk`.",
            ephemeral=True
        )
        return

    # Pick lowest box number available
    box = sorted(PINS_POOL.keys())[0]
    bp = PINS_POOL.pop(box)

    # Persist pool change
    await save_pool_state()

    # Record claim in state
    CLAIMS[uid] = (bp.box, bp.pin)
    await save_claims_only()

    await interaction.response.send_message(
        f"🎁 Starter kit claimed!\n"
        f"**Your box:** #{bp.box}\n"
        f"**Your PIN:** `{bp.pin}`\n\n"
        f"Go to the Community Hub and unlock **Box #{bp.box}** with that PIN.\n\n"
        f"{pool_counts()}",
        ephemeral=True
    )

# -----------------------
# POLL (UPDATED: no 1.1 / 2.2, and live public vote counters)
# -----------------------
@dataclass
class PollState:
    message_id: int
    channel_id: int
    question: str
    options: List[str]
    votes: Dict[int, int]  # user_id -> option_index
    ended: bool

POLL_BY_CHANNEL: Dict[int, PollState] = {}

# ✅ PATCH: prevents Discord dropping edits when multiple votes happen fast
POLL_LOCKS: Dict[int, asyncio.Lock] = {}

def _get_poll_lock(channel_id: int) -> asyncio.Lock:
    lock = POLL_LOCKS.get(channel_id)
    if lock is None:
        lock = asyncio.Lock()
        POLL_LOCKS[channel_id] = lock
    return lock

def _poll_counts(poll: PollState) -> List[int]:
    counts = [0] * len(poll.options)
    for idx in poll.votes.values():
        if 0 <= idx < len(counts):
            counts[idx] += 1
    return counts

def poll_embed(poll: PollState) -> discord.Embed:
    counts = _poll_counts(poll)
    total = sum(counts)

    e = discord.Embed(
        title="📊 Poll" + (" (Closed)" if poll.ended else ""),
        description=poll.question,
    )

    # Public, live counts
    lines = []
    for i, opt in enumerate(poll.options):
        lines.append(f"**{i+1}.** {opt} — **{counts[i]}** vote(s)")
    e.add_field(name=f"Options (Total votes: {total})", value="\n".join(lines), inline=False)

    e.set_footer(text="Click a button to vote. Admins: /pollresults /pollend /polldelete")
    return e

class PollView(discord.ui.View):
    def __init__(self, channel_id: int):
        super().__init__(timeout=None)
        self.channel_id = channel_id

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        poll = POLL_BY_CHANNEL.get(self.channel_id)
        if not poll or poll.ended:
            await interaction.response.send_message("This poll is closed.", ephemeral=True)
            return False
        return True

    def build_buttons(self):
        self.clear_items()
        poll = POLL_BY_CHANNEL.get(self.channel_id)
        if not poll:
            return

        counts = _poll_counts(poll)

        for idx in range(len(poll.options)):
            # Button label ONLY numbers + live count (prevents 1.1 / 2.2)
            btn = discord.ui.Button(
                label=f"{idx+1} ({counts[idx]})",
                style=discord.ButtonStyle.primary,
                custom_id=f"poll_vote_{self.channel_id}_{idx}",
            )

            async def callback(interaction: discord.Interaction, option_index=idx):
                poll2 = POLL_BY_CHANNEL.get(self.channel_id)
                if not poll2 or poll2.ended:
                    await interaction.response.send_message("This poll is closed.", ephemeral=True)
                    return

                # ✅ PATCH: acknowledge instantly so Discord doesn't time out the interaction
                try:
                    await interaction.response.defer(ephemeral=True)
                except Exception:
                    pass

                # ✅ PATCH: serialize edits so counts always update
                lock = _get_poll_lock(self.channel_id)
                async with lock:
                    # Save vote (one vote per user; changing vote is allowed)
                    poll2.votes[interaction.user.id] = option_index

                    # ✅ PATCH: ALWAYS edit the real poll message by ID (most reliable)
                    try:
                        channel = bot.get_channel(poll2.channel_id)
                        if channel is None:
                            channel = await bot.fetch_channel(poll2.channel_id)

                        msg = await channel.fetch_message(poll2.message_id)

                        view = PollView(self.channel_id)
                        view.build_buttons()

                        await msg.edit(embed=poll_embed(poll2), view=view)
                    except Exception as e:
                        print("Poll message edit failed:", repr(e))

                # Ephemeral confirmation to the voter
                try:
                    await interaction.followup.send(
                        f"✅ Vote saved: **{poll2.options[option_index]}**",
                        ephemeral=True,
                    )
                except Exception:
                    pass

            btn.callback = callback
            self.add_item(btn)

def poll_results_text(poll: PollState) -> str:
    counts = _poll_counts(poll)
    total = sum(counts)
    out = [f"📊 **Results:** {poll.question}", f"Total votes: **{total}**"]
    for i, opt in enumerate(poll.options):
        out.append(f"**{i+1}. {opt}** — {counts[i]}")
    return "\n".join(out)

@bot.tree.command(name="poll", description="Admin: Create a poll with up to 10 options.")
@app_commands.describe(
    question="The poll question",
    option1="Option 1",
    option2="Option 2",
    option3="Option 3 (optional)",
    option4="Option 4 (optional)",
    option5="Option 5 (optional)",
    option6="Option 6 (optional)",
    option7="Option 7 (optional)",
    option8="Option 8 (optional)",
    option9="Option 9 (optional)",
    option10="Option 10 (optional)",
)
async def poll_create(
    interaction: discord.Interaction,
    question: str,
    option1: str,
    option2: str,
    option3: Optional[str] = None,
    option4: Optional[str] = None,
    option5: Optional[str] = None,
    option6: Optional[str] = None,
    option7: Optional[str] = None,
    option8: Optional[str] = None,
    option9: Optional[str] = None,
    option10: Optional[str] = None,
):
    # ✅ lock poll creation to vote channel
    if not _only_in_channel(interaction, VOTE_CHANNEL_ID):
        await _wrong_channel(interaction, "#vote")
        return

    if not is_admin(interaction):
        await interaction.response.send_message("❌ Admins only.", ephemeral=True)
        return
    if not interaction.channel:
        return

    channel_id = interaction.channel.id
    existing = POLL_BY_CHANNEL.get(channel_id)
    if existing and not existing.ended:
        await interaction.response.send_message(
            "⚠️ There is already an active poll in this channel.\nUse `/pollend` or `/polldelete`.",
            ephemeral=True,
        )
        return

    options = [option1.strip(), option2.strip()]
    for opt in [option3, option4, option5, option6, option7, option8, option9, option10]:
        if opt and opt.strip():
            options.append(opt.strip())

    poll_state = PollState(
        message_id=0,
        channel_id=channel_id,
        question=question.strip(),
        options=options[:10],
        votes={},
        ended=False,
    )
    POLL_BY_CHANNEL[channel_id] = poll_state

    view = PollView(channel_id)
    view.build_buttons()

    await interaction.response.send_message(embed=poll_embed(poll_state), view=view)
    msg = await interaction.original_response()
    poll_state.message_id = msg.id

@bot.tree.command(name="pollresults", description="Admin: Show results for the current poll in this channel.")
async def poll_results(interaction: discord.Interaction):
    # ✅ lock poll admin commands to vote channel
    if not _only_in_channel(interaction, VOTE_CHANNEL_ID):
        await _wrong_channel(interaction, "#vote")
        return

    if not is_admin(interaction):
        await interaction.response.send_message("❌ Admins only.", ephemeral=True)
        return
    if not interaction.channel:
        return
    poll = POLL_BY_CHANNEL.get(interaction.channel.id)
    if not poll:
        await interaction.response.send_message("No poll found in this channel.", ephemeral=True)
        return
    await interaction.response.send_message(poll_results_text(poll), ephemeral=True)

@bot.tree.command(name="pollend", description="Admin: End/lock the current poll.")
async def poll_end(interaction: discord.Interaction):
    # ✅ lock poll admin commands to vote channel
    if not _only_in_channel(interaction, VOTE_CHANNEL_ID):
        await _wrong_channel(interaction, "#vote")
        return

    if not is_admin(interaction):
        await interaction.response.send_message("❌ Admins only.", ephemeral=True)
        return
    if not interaction.channel:
        return
    poll = POLL_BY_CHANNEL.get(interaction.channel.id)
    if not poll:
        await interaction.response.send_message("No poll found in this channel.", ephemeral=True)
        return
    poll.ended = True

    # Try to update the public message to show closed + final counts
    try:
        msg = await interaction.channel.fetch_message(poll.message_id)
        await msg.edit(embed=poll_embed(poll), view=None)
    except Exception:
        pass

    await interaction.response.send_message("✅ Poll ended. Voting is now closed.", ephemeral=True)

@bot.tree.command(name="polldelete", description="Admin: Delete the poll message and remove the poll.")
async def poll_delete(interaction: discord.Interaction):
    # ✅ lock poll admin commands to vote channel
    if not _only_in_channel(interaction, VOTE_CHANNEL_ID):
        await _wrong_channel(interaction, "#vote")
        return

    if not is_admin(interaction):
        await interaction.response.send_message("❌ Admins only.", ephemeral=True)
        return
    if not interaction.channel:
        return

    channel_id = interaction.channel.id
    poll = POLL_BY_CHANNEL.get(channel_id)
    if not poll:
        await interaction.response.send_message("No poll found in this channel.", ephemeral=True)
        return

    try:
        msg = await interaction.channel.fetch_message(poll.message_id)
        await msg.delete()
    except Exception:
        pass

    POLL_BY_CHANNEL.pop(channel_id, None)
    await interaction.response.send_message("🗑️ Poll deleted.", ephemeral=True)

# =====================================================================
# FULL TICKET SYSTEM (DB-backed, channel-based, transcripts, staff tools)
# =====================================================================

TICKET_TYPES = [
    ("support", "Support"),
    ("bug", "Bug"),
    ("report", "Report / Griefing"),
    ("appeal", "Appeal"),
    ("suggestion", "Suggestion"),
]

TICKET_PRIORITIES = ["low", "normal", "high", "urgent"]

def _now() -> int:
    return int(time.time())

def _get_ticket_category(guild: discord.Guild) -> Optional[discord.CategoryChannel]:
    if _is_digit_id(TICKETS_CATEGORY_ID):
        ch = guild.get_channel(int(TICKETS_CATEGORY_ID))
        if isinstance(ch, discord.CategoryChannel):
            return ch
    return None

def _clean_channel_name(raw: str) -> str:
    raw = raw.lower().strip()
    raw = re.sub(r"[^a-z0-9\-]+", "-", raw)
    raw = re.sub(r"-{2,}", "-", raw)
    raw = raw.strip("-")
    if not raw:
        raw = "user"
    return raw[:60]

def _ticket_channel_name(username: str, ticket_id: int) -> str:
    base = _clean_channel_name(username)
    prefix = _clean_channel_name(TICKET_NAME_PREFIX or "ticket")
    name = f"{prefix}-{base}-{ticket_id}"
    return name[:90]

async def _log_ticket_event(guild: discord.Guild, text: str, embed: Optional[discord.Embed] = None) -> None:
    if not _is_digit_id(TICKET_LOG_CHANNEL_ID):
        return
    ch = guild.get_channel(int(TICKET_LOG_CHANNEL_ID))
    if not isinstance(ch, discord.TextChannel):
        return
    try:
        if embed:
            await ch.send(content=text, embed=embed)
        else:
            await ch.send(content=text)
    except Exception:
        pass

async def _db_fetchrow(query: str, *args) -> Optional[asyncpg.Record]:
    if DB_POOL is None:
        return None
    async with DB_POOL.acquire() as conn:
        return await conn.fetchrow(query, *args)

async def _db_fetch(query: str, *args) -> List[asyncpg.Record]:
    if DB_POOL is None:
        return []
    async with DB_POOL.acquire() as conn:
        return await conn.fetch(query, *args)

async def _db_execute(query: str, *args) -> None:
    if DB_POOL is None:
        return
    async with DB_POOL.acquire() as conn:
        await conn.execute(query, *args)

async def _ticket_by_channel(guild_id: int, channel_id: int) -> Optional[asyncpg.Record]:
    return await _db_fetchrow(
        "SELECT * FROM tickets WHERE guild_id=$1 AND channel_id=$2;",
        int(guild_id),
        int(channel_id),
    )

async def _open_ticket_for_user(guild_id: int, user_id: int) -> Optional[asyncpg.Record]:
    return await _db_fetchrow(
        "SELECT * FROM tickets WHERE guild_id=$1 AND owner_id=$2 AND status='open' ORDER BY id DESC LIMIT 1;",
        int(guild_id),
        int(user_id),
    )

async def _append_ticket_event(ticket_id: int, actor_id: int, event: str, data: str = "") -> None:
    await _db_execute(
        "INSERT INTO ticket_events (ticket_id, at, actor_id, event, data) VALUES ($1,$2,$3,$4,$5);",
        int(ticket_id),
        _now(),
        int(actor_id),
        str(event),
        str(data or ""),
    )

def _staff_overwrites(guild: discord.Guild) -> Dict[discord.abc.Snowflake, discord.PermissionOverwrite]:
    overwrites: Dict[discord.abc.Snowflake, discord.PermissionOverwrite] = {}
    overwrites[guild.default_role] = discord.PermissionOverwrite(view_channel=False)

    # Bot
    if guild.me:
        overwrites[guild.me] = discord.PermissionOverwrite(
            view_channel=True,
            send_messages=True,
            read_message_history=True,
            manage_channels=True,
            manage_messages=True,
            attach_files=True,
            embed_links=True,
        )

    # Staff roles
    for role in guild.roles:
        if role and role.id in STAFF_ROLE_IDS:
            overwrites[role] = discord.PermissionOverwrite(
                view_channel=True,
                send_messages=True,
                read_message_history=True,
                manage_messages=True,
                attach_files=True,
                embed_links=True,
            )
    return overwrites

async def _create_ticket_channel(
    guild: discord.Guild,
    owner: discord.Member,
    ticket_id: int,
    ticket_type: str,
) -> discord.TextChannel:
    category = _get_ticket_category(guild)

    overwrites = _staff_overwrites(guild)
    overwrites[owner] = discord.PermissionOverwrite(
        view_channel=True,
        send_messages=True,
        read_message_history=True,
        attach_files=True,
        embed_links=True,
    )

    name = _ticket_channel_name(owner.display_name or owner.name, ticket_id)

    channel = await guild.create_text_channel(
        name=name,
        category=category,
        overwrites=overwrites,
        reason=f"Ticket #{ticket_id} created by {owner} ({owner.id})",
    )
    return channel

async def _ticket_intro_message(channel: discord.TextChannel, owner: discord.Member, ticket_id: int, ticket_type: str, subject: str, details: str):
    pretty_type = dict(TICKET_TYPES).get(ticket_type, ticket_type)
    e = discord.Embed(
        title=f"🎫 Ticket #{ticket_id} — {pretty_type}",
        description="A staff member will respond as soon as possible.",
    )
    e.add_field(name="Owner", value=f"{owner.mention} (`{owner.id}`)", inline=False)
    if subject:
        e.add_field(name="Subject", value=subject[:1024], inline=False)
    if details:
        chunk = details[:1024]
        e.add_field(name="Details", value=chunk, inline=False)
    e.set_footer(text="Staff: use /ticketclaim /ticketclose /tickettranscript /ticketdelete")
    try:
        await channel.send(content=f"{owner.mention} ✅ Ticket created.", embed=e, view=TicketControlsView())
    except Exception:
        pass

class TicketCreateModal(discord.ui.Modal, title="Create a ticket"):
    subject = discord.ui.TextInput(label="Subject", required=False, max_length=120)
    details = discord.ui.TextInput(label="What happened? (details)", style=discord.TextStyle.paragraph, required=False, max_length=1500)

    def __init__(self, ticket_type: str):
        super().__init__()
        self.ticket_type = ticket_type

    async def on_submit(self, interaction: discord.Interaction):
        await create_ticket_flow(interaction, self.ticket_type, str(self.subject.value or "").strip(), str(self.details.value or "").strip())

class TicketTypeSelect(discord.ui.Select):
    def __init__(self):
        options = []
        for key, label in TICKET_TYPES:
            options.append(discord.SelectOption(label=label, value=key))
        super().__init__(
            placeholder="Select a ticket type…",
            options=options,
            min_values=1,
            max_values=1,
            custom_id="ticketpanel_type_select",
        )

    async def callback(self, interaction: discord.Interaction):
        ticket_type = self.values[0]
        try:
            await interaction.response.send_modal(TicketCreateModal(ticket_type=ticket_type))
        except Exception:
            await interaction.response.send_message("❌ Couldn't open the ticket form. Try again.", ephemeral=True)

class TicketPanelView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)
        self.add_item(TicketTypeSelect())

class TicketControlsView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="Transcript", style=discord.ButtonStyle.secondary, custom_id="ticket_ctrl_transcript")
    async def transcript_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await ticket_transcript_action(interaction)

    @discord.ui.button(label="Close", style=discord.ButtonStyle.danger, custom_id="ticket_ctrl_close")
    async def close_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        # Staff only
        if not interaction.guild or not isinstance(interaction.user, discord.Member) or not is_staff_member(interaction.user):
            await interaction.response.send_message("❌ Staff only.", ephemeral=True)
            return
        await ticket_close_action(interaction, reason="closed via button")

async def create_ticket_flow(interaction: discord.Interaction, ticket_type: str, subject: str, details: str) -> None:
    if not interaction.guild or not isinstance(interaction.user, discord.Member):
        try:
            await interaction.response.send_message("❌ Server context required.", ephemeral=True)
        except Exception:
            pass
        return

    guild = interaction.guild
    user = interaction.user

    # Basic config check
    if not (_is_digit_id(TICKETS_CATEGORY_ID) and _is_digit_id(TICKET_LOG_CHANNEL_ID) and _is_digit_id(TICKET_PANEL_CHANNEL_ID)):
        # panel/log/category are needed for the full workflow; still can create channel if category missing
        pass

    if DB_POOL is None:
        await interaction.response.send_message("❌ Ticket system needs the database connected. (DB_POOL is None)", ephemeral=True)
        return

    # One open ticket per user (config)
    if TICKET_ONE_OPEN_PER_USER:
        existing = await _open_ticket_for_user(guild.id, user.id)
        if existing:
            ch_id = int(existing.get("channel_id") or 0)
            if ch_id:
                ch = guild.get_channel(ch_id)
                if isinstance(ch, discord.TextChannel):
                    await interaction.response.send_message(f"⚠️ You already have an open ticket: {ch.mention}", ephemeral=True)
                    return
            await interaction.response.send_message("⚠️ You already have an open ticket.", ephemeral=True)
            return

    # Create DB ticket row first (so we have a ticket ID for naming)
    now = _now()
    row = await _db_fetchrow(
        """
        INSERT INTO tickets (guild_id, channel_id, owner_id, ticket_type, status, priority, assigned_to, subject, details, created_at, updated_at)
        VALUES ($1, $2, $3, $4, 'open', 'normal', NULL, $5, $6, $7, $7)
        RETURNING id;
        """,
        int(guild.id),
        0,  # temp, will update after channel created
        int(user.id),
        str(ticket_type),
        str(subject or ""),
        str(details or ""),
        int(now),
    )
    if not row:
        await interaction.response.send_message("❌ Failed to create ticket in DB.", ephemeral=True)
        return

    ticket_id = int(row["id"])

    try:
        channel = await _create_ticket_channel(guild, user, ticket_id, ticket_type)
    except Exception as e:
        await _db_execute("UPDATE tickets SET status='closed', updated_at=$2 WHERE id=$1;", int(ticket_id), _now())
        await interaction.response.send_message(f"❌ Failed to create ticket channel: {repr(e)}", ephemeral=True)
        return

    await _db_execute(
        "UPDATE tickets SET channel_id=$2, updated_at=$3 WHERE id=$1;",
        int(ticket_id),
        int(channel.id),
        _now(),
    )
    await _append_ticket_event(ticket_id, user.id, "created", f"type={ticket_type}")

    # Acknowledge to user
    try:
        await interaction.response.send_message(f"✅ Ticket created: {channel.mention}", ephemeral=True)
    except Exception:
        pass

    await _ticket_intro_message(channel, user, ticket_id, ticket_type, subject, details)

    # Log
    e = discord.Embed(title=f"🎫 Ticket #{ticket_id} created", description=f"{channel.mention}")
    e.add_field(name="Owner", value=f"{user.mention} (`{user.id}`)", inline=False)
    e.add_field(name="Type", value=str(ticket_type), inline=True)
    if subject:
        e.add_field(name="Subject", value=subject[:1024], inline=False)
    await _log_ticket_event(guild, "", embed=e)

async def _ensure_staff(interaction: discord.Interaction) -> bool:
    if not interaction.guild or not isinstance(interaction.user, discord.Member):
        return False
    return is_staff_member(interaction.user)

async def _get_ticket_or_reply(interaction: discord.Interaction) -> Optional[asyncpg.Record]:
    if not interaction.guild or not interaction.channel:
        return None
    if DB_POOL is None:
        if interaction.response.is_done():
            await interaction.followup.send("❌ Ticket system needs DB connected.", ephemeral=True)
        else:
            await interaction.response.send_message("❌ Ticket system needs DB connected.", ephemeral=True)
        return None
    t = await _ticket_by_channel(interaction.guild.id, interaction.channel.id)
    if not t:
        if interaction.response.is_done():
            await interaction.followup.send("❌ This channel is not a ticket.", ephemeral=True)
        else:
            await interaction.response.send_message("❌ This channel is not a ticket.", ephemeral=True)
        return None
    return t

async def ticket_close_action(interaction: discord.Interaction, reason: str = "") -> None:
    t = await _get_ticket_or_reply(interaction)
    if not t or not interaction.guild or not isinstance(interaction.channel, discord.TextChannel):
        return

    if not await _ensure_staff(interaction):
        if interaction.response.is_done():
            await interaction.followup.send("❌ Staff only.", ephemeral=True)
        else:
            await interaction.response.send_message("❌ Staff only.", ephemeral=True)
        return

    if str(t["status"]) != "open":
        if interaction.response.is_done():
            await interaction.followup.send("ℹ️ Ticket is not open.", ephemeral=True)
        else:
            await interaction.response.send_message("ℹ️ Ticket is not open.", ephemeral=True)
        return

    owner_id = int(t["owner_id"])
    owner = interaction.guild.get_member(owner_id)

    # Lock owner sending
    try:
        if owner:
            ow = interaction.channel.overwrites_for(owner)
            ow.send_messages = False
            ow.add_reactions = False
            await interaction.channel.set_permissions(owner, overwrite=ow, reason="Ticket closed")
    except Exception:
        pass

    await _db_execute(
        "UPDATE tickets SET status='closed', closed_at=$2, updated_at=$2 WHERE id=$1;",
        int(t["id"]),
        _now(),
    )
    await _append_ticket_event(int(t["id"]), interaction.user.id, "closed", reason or "")

    msg = f"🔒 Ticket closed by {interaction.user.mention}."
    if reason:
        msg += f"\n**Reason:** {reason}"

    if interaction.response.is_done():
        await interaction.followup.send(msg)
    else:
        await interaction.response.send_message(msg)

    await _log_ticket_event(interaction.guild, f"🔒 Closed ticket #{t['id']} by {interaction.user} | channel: {interaction.channel.mention}")

async def ticket_reopen_action(interaction: discord.Interaction) -> None:
    t = await _get_ticket_or_reply(interaction)
    if not t or not interaction.guild or not isinstance(interaction.channel, discord.TextChannel):
        return
    if not await _ensure_staff(interaction):
        if interaction.response.is_done():
            await interaction.followup.send("❌ Staff only.", ephemeral=True)
        else:
            await interaction.response.send_message("❌ Staff only.", ephemeral=True)
        return

    if str(t["status"]) != "closed":
        if interaction.response.is_done():
            await interaction.followup.send("ℹ️ Ticket is not closed.", ephemeral=True)
        else:
            await interaction.response.send_message("ℹ️ Ticket is not closed.", ephemeral=True)
        return

    owner_id = int(t["owner_id"])
    owner = interaction.guild.get_member(owner_id)

    # Restore owner sending
    try:
        if owner:
            ow = interaction.channel.overwrites_for(owner)
            ow.send_messages = True
            ow.add_reactions = True
            await interaction.channel.set_permissions(owner, overwrite=ow, reason="Ticket reopened")
    except Exception:
        pass

    await _db_execute(
        "UPDATE tickets SET status='open', closed_at=NULL, updated_at=$2 WHERE id=$1;",
        int(t["id"]),
        _now(),
    )
    await _append_ticket_event(int(t["id"]), interaction.user.id, "reopened", "")

    msg = f"🔓 Ticket reopened by {interaction.user.mention}."
    if interaction.response.is_done():
        await interaction.followup.send(msg)
    else:
        await interaction.response.send_message(msg)

    await _log_ticket_event(interaction.guild, f"🔓 Reopened ticket #{t['id']} by {interaction.user} | channel: {interaction.channel.mention}")

async def ticket_claim_action(interaction: discord.Interaction) -> None:
    t = await _get_ticket_or_reply(interaction)
    if not t or not interaction.guild:
        return
    if not await _ensure_staff(interaction):
        if interaction.response.is_done():
            await interaction.followup.send("❌ Staff only.", ephemeral=True)
        else:
            await interaction.response.send_message("❌ Staff only.", ephemeral=True)
        return

    await _db_execute(
        "UPDATE tickets SET assigned_to=$2, updated_at=$3 WHERE id=$1;",
        int(t["id"]),
        int(interaction.user.id),
        _now(),
    )
    await _append_ticket_event(int(t["id"]), interaction.user.id, "claimed", "")

    msg = f"✅ Ticket claimed by {interaction.user.mention}."
    if interaction.response.is_done():
        await interaction.followup.send(msg)
    else:
        await interaction.response.send_message(msg)

    await _log_ticket_event(interaction.guild, f"✅ Claimed ticket #{t['id']} by {interaction.user} | channel: {interaction.channel.mention}")

async def ticket_priority_action(interaction: discord.Interaction, priority: str) -> None:
    t = await _get_ticket_or_reply(interaction)
    if not t or not interaction.guild:
        return
    if not await _ensure_staff(interaction):
        if interaction.response.is_done():
            await interaction.followup.send("❌ Staff only.", ephemeral=True)
        else:
            await interaction.response.send_message("❌ Staff only.", ephemeral=True)
        return

    p = (priority or "").strip().lower()
    if p not in TICKET_PRIORITIES:
        if interaction.response.is_done():
            await interaction.followup.send(f"❌ Invalid priority. Use: {', '.join(TICKET_PRIORITIES)}", ephemeral=True)
        else:
            await interaction.response.send_message(f"❌ Invalid priority. Use: {', '.join(TICKET_PRIORITIES)}", ephemeral=True)
        return

    await _db_execute(
        "UPDATE tickets SET priority=$2, updated_at=$3 WHERE id=$1;",
        int(t["id"]),
        str(p),
        _now(),
    )
    await _append_ticket_event(int(t["id"]), interaction.user.id, "priority", p)

    msg = f"🏷️ Priority set to **{p}** by {interaction.user.mention}."
    if interaction.response.is_done():
        await interaction.followup.send(msg)
    else:
        await interaction.response.send_message(msg)

async def ticket_add_remove_action(interaction: discord.Interaction, member: discord.Member, add: bool) -> None:
    t = await _get_ticket_or_reply(interaction)
    if not t or not interaction.guild or not isinstance(interaction.channel, discord.TextChannel):
        return
    if not await _ensure_staff(interaction):
        if interaction.response.is_done():
            await interaction.followup.send("❌ Staff only.", ephemeral=True)
        else:
            await interaction.response.send_message("❌ Staff only.", ephemeral=True)
        return

    try:
        ow = interaction.channel.overwrites_for(member)
        ow.view_channel = True if add else False
        ow.send_messages = True if add else False
        ow.read_message_history = True if add else False
        await interaction.channel.set_permissions(member, overwrite=ow, reason="Ticket add/remove user")
    except Exception as e:
        if interaction.response.is_done():
            await interaction.followup.send(f"❌ Failed: {repr(e)}", ephemeral=True)
        else:
            await interaction.response.send_message(f"❌ Failed: {repr(e)}", ephemeral=True)
        return

    event = "added_user" if add else "removed_user"
    await _append_ticket_event(int(t["id"]), interaction.user.id, event, f"user_id={member.id}")

    if interaction.response.is_done():
        await interaction.followup.send(("➕ Added " if add else "➖ Removed ") + member.mention)
    else:
        await interaction.response.send_message(("➕ Added " if add else "➖ Removed ") + member.mention)

async def ticket_note_action(interaction: discord.Interaction, note: str) -> None:
    t = await _get_ticket_or_reply(interaction)
    if not t or not interaction.guild:
        return
    if not await _ensure_staff(interaction):
        if interaction.response.is_done():
            await interaction.followup.send("❌ Staff only.", ephemeral=True)
        else:
            await interaction.response.send_message("❌ Staff only.", ephemeral=True)
        return

    note = (note or "").strip()
    if not note:
        if interaction.response.is_done():
            await interaction.followup.send("❌ Note cannot be empty.", ephemeral=True)
        else:
            await interaction.response.send_message("❌ Note cannot be empty.", ephemeral=True)
        return

    await _db_execute(
        "INSERT INTO ticket_notes (ticket_id, at, author_id, note) VALUES ($1,$2,$3,$4);",
        int(t["id"]),
        _now(),
        int(interaction.user.id),
        str(note),
    )
    await _append_ticket_event(int(t["id"]), interaction.user.id, "note", note[:200])

    if interaction.response.is_done():
        await interaction.followup.send("📝 Note saved (staff-only).", ephemeral=True)
    else:
        await interaction.response.send_message("📝 Note saved (staff-only).", ephemeral=True)

async def ticket_transcript_action(interaction: discord.Interaction) -> None:
    t = await _get_ticket_or_reply(interaction)
    if not t or not interaction.guild or not isinstance(interaction.channel, discord.TextChannel):
        return

    # staff OR owner can transcript
    is_owner = int(t["owner_id"]) == int(interaction.user.id) if interaction.user else False
    is_staff = isinstance(interaction.user, discord.Member) and is_staff_member(interaction.user)
    if not (is_owner or is_staff):
        if interaction.response.is_done():
            await interaction.followup.send("❌ Only the ticket owner or staff can do that.", ephemeral=True)
        else:
            await interaction.response.send_message("❌ Only the ticket owner or staff can do that.", ephemeral=True)
        return

    # Defer so interaction doesn't time out
    try:
        if not interaction.response.is_done():
            await interaction.response.defer(ephemeral=True)
    except Exception:
        pass

    # Fetch messages
    lines: List[str] = []
    count = 0
    try:
        async for msg in interaction.channel.history(limit=TICKET_TRANSCRIPT_MAX_MESSAGES, oldest_first=True):
            ts = msg.created_at.strftime("%Y-%m-%d %H:%M:%S")
            author = f"{msg.author} ({msg.author.id})"
            content = msg.content or ""
            # keep it plain
            content = content.replace("\r", "").replace("\n", "\\n")
            lines.append(f"[{ts}] {author}: {content}")
            count += 1
    except Exception as e:
        await interaction.followup.send(f"❌ Transcript failed: {repr(e)}", ephemeral=True)
        return

    text = "\n".join(lines) if lines else "(no messages)"
    buf = io.BytesIO(text.encode("utf-8", errors="replace"))
    filename = f"ticket-{int(t['id'])}-transcript.txt"
    file = discord.File(buf, filename=filename)

    # Send to log channel
    embed = discord.Embed(title=f"🧾 Transcript for Ticket #{int(t['id'])}", description=f"Channel: {interaction.channel.mention}")
    embed.add_field(name="Messages", value=str(count), inline=True)
    embed.add_field(name="Requested by", value=f"{interaction.user} (`{interaction.user.id}`)" if interaction.user else "Unknown", inline=False)

    await _log_ticket_event(interaction.guild, "", embed=embed)
    if _is_digit_id(TICKET_LOG_CHANNEL_ID):
        logch = interaction.guild.get_channel(int(TICKET_LOG_CHANNEL_ID))
        if isinstance(logch, discord.TextChannel):
            try:
                await logch.send(file=file)
            except Exception:
                pass

    await _append_ticket_event(int(t["id"]), int(interaction.user.id), "transcript", f"messages={count}")

    try:
        await interaction.followup.send("✅ Transcript generated and posted to ticket logs.", ephemeral=True)
    except Exception:
        pass

async def ticket_delete_action(interaction: discord.Interaction, reason: str = "") -> None:
    t = await _get_ticket_or_reply(interaction)
    if not t or not interaction.guild or not isinstance(interaction.channel, discord.TextChannel):
        return
    if not await _ensure_staff(interaction):
        if interaction.response.is_done():
            await interaction.followup.send("❌ Staff only.", ephemeral=True)
        else:
            await interaction.response.send_message("❌ Staff only.", ephemeral=True)
        return

    # Defer, then transcript, then delete
    try:
        if not interaction.response.is_done():
            await interaction.response.defer(ephemeral=True)
    except Exception:
        pass

    # Try transcript first (best-effort)
    try:
        await ticket_transcript_action(interaction)
    except Exception:
        pass

    await _db_execute(
        "UPDATE tickets SET status='deleted', updated_at=$2 WHERE id=$1;",
        int(t["id"]),
        _now(),
    )
    await _append_ticket_event(int(t["id"]), interaction.user.id, "deleted", reason or "")

    await _log_ticket_event(interaction.guild, f"🗑️ Deleted ticket #{t['id']} by {interaction.user} | reason: {reason or 'n/a'}")

    try:
        await interaction.channel.delete(reason=f"Ticket deleted by {interaction.user} | {reason}")
    except Exception as e:
        await interaction.followup.send(f"❌ Could not delete channel: {repr(e)}", ephemeral=True)

# -----------------------
# Ticket panel command (posts the dropdown panel in your panel channel)
# -----------------------
@bot.tree.command(name="ticketpanel", description="Staff: Post the ticket panel (dropdown) in the configured panel channel.")
async def ticketpanel(interaction: discord.Interaction):
    if not interaction.guild or not isinstance(interaction.user, discord.Member):
        await interaction.response.send_message("❌ Server context required.", ephemeral=True)
        return
    if not is_staff_member(interaction.user):
        await interaction.response.send_message("❌ Staff only.", ephemeral=True)
        return
    if not _is_digit_id(TICKET_PANEL_CHANNEL_ID):
        await interaction.response.send_message("❌ TICKET_PANEL_CHANNEL_ID is not set/invalid.", ephemeral=True)
        return

    ch = interaction.guild.get_channel(int(TICKET_PANEL_CHANNEL_ID))
    if not isinstance(ch, discord.TextChannel):
        await interaction.response.send_message("❌ Ticket panel channel not found.", ephemeral=True)
        return

    e = discord.Embed(
        title="🎫 Support Tickets",
        description=(
            "Select a ticket type below to open a private support channel.\n\n"
            "Please include as much detail as you can so staff can help faster."
        ),
    )
    try:
        await ch.send(embed=e, view=TicketPanelView())
        await interaction.response.send_message("✅ Ticket panel posted.", ephemeral=True)
    except Exception as e2:
        await interaction.response.send_message(f"❌ Failed to post panel: {repr(e2)}", ephemeral=True)

# -----------------------
# Ticket staff commands (use inside a ticket channel)
# -----------------------
@bot.tree.command(name="ticketclaim", description="Staff: Claim/assign this ticket to yourself.")
async def ticketclaim(interaction: discord.Interaction):
    await ticket_claim_action(interaction)

@bot.tree.command(name="ticketclose", description="Staff: Close/lock this ticket.")
@app_commands.describe(reason="Optional reason for closing")
async def ticketclose(interaction: discord.Interaction, reason: Optional[str] = None):
    await ticket_close_action(interaction, reason=str(reason or "").strip())

@bot.tree.command(name="ticketreopen", description="Staff: Reopen this ticket.")
async def ticketreopen(interaction: discord.Interaction):
    await ticket_reopen_action(interaction)

@bot.tree.command(name="ticketpriority", description="Staff: Set the ticket priority.")
@app_commands.describe(priority="low | normal | high | urgent")
async def ticketpriority(interaction: discord.Interaction, priority: str):
    await ticket_priority_action(interaction, priority)

@bot.tree.command(name="ticketadd", description="Staff: Add a user to this ticket.")
@app_commands.describe(user="User to add")
async def ticketadd(interaction: discord.Interaction, user: discord.Member):
    await ticket_add_remove_action(interaction, user, add=True)

@bot.tree.command(name="ticketremove", description="Staff: Remove a user from this ticket.")
@app_commands.describe(user="User to remove")
async def ticketremove(interaction: discord.Interaction, user: discord.Member):
    await ticket_add_remove_action(interaction, user, add=False)

@bot.tree.command(name="ticketnote", description="Staff: Save a private note on this ticket (DB).")
@app_commands.describe(note="Staff-only note")
async def ticketnote(interaction: discord.Interaction, note: str):
    await ticket_note_action(interaction, note)

@bot.tree.command(name="tickettranscript", description="Ticket owner or staff: Generate a transcript to ticket logs.")
async def tickettranscript(interaction: discord.Interaction):
    await ticket_transcript_action(interaction)

@bot.tree.command(name="ticketdelete", description="Staff: Transcript + delete this ticket channel.")
@app_commands.describe(reason="Optional reason for deleting")
async def ticketdelete(interaction: discord.Interaction, reason: Optional[str] = None):
    await ticket_delete_action(interaction, reason=str(reason or "").strip())

@bot.tree.command(name="ticketlist", description="Staff: List open tickets (DB).")
async def ticketlist(interaction: discord.Interaction):
    if not interaction.guild or not isinstance(interaction.user, discord.Member):
        await interaction.response.send_message("❌ Server context required.", ephemeral=True)
        return
    if not is_staff_member(interaction.user):
        await interaction.response.send_message("❌ Staff only.", ephemeral=True)
        return
    if DB_POOL is None:
        await interaction.response.send_message("❌ Ticket system needs DB connected.", ephemeral=True)
        return

    rows = await _db_fetch(
        "SELECT id, channel_id, owner_id, ticket_type, priority, status, assigned_to, created_at FROM tickets WHERE guild_id=$1 AND status='open' ORDER BY id DESC LIMIT 25;",
        int(interaction.guild.id),
    )
    if not rows:
        await interaction.response.send_message("✅ No open tickets.", ephemeral=True)
        return

    lines = []
    for r in rows:
        tid = int(r["id"])
        ch_id = int(r["channel_id"] or 0)
        owner_id = int(r["owner_id"])
        ttype = str(r["ticket_type"])
        pr = str(r["priority"])
        assigned = r["assigned_to"]
        assigned_txt = f"assigned `{int(assigned)}`" if assigned else "unassigned"
        ch = interaction.guild.get_channel(ch_id) if ch_id else None
        ch_txt = ch.mention if isinstance(ch, discord.TextChannel) else f"`{ch_id}`"
        lines.append(f"• **#{tid}** {ch_txt} — type `{ttype}` — `{pr}` — {assigned_txt} — owner `{owner_id}`")

    msg = "\n".join(lines)
    await interaction.response.send_message(msg[:1900], ephemeral=True)

# =====================================================================
# END TICKET SYSTEM
# =====================================================================

# -----------------------
# RUN
# -----------------------
bot.run(DISCORD_TOKEN)
