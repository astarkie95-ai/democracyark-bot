import os
import csv
import time
import traceback
import io
import re
import random
import math
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

CLAIMED_USERS_CSV_PATH = os.getenv("CLAIMED_USERS_CSV_PATH", "claimed_users.csv")
RESETS_CSV_PATH = os.getenv("RESETS_CSV_PATH", "resets.csv")   # admin reset log

# ✅ NEW: channel locks for slash commands (set these in Railway Variables)
# Copy channel ID in Discord (Developer Mode):
# - CLAIM_CHANNEL_ID = #claim-starter-kit channel ID
# - VOTE_CHANNEL_ID  = #vote channel ID
CLAIM_CHANNEL_ID = os.getenv("CLAIM_CHANNEL_ID", "").strip()

# Starter vault admin panel (optional)
STARTER_ADMIN_CHANNEL_ID = os.getenv("STARTER_ADMIN_CHANNEL_ID", "").strip()
STARTER_ADMIN_MESSAGE_ID = os.getenv("STARTER_ADMIN_MESSAGE_ID", "").strip()
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
# ✅ NEW: Persistent server control panel (admin-only channel)
SERVER_CONTROL_CHANNEL_ID = os.getenv("SERVER_CONTROL_CHANNEL_ID", "").strip()   # channel id for 24/7 panel (e.g. #restart-server)
SERVER_CONTROL_MESSAGE_ID = os.getenv("SERVER_CONTROL_MESSAGE_ID", "").strip()   # message id to keep editing (optional)
SERVER_CONTROL_PIN = os.getenv("SERVER_CONTROL_PIN", "0").strip().lower() in ("1","true","yes","on")

# ✅ NEW: Starter Kit module panel (no commands needed for players)
# If *_CHANNEL_ID is blank, defaults to CLAIM_CHANNEL_ID.
STARTER_PANEL_CHANNEL_ID = os.getenv("STARTER_PANEL_CHANNEL_ID", "").strip()
STARTER_PANEL_MESSAGE_ID = os.getenv("STARTER_PANEL_MESSAGE_ID", "").strip()
STARTER_PANEL_PIN = os.getenv("STARTER_PANEL_PIN", "1").strip().lower() in ("1","true","yes","on")

# ✅ NEW: Poll module panel (no commands needed for players)
# If *_CHANNEL_ID is blank, defaults to VOTE_CHANNEL_ID.
POLL_PANEL_CHANNEL_ID = os.getenv("POLL_PANEL_CHANNEL_ID", "").strip()
POLL_PANEL_MESSAGE_ID = os.getenv("POLL_PANEL_MESSAGE_ID", "").strip()
POLL_PANEL_PIN = os.getenv("POLL_PANEL_PIN", "1").strip().lower() in ("1","true","yes","on")




# ✅ NEW: Role panels (Visitor -> Survivor + optional self-assign roles)
# - GET_ROLE_CHANNEL_ID: channel where the public role panel lives (e.g. #get-role)
# - GET_ROLE_MESSAGE_ID: message id to keep editing (optional)
# - SURVIVOR_ROLE_ID: role id for "Survivor"
# - ROLE_MANAGER_CHANNEL_ID: staff channel for role manager module (optional; default SERVER_CONTROL_CHANNEL_ID)
# - ROLE_MANAGER_MESSAGE_ID: message id to keep editing (optional)
# - SELF_ROLES_CSV_PATH: CSV fallback for self-assign roles list (if DB is unavailable)
GET_ROLE_CHANNEL_ID = os.getenv("GET_ROLE_CHANNEL_ID", "").strip()
GET_ROLE_MESSAGE_ID = os.getenv("GET_ROLE_MESSAGE_ID", "").strip()
SURVIVOR_ROLE_ID = os.getenv("SURVIVOR_ROLE_ID", "").strip()

ROLE_MANAGER_CHANNEL_ID = os.getenv("ROLE_MANAGER_CHANNEL_ID", "").strip()
ROLE_MANAGER_MESSAGE_ID = os.getenv("ROLE_MANAGER_MESSAGE_ID", "").strip()
ROLE_MANAGER_PIN = os.getenv("ROLE_MANAGER_PIN", "0").strip().lower() in ("1","true","yes","on")

SELF_ROLES_CSV_PATH = os.getenv("SELF_ROLES_CSV_PATH", "self_roles.csv").strip()
# ✅ NEW: Tame Calculator modules
# - TAME_CALC_CHANNEL_ID: public channel where the calculator panel lives (e.g. #tame-calculator)
# - TAME_CALC_MESSAGE_ID: message id to keep editing (optional)
# - CALC_SETTINGS_CHANNEL_ID: staff channel for calculator settings (e.g. #calc-settings)
# - CALC_SETTINGS_MESSAGE_ID: message id to keep editing (optional)
# If channel IDs are not set, the bot will try to find channels by name ("tame-calculator" / "calc-settings") within your guild.
TAME_CALC_CHANNEL_ID = os.getenv("TAME_CALC_CHANNEL_ID", "").strip()
TAME_CALC_MESSAGE_ID = os.getenv("TAME_CALC_MESSAGE_ID", "").strip()
CALC_SETTINGS_CHANNEL_ID = os.getenv("CALC_SETTINGS_CHANNEL_ID", "").strip()
CALC_SETTINGS_MESSAGE_ID = os.getenv("CALC_SETTINGS_MESSAGE_ID", "").strip()

# ✅ NEW: Poll module channels split (optional)
# - POLL_CREATE_CHANNEL_ID: where the Poll PANEL lives (private staff channel, e.g. #create-poll)
# - POLL_VOTE_CHANNEL_ID  : where polls are posted for players to vote (public, e.g. #vote)
POLL_CREATE_CHANNEL_ID = os.getenv("POLL_CREATE_CHANNEL_ID", "").strip()
POLL_VOTE_CHANNEL_ID = os.getenv("POLL_VOTE_CHANNEL_ID", "").strip()
# ✅ NEW: ping roles (use IDs, not names)
# Default pings: Owner/Admin/Moderator/Members (you can override in Railway)
SERVER_PING_ROLE_IDS = os.getenv(
    "SERVER_PING_ROLE_IDS",
    "1461514415559147725,1461514871396106404,1461515030800629915,1465022269456646336",
).strip()


# ✅ NEW: ping mode
# If SERVER_PING_EVERYONE is truthy, alerts will use @everyone (restricted to channel visibility).
SERVER_PING_EVERYONE = os.getenv("SERVER_PING_EVERYONE", "0").strip().lower() in ("1","true","yes","on")

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
# ✅ Poll system core (restored)
# -----------------------
# NOTE: Several poll features in this bot (poll panel buttons + /poll commands) rely on these
# core classes/helpers. If these are missing, poll creation and results will silently fail.

@dataclass
class PollState:
    message_id: int
    channel_id: int
    question: str
    options: List[str]
    votes: Dict[int, int]  # user_id -> option_index
    ended: bool = False


# Active poll per vote-channel id
POLL_BY_CHANNEL: Dict[int, PollState] = {}


def _poll_counts(poll: PollState) -> List[int]:
    counts = [0] * max(0, len(poll.options))
    for opt in (poll.votes or {}).values():
        try:
            i = int(opt)
        except Exception:
            continue
        if 0 <= i < len(counts):
            counts[i] += 1
    return counts


def poll_results_text(poll: PollState) -> str:
    counts = _poll_counts(poll)
    total = sum(counts)
    lines = [f"📊 **{poll.question}**", ""]
    for i, opt in enumerate(poll.options):
        c = counts[i] if i < len(counts) else 0
        pct = (c / total * 100.0) if total else 0.0
        lines.append(f"{i+1}) {opt} — **{c}** vote{'s' if c != 1 else ''} ({pct:.0f}%)")
    lines.append("")
    lines.append(f"Total votes: **{total}**")
    if poll.ended:
        lines.append("Status: 🔒 CLOSED")
    else:
        lines.append("Status: 🗳️ OPEN")
    out = "\n".join(lines)
    # Hard safety for Discord 2000 char limit
    if len(out) > 1990:
        out = out[:1990] + "…"
    return out


def poll_embed(poll: PollState) -> discord.Embed:
    counts = _poll_counts(poll)
    total = sum(counts)
    desc_lines = [f"**{poll.question}**", ""]
    for i, opt in enumerate(poll.options):
        c = counts[i] if i < len(counts) else 0
        pct = (c / total * 100.0) if total else 0.0
        desc_lines.append(f"**{i+1}. {opt}** — {c} ({pct:.0f}%)")
    status = "🔒 CLOSED" if poll.ended else "🗳️ OPEN"
    e = discord.Embed(
        title="📊 Server Poll",
        description="\n".join(desc_lines),
        color=0x3498DB,
    )
    e.set_footer(text=f"Status: {status} • Total votes: {total}")
    e.timestamp = datetime.utcnow()
    return e


class PollView(discord.ui.View):
    """Persistent voting buttons for a poll in a specific channel."""

    def __init__(self, channel_id: int):
        super().__init__(timeout=None)
        self.channel_id = int(channel_id)

    def build_buttons(self) -> None:
        self.clear_items()
        poll = POLL_BY_CHANNEL.get(self.channel_id)
        if not poll:
            return

        for idx, _opt in enumerate(poll.options[:10]):
            btn = discord.ui.Button(
                label=str(idx + 1),
                style=discord.ButtonStyle.primary,
                custom_id=f"pollvote:{self.channel_id}:{idx}",
            )

            async def _cb(interaction: discord.Interaction, i: int = idx):
                await self._handle_vote(interaction, i)

            btn.callback = _cb
            self.add_item(btn)

    async def _handle_vote(self, interaction: discord.Interaction, option_index: int) -> None:
        if not interaction.guild or not interaction.user:
            try:
                if not interaction.response.is_done():
                    await interaction.response.send_message("❌ Server context required.", ephemeral=True)
            except Exception:
                pass
            return

        poll = POLL_BY_CHANNEL.get(self.channel_id)
        if not poll:
            try:
                await interaction.response.send_message("ℹ️ No active poll found.", ephemeral=True)
            except Exception:
                pass
            return

        # Ensure the click belongs to the current poll message
        try:
            if interaction.message and poll.message_id and int(interaction.message.id) != int(poll.message_id):
                await interaction.response.send_message("ℹ️ This poll is no longer active.", ephemeral=True)
                return
        except Exception:
            pass

        if poll.ended:
            try:
                await interaction.response.send_message("🔒 This poll is closed.", ephemeral=True)
            except Exception:
                pass
            return

        # Record vote (allow changing)
        poll.votes[int(interaction.user.id)] = int(option_index)
        try:
            await db_record_poll_vote(poll.message_id, int(interaction.user.id), int(option_index))
        except Exception:
            pass

        # Update the poll message (counts)
        try:
            if interaction.message:
                await interaction.message.edit(embed=poll_embed(poll), view=self)
        except Exception:
            pass

        # Always acknowledge
        try:
            if not interaction.response.is_done():
                await interaction.response.send_message(
                    f"✅ Vote recorded: **{poll.options[option_index]}**",
                    ephemeral=True,
                )
            else:
                await interaction.followup.send(
                    f"✅ Vote recorded: **{poll.options[option_index]}**",
                    ephemeral=True,
                )
        except Exception:
            pass


async def create_poll_in_channel(
    guild: discord.Guild,
    channel_id: int,
    question: str,
    options: List[str],
    created_by: Optional[discord.abc.User] = None,
) -> Tuple[bool, str]:
    """Create a poll message in the vote channel (buttons + DB persistence)."""
    ch = await _get_text_channel(guild, str(channel_id))
    if not ch:
        return False, "Poll channel not found (check channel ID permissions)."

    existing = POLL_BY_CHANNEL.get(int(channel_id))
    if existing and not existing.ended:
        return False, "There is already an active poll in that channel. End or delete it first."

    q = (question or "").strip()
    opts = [str(o).strip() for o in (options or []) if str(o).strip()]
    if len(opts) < 2:
        return False, "Please provide at least 2 options."
    opts = opts[:10]

    poll = PollState(
        message_id=0,
        channel_id=int(channel_id),
        question=q[:200],
        options=opts,
        votes={},
        ended=False,
    )

    # Store now so the view can resolve counts during callbacks
    POLL_BY_CHANNEL[int(channel_id)] = poll

    view = PollView(int(channel_id))
    view.build_buttons()

    try:
        msg = await ch.send(embed=poll_embed(poll), view=view)
    except Exception as e:
        POLL_BY_CHANNEL.pop(int(channel_id), None)
        return False, f"Failed to post poll message: {repr(e)}"

    poll.message_id = int(msg.id)

    # Persist poll shell
    try:
        await db_upsert_poll(poll.message_id, poll.channel_id, poll.question, poll.options, ended=False)
    except Exception:
        pass

    # Ensure the view stays alive across restarts
    try:
        bot.add_view(view)
    except Exception:
        pass

    return True, "Poll posted."


async def _create_poll_message(channel: discord.TextChannel, question: str, options: List[str]) -> Optional[PollState]:
    """Back-compat helper used by /poll command."""
    if not channel.guild:
        return None
    ok, _msg = await create_poll_in_channel(channel.guild, int(channel.id), question, options, created_by=None)
    if not ok:
        return None
    return POLL_BY_CHANNEL.get(int(channel.id))


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


        # ✅ Poll system: register active poll views so votes work after restarts (DB-backed)
        try:
            for ch_id, poll in list(POLL_BY_CHANNEL.items()):
                if poll and not getattr(poll, "ended", False):
                    v = PollView(ch_id)
                    v.build_buttons()
                    self.add_view(v)
            print("POLL: persistent views registered", flush=True)
        except Exception:
            print("POLL: failed to register persistent views:", traceback.format_exc(), flush=True)

        # ✅ Ticket system: register persistent views so buttons/selects work after restarts
        try:
            self.add_view(TicketPanelView())
            self.add_view(TicketControlsView())
            # ✅ Server control panel: register persistent view for 24/7 buttons
            self.add_view(PersistentServerControlView())
            self.add_view(StarterKitPanelView())
            self.add_view(StarterVaultAdminView())
            self.add_view(PersistentPollPanelView())
            self.add_view(GetRoleView())
            self.add_view(SelfRolesView())
            self.add_view(RoleManagerView())
            self.add_view(TameCalculatorView())
            self.add_view(CalcSettingsView())
            print("TICKETS: persistent views registered", flush=True)
        except Exception:
            print("TICKETS: failed to register views:", traceback.format_exc(), flush=True)

bot = DemocracyBot(command_prefix="!", intents=intents)  # prefix irrelevant, we use slash

VIEWS_REGISTERED = False  # persistent UI views registered on startup

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
                    box INT PRIMARY KEY,
                    pin TEXT NOT NULL
                );
            """)
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS claims (
                    user_id BIGINT PRIMARY KEY,
                    box INT NOT NULL,
                    pin TEXT NOT NULL,
                    claimed_at BIGINT NOT NULL
                );
            """)
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS starter_claimed_users (
                    user_id BIGINT PRIMARY KEY,
                    first_claimed_at BIGINT NOT NULL,
                    last_box INT,
                    last_pin TEXT
                );
            """)
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS resets (
                    id SERIAL PRIMARY KEY,
                    timestamp BIGINT NOT NULL,
                    reason TEXT NOT NULL
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

            # ✅ NEW: Poll system tables (DB-backed so polls survive restarts)
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS polls (
                    message_id BIGINT PRIMARY KEY,
                    channel_id BIGINT NOT NULL,
                    question TEXT NOT NULL,
                    options TEXT NOT NULL, -- newline-separated
                    ended BOOLEAN NOT NULL DEFAULT FALSE,
                    created_at BIGINT NOT NULL,
                    ended_at BIGINT
                );
            """)
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS poll_votes (
                    message_id BIGINT NOT NULL,
                    user_id BIGINT NOT NULL,
                    option_index INTEGER NOT NULL,
                    voted_at BIGINT NOT NULL,
                    PRIMARY KEY (message_id, user_id)
                );
            """)

            # ✅ NEW: Self-assign roles list (role manager / get-role panel)
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS self_roles (
                    role_id BIGINT PRIMARY KEY,
                    label TEXT NOT NULL,
                    description TEXT NOT NULL DEFAULT '',
                    added_at BIGINT NOT NULL
                );
            """)

            # ✅ NEW: Tame calculator settings (kept tiny so it stays within free Neon limits)
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS calc_settings (
                    guild_id BIGINT PRIMARY KEY,
                    taming_speed DOUBLE PRECISION NOT NULL DEFAULT 5.0,
                    food_drain DOUBLE PRECISION NOT NULL DEFAULT 1.0,
                    use_single_player_settings BOOLEAN NOT NULL DEFAULT FALSE,
                    updated_at BIGINT NOT NULL DEFAULT 0
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


async def db_load_claimed_users(con: asyncpg.Connection) -> Set[int]:
    rows = await con.fetch("SELECT user_id FROM starter_claimed_users")
    return {int(r["user_id"]) for r in rows}

async def db_mark_user_claimed(con: asyncpg.Connection, user_id: int, box: int | None = None, pin: str | None = None) -> None:
    # Keep a permanent record that this user has claimed a kit at least once.
    now_ts = int(time.time())
    await con.execute(
        """
        INSERT INTO starter_claimed_users (user_id, first_claimed_at, last_box, last_pin)
        VALUES ($1, $2, $3, $4)
        ON CONFLICT (user_id) DO UPDATE
            SET last_box = COALESCE(EXCLUDED.last_box, starter_claimed_users.last_box),
                last_pin = COALESCE(EXCLUDED.last_pin, starter_claimed_users.last_pin)
        """,
        int(user_id), now_ts, (int(box) if box is not None else None), pin,
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
        )# -----------------------
# ✅ NEW: Poll DB helpers (polls survive restarts)
# -----------------------
async def db_load_active_polls() -> List[Dict[str, Any]]:
    """Load active (not ended) polls and their votes from DB."""
    if DB_POOL is None:
        return []
    polls: List[Dict[str, Any]] = []
    async with DB_POOL.acquire() as conn:
        rows = await conn.fetch("SELECT message_id, channel_id, question, options, ended FROM polls WHERE ended = FALSE;")
        for r in rows:
            mid = int(r["message_id"])
            votes_rows = await conn.fetch("SELECT user_id, option_index FROM poll_votes WHERE message_id=$1;", mid)
            votes = {}
            for vr in votes_rows:
                try:
                    votes[int(vr["user_id"])] = int(vr["option_index"])
                except Exception:
                    continue
            polls.append({
                "message_id": mid,
                "channel_id": int(r["channel_id"]),
                "question": str(r["question"] or ""),
                "options": [o for o in str(r["options"] or "").splitlines() if o.strip()],
                "votes": votes,
                "ended": bool(r["ended"]),
            })
    return polls

async def db_upsert_poll(message_id: int, channel_id: int, question: str, options: List[str], ended: bool = False) -> None:
    if DB_POOL is None:
        return
    opts = "\n".join([str(o).strip() for o in (options or []) if str(o).strip()])
    async with DB_POOL.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO polls (message_id, channel_id, question, options, ended, created_at)
            VALUES ($1,$2,$3,$4,$5,$6)
            ON CONFLICT (message_id) DO UPDATE SET
              channel_id=EXCLUDED.channel_id,
              question=EXCLUDED.question,
              options=EXCLUDED.options,
              ended=EXCLUDED.ended;
            """,
            int(message_id), int(channel_id), str(question or ""), str(opts), bool(ended), int(time.time())
        )

async def db_set_poll_ended(message_id: int, ended: bool = True) -> None:
    if DB_POOL is None:
        return
    async with DB_POOL.acquire() as conn:
        await conn.execute(
            "UPDATE polls SET ended=$2, ended_at=$3 WHERE message_id=$1;",
            int(message_id), bool(ended), int(time.time()) if ended else None
        )

async def db_delete_poll(message_id: int) -> None:
    if DB_POOL is None:
        return
    async with DB_POOL.acquire() as conn:
        async with conn.transaction():
            await conn.execute("DELETE FROM poll_votes WHERE message_id=$1;", int(message_id))
            await conn.execute("DELETE FROM polls WHERE message_id=$1;", int(message_id))

async def db_record_poll_vote(message_id: int, user_id: int, option_index: int) -> None:
    if DB_POOL is None:
        return
    async with DB_POOL.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO poll_votes (message_id, user_id, option_index, voted_at)
            VALUES ($1,$2,$3,$4)
            ON CONFLICT (message_id, user_id) DO UPDATE SET
              option_index=EXCLUDED.option_index,
              voted_at=EXCLUDED.voted_at;
            """,
            int(message_id), int(user_id), int(option_index), int(time.time())
        )



# -----------------------
# ✅ NEW: Self roles DB helpers
# -----------------------
async def db_load_self_roles() -> Dict[int, Tuple[str, str]]:
    if DB_POOL is None:
        return {}
    out: Dict[int, Tuple[str, str]] = {}
    async with DB_POOL.acquire() as conn:
        rows = await conn.fetch("SELECT role_id, label, description FROM self_roles ORDER BY added_at ASC;")
        for r in rows:
            try:
                rid = int(r["role_id"])
                label = str(r["label"] or "").strip() or f"Role {rid}"
                desc = str(r["description"] or "").strip()
                out[rid] = (label, desc)
            except Exception:
                continue
    return out

async def db_upsert_self_role(role_id: int, label: str, description: str = "") -> None:
    if DB_POOL is None:
        return
    await _db_execute(
        """
        INSERT INTO self_roles (role_id, label, description, added_at)
        VALUES ($1,$2,$3,$4)
        ON CONFLICT (role_id) DO UPDATE SET
          label=EXCLUDED.label,
          description=EXCLUDED.description;
        """,
        int(role_id), str(label or ""), str(description or ""), int(time.time())
    )

async def db_delete_self_role(role_id: int) -> None:
    if DB_POOL is None:
        return
    await _db_execute("DELETE FROM self_roles WHERE role_id=$1;", int(role_id))

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
CLAIMED_USERS: Set[int] = set()  # user_ids who have EVER claimed (even if a vault is later recycled)

# Self-assign roles (role_id -> (label, description))
SELF_ROLES: Dict[int, Tuple[str, str]] = {}

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
    """Return a ping string for server alerts, or empty string.

    If SERVER_PING_EVERYONE is enabled, returns "@everyone ".
    Otherwise returns role mentions based on SERVER_PING_ROLE_IDS.
    """
    if SERVER_PING_EVERYONE:
        return "@everyone "

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

def _alert_allowed_mentions() -> discord.AllowedMentions:
    """Allowed mentions for alerts (prevents accidental broad pings).

    - If SERVER_PING_EVERYONE: allow @everyone only.
    - Else: allow role mentions only.
    """
    if SERVER_PING_EVERYONE:
        return discord.AllowedMentions(everyone=True, roles=False, users=False, replied_user=False)
    return discord.AllowedMentions(everyone=False, roles=True, users=False, replied_user=False)

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

async def _nitrado_post_action(action_label: str, endpoint_suffixes: List[str]) -> Tuple[bool, str]:
    """
    Try multiple possible Nitrado endpoints for an action. Some products expose slightly different paths.
    We treat 404 as "try next", but any other non-2xx is returned immediately so you can see the real error.
    """
    if not NITRADO_TOKEN:
        return False, "NITRADO_TOKEN missing in Railway Variables."
    if not _is_digit_id(NITRADO_SERVICE_ID):
        return False, "NITRADO_SERVICE_ID missing/invalid in Railway Variables."

    headers = {
        "Authorization": f"Bearer {NITRADO_TOKEN}",
        "Accept": "application/json",
    }

    last_404 = None
    try:
        async with aiohttp.ClientSession(headers=headers, timeout=aiohttp.ClientTimeout(total=25)) as session:
            for suffix in endpoint_suffixes:
                url = f"https://api.nitrado.net/services/{NITRADO_SERVICE_ID}/{suffix.lstrip('/')}"
                async with session.post(url) as resp:
                    body = await resp.text()
                    if 200 <= resp.status < 300:
                        return True, f"{action_label} triggered via `{suffix}`."
                    if resp.status == 404:
                        last_404 = f"{resp.status}: {body}"
                        continue
                    return False, f"{action_label} failed ({resp.status}): {body}"
    except Exception as e:
        return False, f"{action_label} failed: {type(e).__name__}: {e}"

    return False, f"{action_label} failed. Endpoints not found (last 404: {last_404})."

async def nitrado_restart_call() -> Tuple[bool, str]:
    """Restart the gameserver."""
    return await _nitrado_post_action("RESTART", [
        "gameservers/restart",
        "gameserver/restart",
    ])

async def nitrado_start_call() -> Tuple[bool, str]:
    """Start the gameserver (with a safe fallback)."""
    # Some Nitrado products do not expose a dedicated /start action.
    # If so, /restart often starts a stopped server.
    return await _nitrado_post_action("START", [
        "gameservers/start",
        "gameserver/start",
        "gameservers/restart",  # fallback
        "gameserver/restart",
    ])

async def nitrado_stop_call() -> Tuple[bool, str]:
    """Stop the gameserver."""
    return await _nitrado_post_action("STOP", [
        "gameservers/stop",
        "gameserver/stop",
    ])

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
        super().__init__(timeout=300)
        self.requester_id = requester_id
        self.announcement = (announcement or "").strip()

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user and interaction.user.id == self.requester_id:
            return True
        try:
            msg = "❌ Only the person who ran the command can use these buttons."
            if interaction.response.is_done():
                await interaction.followup.send(msg, ephemeral=True)
            else:
                await interaction.response.send_message(msg, ephemeral=True)
        except Exception:
            pass
        return False

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

async def nitrado_status_call():
    """Fetch Nitrado server status with robust field fallbacks.

    Nitrado's API payload differs a bit between games and sometimes omits the `query`
    object on some endpoints. This function tries a small set of endpoints and
    extracts host/map/player info using multiple fallbacks so the status panel stays populated.
    """
    try:
        token = os.getenv("NITRADO_TOKEN")
        service_id = os.getenv("NITRADO_SERVICE_ID")
        if not token or not service_id:
            return False, {"error": "Missing NITRADO_TOKEN or NITRADO_SERVICE_ID"}

        headers = {
            "Authorization": f"Bearer {token}",
            "Accept": "application/json",
        }

        def _to_int(v):
            try:
                if v is None:
                    return None
                if isinstance(v, bool):
                    return int(v)
                if isinstance(v, (int, float)):
                    return int(v)
                s = str(v).strip()
                if s == "" or s == "-" or s.lower() == "none":
                    return None
                return int(float(s))
            except Exception:
                return None

        def _coalesce(*vals):
            for v in vals:
                if v is None:
                    continue
                if isinstance(v, str) and v.strip() in ("", "-", "none", "None"):
                    continue
                return v
            return None

        def _deep_find(obj, wanted_keys, max_nodes=5000):
            """Return the first value for any key in `wanted_keys` found anywhere in obj."""
            if not isinstance(wanted_keys, (set, list, tuple)):
                wanted = {str(wanted_keys).lower()}
            else:
                wanted = {str(k).lower() for k in wanted_keys}

            seen = 0
            stack = [obj]
            while stack and seen < max_nodes:
                cur = stack.pop()
                seen += 1
                if isinstance(cur, dict):
                    for k, v in cur.items():
                        lk = str(k).lower()
                        if lk in wanted:
                            return v
                        if isinstance(v, (dict, list)):
                            stack.append(v)
                elif isinstance(cur, list):
                    for v in cur:
                        if isinstance(v, (dict, list)):
                            stack.append(v)
            return None

        async def _fetch_json(suffix: str):
            url = f"https://api.nitrado.net/services/{service_id}/{suffix.lstrip('/')}"
            timeout = aiohttp.ClientTimeout(total=15)
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.get(url, headers=headers) as resp:
                    try:
                        data = await resp.json(content_type=None)
                    except Exception:
                        data = {"_raw": await resp.text()}
                    return resp.status, data

        def _extract_payload(raw):
            # Nitrado generally wraps as {"data": {"gameserver": {...}}}
            if not isinstance(raw, dict):
                return None

            data = raw.get("data")
            if not isinstance(data, dict):
                data = {}

            gs = (
                data.get("gameserver")
                or data.get("game_server")
                or data.get("gameservers")
                or data
            )
            if not isinstance(gs, dict):
                return None

            query = gs.get("query") if isinstance(gs.get("query"), dict) else {}
            settings = gs.get("settings") if isinstance(gs.get("settings"), dict) else {}

            # Hostname / server name
            hostname = _coalesce(
                gs.get("hostname"),
                gs.get("server_name"),
                gs.get("name"),
                query.get("hostname"),
                query.get("server_name"),
                query.get("name"),
                _deep_find(gs, {"hostname", "server_name", "servername", "name"}),
            )

            # Game identifier
            game = _coalesce(
                gs.get("game"),
                gs.get("game_short"),
                gs.get("game_id"),
                query.get("game"),
                query.get("game"),
                _deep_find(gs, {"game", "game_short", "gameid", "game_id"}),
            )

            # Map (ark/asa varies)
            map_name = _coalesce(
                query.get("map"),
                query.get("map_name"),
                query.get("level"),
                query.get("level_name"),
                settings.get("map"),
                settings.get("map_name"),
                gs.get("map"),
                gs.get("map_name"),
                _deep_find(gs, {"map", "map_name", "level", "level_name", "mapname"}),
            )

            # Players / slots
            players = _coalesce(
                query.get("players"),
                query.get("player_current"),
                query.get("players_current"),
                query.get("numplayers"),
                query.get("num_players"),
                gs.get("players"),
                gs.get("player_current"),
                _deep_find(gs, {"players", "player_current", "players_current", "numplayers", "num_players"}),
            )
            slots = _coalesce(
                query.get("slots"),
                query.get("player_max"),
                query.get("players_max"),
                query.get("maxplayers"),
                query.get("max_players"),
                gs.get("slots"),
                gs.get("player_max"),
                _deep_find(gs, {"slots", "player_max", "players_max", "maxplayers", "max_players"}),
            )

            ip = _coalesce(
                query.get("ip"),
                query.get("ip_address"),
                gs.get("ip"),
                gs.get("ip_address"),
                _deep_find(gs, {"ip", "ip_address", "ipaddress"}),
            )
            port = _coalesce(
                query.get("port"),
                gs.get("port"),
                _deep_find(gs, {"port"}),
            )

            status_txt = _coalesce(
                gs.get("status"),
                query.get("status"),
                _deep_find(gs, {"status", "state"}),
            )

            payload = {
                "status": status_txt,
                "hostname": hostname,
                "game": game,
                "map": map_name,
                "ip": ip,
                "port": _to_int(port),
                "players": _to_int(players),
                "slots": _to_int(slots),
            }
            return payload

        best = None
        best_score = -1

        # Try a few endpoints; whichever yields the richest payload wins.
        for suffix in (
            "gameservers",
            "gameservers/gameserver",
            "gameservers/gameserver/status",
            "gameserver",
        ):
            status_code, raw = await _fetch_json(suffix)
            if status_code >= 400:
                continue

            payload = _extract_payload(raw)
            if not payload:
                continue

            score = sum(1 for k in ("hostname", "map", "players", "slots", "ip", "port") if payload.get(k) not in (None, "", "-"))
            if score > best_score:
                best = payload
                best_score = score

            # If we have the critical fields, stop early.
            if payload.get("players") is not None and payload.get("slots") is not None and payload.get("map") not in (None, "", "-"):
                return True, payload

        if best:
            return True, best

        return False, {"error": "Unable to fetch status from Nitrado (no usable payload)"}
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
        color=0x2ECC71,
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
        await ch.send(content=ping, embed=e, allowed_mentions=_alert_allowed_mentions())
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
        await ch.send(msg, allowed_mentions=_alert_allowed_mentions())
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
                    color=0x2ECC71,
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
        super().__init__(timeout=300)
        self.requester_id = requester_id
        self.action = action
        self.announcement = (announcement or "").strip()

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user and interaction.user.id == self.requester_id:
            return True
        try:
            msg = "❌ Only the person who opened this panel can use these buttons. Run the command yourself."
            if interaction.response.is_done():
                await interaction.followup.send(msg, ephemeral=True)
            else:
                await interaction.response.send_message(msg, ephemeral=True)
        except Exception:
            pass
        return False

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

# =====================================================================
# ✅ NEW: Persistent 24/7 Server Control Panel message (no command needed)
# =====================================================================

def _build_control_panel_embed() -> discord.Embed:
    box = (
        "```ansi\n"
        "⟦ DEMOCRACY ARK : SERVER CONTROL PANEL ⟧\n"
        "Use the buttons below to Start / Stop / Restart.\n"
        "You will be prompted for an announcement message.\n"
        "A confirmation step prevents misclicks.\n"
        "```"
    )
    e = discord.Embed(
        title="🛠 Democracy Bot — Server Control Panel",
        color=0xE67E22,
        description=box,
    )
    e.timestamp = datetime.utcnow()
    return e

class PersistentServerControlView(discord.ui.View):
    """Persistent buttons so the panel works after bot restarts."""
    def __init__(self):
        super().__init__(timeout=None)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if not interaction.guild or not isinstance(interaction.user, discord.Member):
            try:
                if interaction.response.is_done():
                    await interaction.followup.send("❌ Server context required.", ephemeral=True)
                else:
                    await interaction.response.send_message("❌ Server context required.", ephemeral=True)
            except Exception:
                pass
            return False

        if not is_staff_member(interaction.user):
            try:
                if interaction.response.is_done():
                    await interaction.followup.send("❌ Staff only.", ephemeral=True)
                else:
                    await interaction.response.send_message("❌ Staff only.", ephemeral=True)
            except Exception:
                pass
            return False

        return True

    @discord.ui.button(label="Start", style=discord.ButtonStyle.success, custom_id="serverctl_start")
    async def start_btn(self, interaction: discord.Interaction, _: discord.ui.Button):
        try:
            await interaction.response.send_modal(ServerActionModal(requester_id=interaction.user.id, action="start"))
        except Exception as e:
            try:
                msg = f"❌ Could not open form: {repr(e)}"
                if interaction.response.is_done():
                    await interaction.followup.send(msg, ephemeral=True)
                else:
                    await interaction.response.send_message(msg, ephemeral=True)
            except Exception:
                pass

    @discord.ui.button(label="Stop", style=discord.ButtonStyle.secondary, custom_id="serverctl_stop")
    async def stop_btn(self, interaction: discord.Interaction, _: discord.ui.Button):
        try:
            await interaction.response.send_modal(ServerActionModal(requester_id=interaction.user.id, action="stop"))
        except Exception as e:
            try:
                msg = f"❌ Could not open form: {repr(e)}"
                if interaction.response.is_done():
                    await interaction.followup.send(msg, ephemeral=True)
                else:
                    await interaction.response.send_message(msg, ephemeral=True)
            except Exception:
                pass

    @discord.ui.button(label="Restart", style=discord.ButtonStyle.danger, custom_id="serverctl_restart")
    async def restart_btn(self, interaction: discord.Interaction, _: discord.ui.Button):
        try:
            await interaction.response.send_modal(ServerActionModal(requester_id=interaction.user.id, action="restart"))
        except Exception as e:
            try:
                msg = f"❌ Could not open form: {repr(e)}"
                if interaction.response.is_done():
                    await interaction.followup.send(msg, ephemeral=True)
                else:
                    await interaction.response.send_message(msg, ephemeral=True)
            except Exception:
                pass

async def ensure_server_control_panel(guild: discord.Guild) -> None:
    """Ensure the 24/7 control panel message exists and has buttons attached."""
    if not _is_digit_id(SERVER_CONTROL_CHANNEL_ID):
        return

    ch = await _get_text_channel(guild, SERVER_CONTROL_CHANNEL_ID)
    if not ch:
        return

    view = PersistentServerControlView()
    embed = _build_control_panel_embed()

    # If message ID is known, edit it in place; otherwise create a new one.
    if _is_digit_id(SERVER_CONTROL_MESSAGE_ID):
        try:
            msg = await ch.fetch_message(int(SERVER_CONTROL_MESSAGE_ID))
            await msg.edit(embed=embed, view=view)
            return
        except Exception:
            pass

    try:
        msg = await ch.send(embed=embed, view=view)
        print(f"[SERVERCTL] New SERVER_CONTROL_MESSAGE_ID = {msg.id} (save this in Railway Variables)", flush=True)
        # Optional pin
        if SERVER_CONTROL_PIN:
            try:
                await msg.pin(reason="Democracy Bot: server control panel")
            except Exception:
                pass
    except Exception:
        pass

class ServerControlView(discord.ui.View):
    def __init__(self, requester_id: int):
        super().__init__(timeout=600)
        self.requester_id = requester_id

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user and interaction.user.id == self.requester_id:
            return True
        try:
            msg = "❌ Only the person who opened this panel can use these buttons. Run the command yourself."
            if interaction.response.is_done():
                await interaction.followup.send(msg, ephemeral=True)
            else:
                await interaction.response.send_message(msg, ephemeral=True)
        except Exception:
            pass
        return False

    @discord.ui.button(label="Start", style=discord.ButtonStyle.success)
    async def start_btn(self, interaction: discord.Interaction, _: discord.ui.Button):
        try:
            await interaction.response.send_modal(ServerActionModal(requester_id=self.requester_id, action="start"))
        except Exception as e:
            try:
                msg = f"❌ Could not open form: {repr(e)}"
                if interaction.response.is_done():
                    await interaction.followup.send(msg, ephemeral=True)
                else:
                    await interaction.response.send_message(msg, ephemeral=True)
            except Exception:
                pass

    @discord.ui.button(label="Stop", style=discord.ButtonStyle.secondary)
    async def stop_btn(self, interaction: discord.Interaction, _: discord.ui.Button):
        try:
            await interaction.response.send_modal(ServerActionModal(requester_id=self.requester_id, action="stop"))
        except Exception as e:
            try:
                msg = f"❌ Could not open form: {repr(e)}"
                if interaction.response.is_done():
                    await interaction.followup.send(msg, ephemeral=True)
                else:
                    await interaction.response.send_message(msg, ephemeral=True)
            except Exception:
                pass

    @discord.ui.button(label="Restart", style=discord.ButtonStyle.danger)
    async def restart_btn(self, interaction: discord.Interaction, _: discord.ui.Button):
        try:
            await interaction.response.send_modal(ServerActionModal(requester_id=self.requester_id, action="restart"))
        except Exception as e:
            try:
                msg = f"❌ Could not open form: {repr(e)}"
                if interaction.response.is_done():
                    await interaction.followup.send(msg, ephemeral=True)
                else:
                    await interaction.response.send_message(msg, ephemeral=True)
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
        await ch.send(content=ping, embed=e, allowed_mentions=_alert_allowed_mentions())
    except Exception:
        pass
# =====================================================================
# ✅ NEW: Starter Kit + Poll MODULE PANELS (no commands needed for players)
# =====================================================================

_STARTER_PANEL_MESSAGE_ID_RUNTIME: int = int(STARTER_PANEL_MESSAGE_ID) if _is_digit_id(STARTER_PANEL_MESSAGE_ID) else 0
_POLL_PANEL_MESSAGE_ID_RUNTIME: int = int(POLL_PANEL_MESSAGE_ID) if _is_digit_id(POLL_PANEL_MESSAGE_ID) else 0

def _module_box(header: str, lines: List[str]) -> str:
    """Pretty ANSI-style module box with a unique header."""
    safe_lines = [str(x) for x in (lines or [])]
    body = "\n".join(safe_lines)
    return (
        "```ansi\n"
        f"⟦ {header} ⟧\n"
        f"{body}\n"
        "```"
    )

def _starter_panel_channel_id() -> str:
    return STARTER_PANEL_CHANNEL_ID if _is_digit_id(STARTER_PANEL_CHANNEL_ID) else CLAIM_CHANNEL_ID

def _poll_panel_channel_id() -> str:
    """Where the Poll MODULE PANEL message lives (staff/private by default)."""
    # Prefer explicit create channel, then POLL_PANEL_CHANNEL_ID, then fall back to VOTE_CHANNEL_ID (last resort).
    if _is_digit_id(POLL_CREATE_CHANNEL_ID):
        return POLL_CREATE_CHANNEL_ID
    if _is_digit_id(POLL_PANEL_CHANNEL_ID):
        return POLL_PANEL_CHANNEL_ID
    return VOTE_CHANNEL_ID

def _poll_vote_channel_id() -> str:
    """Where polls are posted and voted on (public by default)."""
    # Prefer explicit vote channel, then VOTE_CHANNEL_ID.
    if _is_digit_id(POLL_VOTE_CHANNEL_ID):
        return POLL_VOTE_CHANNEL_ID
    return VOTE_CHANNEL_ID

def _build_starter_panel_embed() -> discord.Embed:
    lines = [
        "🎁 Claim your free ingame starter kit",
        "",
        f"Available kits : {len(PINS_POOL)}",
        "One per person : enabled",
        "",
        "Press **Claim Starter Kit** to receive your vault PIN privately.",
    ]
    e = discord.Embed(
        title="🎁 Democracy Bot — Starter Kit Module",
        description=_module_box("STARTER KIT MODULE", lines),
        color=0xF1C40F,
    )
    e.set_footer(text="If kits are out of stock, ask an admin to restock the pool.")
    e.timestamp = datetime.utcnow()
    return e

class StarterKitPanelView(discord.ui.View):
    """Persistent view for the Starter Kit module panel."""
    def __init__(self):
        super().__init__(timeout=None)

    async def _claim(self, interaction: discord.Interaction):
        # Mirror /claimstarter behavior (same channel rules)
        if not interaction.user:
            return

        # Enforce claim channel if configured
        allowed_ch = _starter_panel_channel_id()
        if not _only_in_channel(interaction, allowed_ch):
            await _wrong_channel(interaction, "#claim-starter-kit")
            return

        uid = interaction.user.id

        # If they've ever claimed before (even if the vault was recycled later), block re-claim.
        if uid not in CLAIMS and uid in CLAIMED_USERS:
            try:
                await interaction.response.send_message(
                    "❌ You've already claimed a free starter kit on this server.\n"
                    "If you need help, open a ticket and a staff member can assist.",
                    ephemeral=True,
                )
            except Exception:
                pass
            return

        # One per person check
        if uid in CLAIMS:
            box, pin = CLAIMS[uid]
            try:
                await interaction.response.send_message(
                    f"✅ You already claimed a kit.\n**Your box:** #{box}\n**Your PIN:** `{pin}`",
                    ephemeral=True,
                )
            except Exception:
                pass
            return

        if not PINS_POOL:
            try:
                await interaction.response.send_message(
                    "❌ No starter kits available right now.\nAsk an admin to restock.",
                    ephemeral=True,
                )
            except Exception:
                pass
            return

        # Pick lowest box number available
        box = sorted(PINS_POOL.keys())[0]
        bp = PINS_POOL.pop(box)

        await save_pool_state()
        CLAIMS[uid] = (bp.box, bp.pin)
        await save_claims_only()

        # Permanently mark this user as having claimed (even if a vault is later recycled)
        CLAIMED_USERS.add(uid)
        if DATABASE_URL and DB_POOL:
            try:
                async with DB_POOL.acquire() as con:
                    await db_mark_user_claimed(con, uid, box=bp.box, pin=bp.pin)
            except Exception:
                pass
        else:
            await save_claimed_users_only()
        msg = (
            f"🎁 Starter kit claimed!\n"
            f"**Your box:** #{bp.box}\n"
            f"**Your PIN:** `{bp.pin}`\n\n"
            f"Go to the Community Hub and unlock **Box #{bp.box}** with that PIN."
        )

        # Ephemeral + DM fallback
        try:
            await interaction.response.send_message(msg, ephemeral=True)
        except Exception:
            pass
        try:
            await interaction.user.send(msg)
        except Exception:
            pass

        # Refresh panel counts
        try:
            if interaction.guild:
                await refresh_starter_panel(interaction.guild)
        except Exception:
            pass

    @discord.ui.button(label="Claim Starter Kit", style=discord.ButtonStyle.primary, custom_id="starterpanel_claim")
    async def claim_btn(self, interaction: discord.Interaction, _: discord.ui.Button):
        await self._claim(interaction)

    @discord.ui.button(label="My Kit", style=discord.ButtonStyle.secondary, custom_id="starterpanel_mykit")
    async def mykit_btn(self, interaction: discord.Interaction, _: discord.ui.Button):
        if not interaction.user:
            return
        uid = interaction.user.id
        if uid in CLAIMS:
            box, pin = CLAIMS[uid]
            try:
                await interaction.response.send_message(
                    f"✅ Your kit:\n**Box:** #{box}\n**PIN:** `{pin}`",
                    ephemeral=True,
                )
            except Exception:
                pass
        else:
            try:
                await interaction.response.send_message(
                    "ℹ️ You haven't claimed a starter kit yet.\nPress **Claim Starter Kit**.",
                    ephemeral=True,
                )
            except Exception:
                pass

async def _ensure_panel_message(
    guild: discord.Guild,
    channel_id_str: str,
    message_id_runtime_name: str,
    embed: discord.Embed,
    view: discord.ui.View,
    pin: bool = False,
    expected_embed_title: Optional[str] = None,
) -> Optional[int]:
    """Generic helper used by module panels.

    Strategy:
    1) If message id is known (Railway var / runtime), edit it.
    2) Else try to locate an existing pinned/recent panel by embed title (avoids duplicates on restart).
    3) Else send a new one (and optionally pin it).
    """
    ch = await _get_text_channel(guild, channel_id_str)
    if not ch:
        return None

    current_id = globals().get(message_id_runtime_name, 0) or 0
    if current_id:
        try:
            msg = await ch.fetch_message(int(current_id))
            await msg.edit(embed=embed, view=view)
            return int(msg.id)
        except Exception:
            pass

    # Try to reuse an existing pinned/recent panel to avoid duplicates (even if Railway message id isn't set)
    title = expected_embed_title or (embed.title or "")
    if title:
        # 1) Pinned messages
        try:
            pins = await ch.pins()
            for m in pins:
                if not m.embeds:
                    continue
                if m.embeds[0].title == title and (m.author.id == getattr(bot.user, "id", m.author.id) or m.author.bot):
                    try:
                        await m.edit(embed=embed, view=view)
                        return int(m.id)
                    except Exception:
                        continue
        except Exception:
            pass

        # 2) Recent history (last 50)
        try:
            async for m in ch.history(limit=50):
                if not m.embeds:
                    continue
                if m.embeds[0].title == title and (m.author.id == getattr(bot.user, "id", m.author.id) or m.author.bot):
                    try:
                        await m.edit(embed=embed, view=view)
                        return int(m.id)
                    except Exception:
                        continue
        except Exception:
            pass

    try:
        msg = await ch.send(embed=embed, view=view)
        if pin:
            try:
                await msg.pin(reason="Democracy Bot: module panel")
            except Exception:
                pass
        return int(msg.id)
    except Exception:
        return None

async def ensure_starter_panel(guild: discord.Guild) -> None:
    global _STARTER_PANEL_MESSAGE_ID_RUNTIME

    ch_id = _starter_panel_channel_id()
    if not _is_digit_id(ch_id):
        return

    msg_id = await _ensure_panel_message(
        guild=guild,
        channel_id_str=ch_id,
        message_id_runtime_name="_STARTER_PANEL_MESSAGE_ID_RUNTIME",
        embed=_build_starter_panel_embed(),
        view=StarterKitPanelView(),
        pin=STARTER_PANEL_PIN,
        expected_embed_title="🎁 Democracy Bot — Starter Kit Module",
    )
    if msg_id and msg_id != _STARTER_PANEL_MESSAGE_ID_RUNTIME:
        _STARTER_PANEL_MESSAGE_ID_RUNTIME = msg_id
        print(f"[STARTER] New STARTER_PANEL_MESSAGE_ID = {msg_id} (save this in Railway Variables)", flush=True)

async def refresh_starter_panel(guild: discord.Guild) -> None:
    """Update the Starter panel embed in-place (keeps counts accurate)."""
    global _STARTER_PANEL_MESSAGE_ID_RUNTIME
    if not _STARTER_PANEL_MESSAGE_ID_RUNTIME:
        return
    ch_id = _starter_panel_channel_id()
    ch = await _get_text_channel(guild, ch_id)
    if not ch:
        return
    try:
        msg = await ch.fetch_message(int(_STARTER_PANEL_MESSAGE_ID_RUNTIME))
        await msg.edit(embed=_build_starter_panel_embed(), view=StarterKitPanelView())
    except Exception:
        pass


# -----------------------
# ✅ Poll module panel (create polls without commands)
# -----------------------

def _build_poll_panel_embed(active: Optional["PollState"] = None) -> discord.Embed:
    if active and not active.ended:
        counts = _poll_counts(active)
        total = sum(counts)
        lines = [
            "📊 Poll controls",
            "",
            "Active poll : YES",
            f"Question    : {active.question[:80]}",
            f"Total votes : {total}",
            "",
            "Admins: **Create Poll** | **End Poll**",
        ]
    else:
        lines = [
            "📊 Poll controls",
            "",
            "Active poll : NO",
            "",
            "Admins: press **Create Poll** to post a new poll in the vote channel.",
            "Players vote in the vote channel when a poll is posted.",
        ]

    e = discord.Embed(
        title="📊 Democracy Bot — Poll Module",
        description=_module_box("POLL MODULE", lines),
        color=0x3498DB,
    )
    e.timestamp = datetime.utcnow()
    return e

class PollCreateModal(discord.ui.Modal, title="Create a poll"):
    question = discord.ui.TextInput(label="Poll question", required=True, max_length=200)
    options = discord.ui.TextInput(
        label="Options (one per line, 2-10)",
        style=discord.TextStyle.paragraph,
        required=True,
        max_length=1500,
        placeholder="Option 1\nOption 2\nOption 3",
    )

    def __init__(self, channel_id: int):
        super().__init__()
        self.channel_id = int(channel_id)

    async def on_submit(self, interaction: discord.Interaction):
        if not interaction.guild:
            try:
                await interaction.response.send_message("❌ Server context required.", ephemeral=True)
            except Exception:
                pass
            return

        if not is_admin(interaction):
            try:
                await interaction.response.send_message("❌ Admins only.", ephemeral=True)
            except Exception:
                pass
            return

        q = str(self.question.value or "").strip()
        opts = [o.strip() for o in str(self.options.value or "").splitlines() if o.strip()]
        if len(opts) < 2:
            try:
                await interaction.response.send_message("❌ Please provide at least 2 options.", ephemeral=True)
            except Exception:
                pass
            return
        opts = opts[:10]

        try:
            await interaction.response.defer(ephemeral=True)
        except Exception:
            pass

        ok, msg = await create_poll_in_channel(interaction.guild, self.channel_id, q, opts, created_by=interaction.user)
        try:
            await interaction.followup.send(("✅ " if ok else "❌ ") + msg, ephemeral=True)
        except Exception:
            pass

        try:
            await refresh_poll_panel(interaction.guild, self.channel_id)
        except Exception:
            pass

class PersistentPollPanelView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="Create Poll (Admin)", style=discord.ButtonStyle.primary, custom_id="pollpanel_create")
    async def create_btn(self, interaction: discord.Interaction, _: discord.ui.Button):
        if not interaction.guild:
            try:
                await interaction.response.send_message("❌ Server context required.", ephemeral=True)
            except Exception:
                pass
            return
        if not is_admin(interaction):
            try:
                await interaction.response.send_message("❌ Admins only.", ephemeral=True)
            except Exception:
                pass
            return

        ch_id_str = _poll_vote_channel_id()
        if not _is_digit_id(ch_id_str):
            try:
                await interaction.response.send_message("❌ Poll channel not configured.", ephemeral=True)
            except Exception:
                pass
            return

        try:
            await interaction.response.send_modal(PollCreateModal(channel_id=int(ch_id_str)))
        except Exception as e:
            try:
                await interaction.response.send_message(f"❌ Could not open form: {repr(e)}", ephemeral=True)
            except Exception:
                pass

    @discord.ui.button(label="Results", style=discord.ButtonStyle.secondary, custom_id="pollpanel_results")
    async def results_btn(self, interaction: discord.Interaction, _: discord.ui.Button):
        # Always respond; otherwise Discord shows "Interaction Failed".
        if not interaction.guild:
            try:
                await interaction.response.send_message("❌ Server context required.", ephemeral=True)
            except Exception:
                pass
            return

        if not is_admin(interaction):
            try:
                await interaction.response.send_message("❌ Admins only.", ephemeral=True)
            except Exception:
                pass
            return

        ch_id_str = _poll_vote_channel_id()
        if not _is_digit_id(ch_id_str):
            try:
                await interaction.response.send_message("❌ Poll channel not configured.", ephemeral=True)
            except Exception:
                pass
            return

        channel_id = int(ch_id_str)
        poll = POLL_BY_CHANNEL.get(channel_id)
        if not poll:
            try:
                await interaction.response.send_message("ℹ️ No active poll found.", ephemeral=True)
            except Exception:
                pass
            return

        try:
            await interaction.response.defer(ephemeral=True)
        except Exception:
            pass

        try:
            await interaction.followup.send(poll_results_text(poll), ephemeral=True)
        except Exception:
            # Last resort: send a short error so the interaction is acknowledged.
            try:
                if interaction.response.is_done():
                    await interaction.followup.send("❌ Could not display results.", ephemeral=True)
                else:
                    await interaction.response.send_message("❌ Could not display results.", ephemeral=True)
            except Exception:
                pass
    @discord.ui.button(label="End Poll (Admin)", style=discord.ButtonStyle.danger, custom_id="pollpanel_end")
    async def end_btn(self, interaction: discord.Interaction, _: discord.ui.Button):
        if not interaction.guild:
            return
        if not is_admin(interaction):
            try:
                await interaction.response.send_message("❌ Admins only.", ephemeral=True)
            except Exception:
                pass
            return
        ch_id_str = _poll_vote_channel_id()
        if not _is_digit_id(ch_id_str):
            try:
                await interaction.response.send_message("❌ Poll channel not configured.", ephemeral=True)
            except Exception:
                pass
            return
        channel_id = int(ch_id_str)
        poll = POLL_BY_CHANNEL.get(channel_id)
        if not poll or poll.ended:
            try:
                await interaction.response.send_message("ℹ️ No active poll to end.", ephemeral=True)
            except Exception:
                pass
            return

        poll.ended = True
        try:
            await db_set_poll_ended(poll.message_id, True)
        except Exception:
            pass

        try:
            ch = await _get_text_channel(interaction.guild, str(poll.channel_id))
            if ch:
                msg = await ch.fetch_message(poll.message_id)
                await msg.edit(embed=poll_embed(poll), view=None)
        except Exception:
            pass

        try:
            await interaction.response.send_message("✅ Poll ended.", ephemeral=True)
        except Exception:
            pass

        try:
            await refresh_poll_panel(interaction.guild, channel_id)
        except Exception:
            pass


# ----------------------- Starter Vault Admin Panel (staff) -----------------------
_STARTER_ADMIN_MESSAGE_ID_RUNTIME: int = int(STARTER_ADMIN_MESSAGE_ID) if _is_digit_id(STARTER_ADMIN_MESSAGE_ID) else 0

def _render_starter_admin_box() -> str:
    available = len(PINS_POOL)
    claimed = len(CLAIMS)
    storage = "Database" if DB_POOL else "CSV files"
    return _module_box(
        "STARTER VAULT ADMIN",
        [
            "Admin tools for managing the starter vault pool.",
            "",
            f"Available vaults : {available}",
            f"Claimed vaults   : {claimed}",
            f"Storage          : {storage}",
            "",
            "Use the buttons below to add or delete vaults from the pool.",
        ],
    )


class _StarterAdminAddModal(discord.ui.Modal, title="Add Vault"):
    vault_no = discord.ui.TextInput(
        label="Vault number (optional)",
        placeholder="Leave blank to auto-pick next available",
        required=False,
        max_length=6,
    )
    pin = discord.ui.TextInput(
        label="Vault PIN (optional)",
        placeholder="Leave blank to auto-generate",
        required=False,
        max_length=16,
    )
    note = discord.ui.TextInput(
        label="Note (optional)",
        placeholder="e.g. 'Re-stock batch 1'",
        required=False,
        max_length=60,
    )

    async def on_submit(self, interaction: discord.Interaction):
        if not is_staff_member(interaction.user):
            return await interaction.response.send_message("❌ Staff only.", ephemeral=True)

        # Pick vault number
        raw_no = (self.vault_no.value or "").strip()
        if raw_no:
            if not raw_no.isdigit():
                return await interaction.response.send_message("❌ Vault number must be a number.", ephemeral=True)
            box_no = int(raw_no)
            if box_no <= 0:
                return await interaction.response.send_message("❌ Vault number must be positive.", ephemeral=True)

            # Prevent collisions with pool or claimed vault numbers
            claimed_box_nos = {box for (box, _pin) in CLAIMS.values()}
            if box_no in PINS_POOL or box_no in claimed_box_nos:
                return await interaction.response.send_message(
                    f"❌ Vault #{box_no} is already in use (pool or claimed). Pick another number.",
                    ephemeral=True,
                )
        else:
            used = set(PINS_POOL.keys()) | {box for (box, _pin) in CLAIMS.values()}
            box_no = 1
            while box_no in used:
                box_no += 1

        # Pick PIN
        raw_pin = (self.pin.value or "").strip()
        if raw_pin:
            if not raw_pin.isdigit() or len(raw_pin) < 4:
                return await interaction.response.send_message(
                    "❌ PIN must be digits only (at least 4 digits).", ephemeral=True
                )
            new_pin = raw_pin
        else:
            existing_pins = {bp.pin for bp in PINS_POOL.values()} | {p for (_b, p) in CLAIMS.values()}
            # generate_new_pin() exists elsewhere in this file
            new_pin = generate_new_pin()
            tries = 0
            while new_pin in existing_pins and tries < 200:
                new_pin = generate_new_pin()
                tries += 1
            if new_pin in existing_pins:
                return await interaction.response.send_message(
                    "❌ Could not generate a unique PIN. Try again.", ephemeral=True
                )

        bp = BoxPin(box=box_no, pin=new_pin)
        PINS_POOL[box_no] = bp

        await save_pool_state()
        await ensure_starter_admin_panel(interaction.guild)

        return await interaction.response.send_message(
            f"✅ Added vault **#{box_no}** with PIN **{new_pin}**.",
            ephemeral=True,
        )


class _StarterAdminDeleteModal(discord.ui.Modal, title="Delete Vault"):
    vault_no = discord.ui.TextInput(
        label="Vault number to delete",
        placeholder="e.g. 12",
        required=True,
        max_length=6,
    )

    async def on_submit(self, interaction: discord.Interaction):
        if not is_staff_member(interaction.user):
            return await interaction.response.send_message("❌ Staff only.", ephemeral=True)

        raw_no = (self.vault_no.value or "").strip()
        if not raw_no.isdigit():
            return await interaction.response.send_message("❌ Vault number must be a number.", ephemeral=True)
        box_no = int(raw_no)

        if box_no in PINS_POOL:
            del PINS_POOL[box_no]
            await save_pool_state()
            await ensure_starter_admin_panel(interaction.guild)
            return await interaction.response.send_message(f"✅ Deleted unclaimed vault **#{box_no}**.", ephemeral=True)

        # If it is claimed, we intentionally block "delete" and ask to recycle instead
        claimed_box_nos = {box for (box, _pin) in CLAIMS.values()}
        if box_no in claimed_box_nos:
            return await interaction.response.send_message(
                f"⚠️ Vault **#{box_no}** is claimed. Use **Recycle Vault** to free and reuse it (owner stays ineligible).",
                ephemeral=True,
            )

        return await interaction.response.send_message(f"❌ Vault **#{box_no}** not found.", ephemeral=True)


class _StarterAdminRecycleModal(discord.ui.Modal, title="Recycle Claimed Vault"):
    vault_no = discord.ui.TextInput(
        label="Vault number to recycle",
        placeholder="e.g. 12",
        required=True,
        max_length=6,
    )
    confirm = discord.ui.TextInput(
        label='Type "RECYCLE" to confirm',
        placeholder="RECYCLE",
        required=True,
        max_length=16,
    )

    async def on_submit(self, interaction: discord.Interaction):
        if not is_staff_member(interaction.user):
            return await interaction.response.send_message("❌ Staff only.", ephemeral=True)

        if (self.confirm.value or "").strip().upper() != "RECYCLE":
            return await interaction.response.send_message("❌ Confirmation failed. Type RECYCLE to confirm.", ephemeral=True)

        raw_no = (self.vault_no.value or "").strip()
        if not raw_no.isdigit():
            return await interaction.response.send_message("❌ Vault number must be a number.", ephemeral=True)
        box_no = int(raw_no)

        # Find the claim for this vault number
        owner_id = None
        old_pin = None
        for uid, (b, p) in CLAIMS.items():
            if b == box_no:
                owner_id = uid
                old_pin = p
                break

        if owner_id is None:
            # If unclaimed, recycling is not needed (can delete instead)
            if box_no in PINS_POOL:
                return await interaction.response.send_message(
                    f"ℹ️ Vault **#{box_no}** is not claimed (it is in the pool). No need to recycle; use **Delete Vault** if you want to remove it.",
                    ephemeral=True,
                )
            return await interaction.response.send_message(
                f"❌ Vault **#{box_no}** not found in claims or pool.",
                ephemeral=True,
            )

        # Remove active claim but keep the user in CLAIMED_USERS (so they can't claim again)
        del CLAIMS[owner_id]
        await save_claims_only()

        # Generate a new unique pin and put the slot back into the pool
        existing_pins = {bp.pin for bp in PINS_POOL.values()} | {p for (_b, p) in CLAIMS.values()}
        new_pin = generate_new_pin()
        tries = 0
        while new_pin in existing_pins and tries < 200:
            new_pin = generate_new_pin()
            tries += 1
        if new_pin in existing_pins:
            return await interaction.response.send_message("❌ Could not generate a unique PIN. Try again.", ephemeral=True)

        PINS_POOL[box_no] = BoxPin(box=box_no, pin=new_pin)
        await save_pool_state()

        await ensure_starter_admin_panel(interaction.guild)

        # Do NOT mention/ping the old owner
        owner_name = str(owner_id)
        if interaction.guild:
            m = interaction.guild.get_member(owner_id)
            if m:
                owner_name = m.display_name

        return await interaction.response.send_message(
            f"✅ Recycled vault **#{box_no}** (old owner: **{owner_name}**). "
            f"New PIN generated: **{new_pin}**.\n"
            f"Old owner remains ineligible to claim again.",
            ephemeral=True,
        )


class StarterVaultAdminView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        # If this returns False without responding, Discord shows "Interaction Failed".
        if interaction.guild is None:
            try:
                await interaction.response.send_message("❌ This panel only works inside the server.", ephemeral=True)
            except Exception:
                pass
            return False

        if not is_staff_member(interaction.user):
            try:
                await interaction.response.send_message("🔒 Staff only.", ephemeral=True)
            except Exception:
                pass
            return False

        return True

    def _render_starter_admin_box(self) -> str:
        avail = len(PINS_POOL)
        claimed = len(CLAIMS)
        return (
            "[ STARTER VAULT ADMIN ]\n"
            "Admin tools for managing the starter vault pool.\n\n"
            f"Available vaults : {avail}\n"
            f"Claimed vaults   : {claimed}\n"
            "Storage          : Database\n\n"
            "Use the buttons below to add, delete, view, or recycle vaults.\n"
        )

    @discord.ui.button(label="Add Vault", style=discord.ButtonStyle.success, custom_id="starter_admin_add")
    async def add_vault(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(_StarterAdminAddModal())

    @discord.ui.button(label="Delete Vault", style=discord.ButtonStyle.danger, custom_id="starter_admin_delete")
    async def delete_vault(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(_StarterAdminDeleteModal())

    @discord.ui.button(label="Recycle Vault", style=discord.ButtonStyle.secondary, custom_id="starter_admin_recycle")
    async def recycle_vault(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(_StarterAdminRecycleModal())

    @discord.ui.button(label="View Claims", style=discord.ButtonStyle.primary, custom_id="starter_admin_claims")
    async def view_claims(self, interaction: discord.Interaction, button: discord.ui.Button):
        try:
            await interaction.response.defer(ephemeral=True)
        except Exception:
            pass

        if not CLAIMS:
            await interaction.followup.send("No starter vault claims yet.", ephemeral=True)
            return

        lines = []
        for uid, (vault_id, pin) in CLAIMS.items():
            m = interaction.guild.get_member(uid)
            name = m.display_name if m else f"User {uid}"
            lines.append(f"- {name} — Vault #{vault_id}")
        msg = "Starter vault claims:\n" + "\n".join(lines)
        await interaction.followup.send(msg, ephemeral=True)

    @discord.ui.button(label="Pool Count", style=discord.ButtonStyle.secondary, custom_id="starter_admin_poolcount")
    async def pool_count(self, interaction: discord.Interaction, button: discord.ui.Button):
        try:
            await interaction.response.defer(ephemeral=True)
        except Exception:
            pass
        avail = len(PINS_POOL)
        claimed = len(CLAIMS)
        await interaction.followup.send(f"Available vaults: {avail}\nClaimed vaults: {claimed}", ephemeral=True)

async def ensure_starter_admin_panel(guild: discord.Guild) -> None:
    """
    Ensures the Starter Vault Admin panel exists in STARTER_ADMIN_CHANNEL_ID.
    It will reuse the message in STARTER_ADMIN_MESSAGE_ID if set, otherwise it will
    try to find a matching pinned/recent message, and finally create a new one.
    """
    global _STARTER_ADMIN_MESSAGE_ID_RUNTIME

    ch_id = (STARTER_ADMIN_CHANNEL_ID or "").strip()
    if not _is_digit_id(ch_id):
        return

    embed = discord.Embed(
        title="Democracy Bot — Starter Vault Admin",
        description=_render_starter_admin_box(),
        color=0xFF8C00,
    )

    msg_id = await _ensure_panel_message(
        guild=guild,
        channel_id_str=ch_id,
        message_id_runtime_name="_STARTER_ADMIN_MESSAGE_ID_RUNTIME",
        embed=embed,
        view=StarterVaultAdminView(),
        pin=False,
        expected_embed_title="Democracy Bot — Starter Vault Admin",
    )

    if msg_id and msg_id != _STARTER_ADMIN_MESSAGE_ID_RUNTIME:
        _STARTER_ADMIN_MESSAGE_ID_RUNTIME = msg_id
        print(f"[STARTER-ADMIN] New STARTER_ADMIN_MESSAGE_ID = {msg_id} (save this in Railway Variables)", flush=True)


async def ensure_poll_panel(guild: discord.Guild) -> None:
    global _POLL_PANEL_MESSAGE_ID_RUNTIME

    ch_id = _poll_panel_channel_id()
    if not _is_digit_id(ch_id):
        return

    active = POLL_BY_CHANNEL.get(int(_poll_vote_channel_id())) if _is_digit_id(_poll_vote_channel_id()) else None
    msg_id = await _ensure_panel_message(
        guild=guild,
        channel_id_str=ch_id,
        message_id_runtime_name="_POLL_PANEL_MESSAGE_ID_RUNTIME",
        embed=_build_poll_panel_embed(active if active and not active.ended else None),
        view=PersistentPollPanelView(),
        pin=POLL_PANEL_PIN,
        expected_embed_title="📊 Democracy Bot — Poll Module",
    )
    if msg_id and msg_id != _POLL_PANEL_MESSAGE_ID_RUNTIME:
        _POLL_PANEL_MESSAGE_ID_RUNTIME = msg_id
        print(f"[POLL] New POLL_PANEL_MESSAGE_ID = {msg_id} (save this in Railway Variables)", flush=True)

async def refresh_poll_panel(guild: discord.Guild, vote_channel_id: int) -> None:
    global _POLL_PANEL_MESSAGE_ID_RUNTIME
    if not _POLL_PANEL_MESSAGE_ID_RUNTIME:
        return
    ch_id = _poll_panel_channel_id()
    ch = await _get_text_channel(guild, ch_id)
    if not ch:
        return
    try:
        msg = await ch.fetch_message(int(_POLL_PANEL_MESSAGE_ID_RUNTIME))
        active = POLL_BY_CHANNEL.get(int(vote_channel_id))
        await msg.edit(embed=_build_poll_panel_embed(active if active and not active.ended else None), view=PersistentPollPanelView())
    except Exception:
        pass



# =====================================================================
# ✅ NEW: Get-Role Panel (Visitor -> Survivor) + Role Manager (staff)
# =====================================================================

_GET_ROLE_MESSAGE_ID_RUNTIME: int = int(GET_ROLE_MESSAGE_ID) if _is_digit_id(GET_ROLE_MESSAGE_ID) else 0
_ROLE_MANAGER_MESSAGE_ID_RUNTIME: int = int(ROLE_MANAGER_MESSAGE_ID) if _is_digit_id(ROLE_MANAGER_MESSAGE_ID) else 0
_TAME_CALC_MESSAGE_ID_RUNTIME: int = int(TAME_CALC_MESSAGE_ID) if _is_digit_id(TAME_CALC_MESSAGE_ID) else 0
_CALC_SETTINGS_MESSAGE_ID_RUNTIME: int = int(CALC_SETTINGS_MESSAGE_ID) if _is_digit_id(CALC_SETTINGS_MESSAGE_ID) else 0


def _role_manager_channel_id() -> str:
    # Default to the existing server control panel channel if not specified
    if _is_digit_id(ROLE_MANAGER_CHANNEL_ID):
        return ROLE_MANAGER_CHANNEL_ID
    return SERVER_CONTROL_CHANNEL_ID

def _build_get_role_embed(guild: discord.Guild) -> discord.Embed:
    survivor = "<not set>"
    if _is_digit_id(SURVIVOR_ROLE_ID):
        r = guild.get_role(int(SURVIVOR_ROLE_ID))
        survivor = r.name if r else f"{SURVIVOR_ROLE_ID}"
    lines = [
        "🧭 New here? You're a **Visitor** until you've created your character in-game.",
        "",
        "✅ Once you've spawned in and you're established, press the button below to unlock:",
        f"• **{survivor}**",
        "",
        "If you need help first, open a ticket in **#open-a-ticket**.",
    ]
    e = discord.Embed(
        title="🧬 Democracy Bot — Get Roles",
        description=_module_box("GET ROLE", lines),
        color=0x9B59B6,
    )
    e.set_footer(text="If the button fails, ensure the bot role is above the Survivor role and has Manage Roles.")
    e.timestamp = datetime.utcnow()
    return e

def _build_role_manager_embed(guild: discord.Guild) -> discord.Embed:
    count = len(SELF_ROLES)
    lines = [
        "🔧 Manage which roles the bot can hand out (self-assign roles list).",
        "",
        f"Self-assign roles configured : {count}",
        "",
        "Buttons:",
        "• Add Role — add an existing Discord role to the self-assign list",
        "• Remove Role — remove from list",
        "• List Roles — view configured roles",
    ]
    e = discord.Embed(
        title="🧩 Democracy Bot — Role Manager (Staff)",
        description=_module_box("ROLE MANAGER", lines),
        color=0x1ABC9C,
    )
    e.timestamp = datetime.utcnow()
    return e

def _parse_role_id(raw: str) -> Optional[int]:
    s = (raw or "").strip()
    if not s:
        return None
    m = re.match(r"^<@&(\d+)>$", s)
    if m:
        return int(m.group(1))
    if s.isdigit():
        return int(s)
    return None

class GetRoleView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if not interaction.guild or not isinstance(interaction.user, discord.Member):
            try:
                if interaction.response.is_done():
                    await interaction.followup.send("❌ Server context required.", ephemeral=True)
                else:
                    await interaction.response.send_message("❌ Server context required.", ephemeral=True)
            except Exception:
                pass
            return False
        return True

    @discord.ui.button(label="I’m established in-game (Get Survivor)", style=discord.ButtonStyle.success, custom_id="getrole_survivor_toggle")
    async def survivor_btn(self, interaction: discord.Interaction, _: discord.ui.Button):
        if not interaction.guild or not isinstance(interaction.user, discord.Member):
            return
        if not _is_digit_id(SURVIVOR_ROLE_ID):
            return await interaction.response.send_message("❌ SURVIVOR_ROLE_ID is not set in Railway.", ephemeral=True)

        role = interaction.guild.get_role(int(SURVIVOR_ROLE_ID))
        if not role:
            return await interaction.response.send_message("❌ Survivor role not found in this server.", ephemeral=True)

        try:
            if role in interaction.user.roles:
                await interaction.user.remove_roles(role, reason="Democracy Bot: self-toggle Survivor")
                await interaction.response.send_message(f"✅ Removed **{role.name}**.", ephemeral=True)
            else:
                await interaction.user.add_roles(role, reason="Democracy Bot: self-toggle Survivor")
                await interaction.response.send_message(f"✅ You now have **{role.name}**. Welcome!", ephemeral=True)
        except discord.Forbidden:
            await interaction.response.send_message(
                "❌ I can't manage that role. Ensure my bot role is ABOVE the Survivor role and I have **Manage Roles**.",
                ephemeral=True,
            )
        except Exception as e:
            await interaction.response.send_message(f"❌ Failed: {type(e).__name__}: {e}", ephemeral=True)

class _RoleAddModal(discord.ui.Modal, title="Add self-assign role"):
    role_id_or_mention = discord.ui.TextInput(
        label="Role ID or @Role mention",
        required=True,
        max_length=64,
        placeholder="1234567890 or <@&1234567890>",
    )
    label = discord.ui.TextInput(
        label="Button label (optional)",
        required=False,
        max_length=60,
        placeholder="e.g. Builder",
    )
    description = discord.ui.TextInput(
        label="Description (optional)",
        required=False,
        max_length=120,
        placeholder="e.g. For community builders",
    )

    async def on_submit(self, interaction: discord.Interaction):
        if not interaction.guild or not isinstance(interaction.user, discord.Member):
            return await interaction.response.send_message("❌ Server context required.", ephemeral=True)
        if not is_staff_member(interaction.user):
            return await interaction.response.send_message("❌ Staff only.", ephemeral=True)

        rid = _parse_role_id(str(self.role_id_or_mention.value or ""))
        if not rid:
            return await interaction.response.send_message("❌ Invalid role ID/mention.", ephemeral=True)

        role = interaction.guild.get_role(int(rid))
        if not role:
            return await interaction.response.send_message("❌ That role doesn't exist in this server.", ephemeral=True)

        if _is_digit_id(SURVIVOR_ROLE_ID) and int(rid) == int(SURVIVOR_ROLE_ID):
            return await interaction.response.send_message("ℹ️ Survivor is managed by the Get-Role panel, not the self-role list.", ephemeral=True)

        lab = str(self.label.value or "").strip() or role.name
        desc = str(self.description.value or "").strip()

        global SELF_ROLES
        SELF_ROLES[int(rid)] = (lab, desc)

        if DB_POOL is not None:
            try:
                await db_upsert_self_role(int(rid), lab, desc)
            except Exception:
                pass
        else:
            await save_self_roles_only()

        try:
            await ensure_role_manager_panel(interaction.guild)
            await ensure_self_roles_panel(interaction.guild)
        except Exception:
            pass

        await interaction.response.send_message(f"✅ Added **{role.name}** to self-assign roles.", ephemeral=True)

class _RoleRemoveModal(discord.ui.Modal, title="Remove self-assign role"):
    role_id_or_mention = discord.ui.TextInput(
        label="Role ID or @Role mention",
        required=True,
        max_length=64,
        placeholder="1234567890 or <@&1234567890>",
    )

    async def on_submit(self, interaction: discord.Interaction):
        if not interaction.guild or not isinstance(interaction.user, discord.Member):
            return await interaction.response.send_message("❌ Server context required.", ephemeral=True)
        if not is_staff_member(interaction.user):
            return await interaction.response.send_message("❌ Staff only.", ephemeral=True)

        rid = _parse_role_id(str(self.role_id_or_mention.value or ""))
        if not rid:
            return await interaction.response.send_message("❌ Invalid role ID/mention.", ephemeral=True)

        global SELF_ROLES
        if int(rid) not in SELF_ROLES:
            return await interaction.response.send_message("ℹ️ That role is not in the self-assign list.", ephemeral=True)

        SELF_ROLES.pop(int(rid), None)

        if DB_POOL is not None:
            try:
                await db_delete_self_role(int(rid))
            except Exception:
                pass
        else:
            await save_self_roles_only()

        try:
            await ensure_role_manager_panel(interaction.guild)
            await ensure_self_roles_panel(interaction.guild)
        except Exception:
            pass

        await interaction.response.send_message("✅ Removed from self-assign list.", ephemeral=True)

class SelfRolesView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)
        self._build()

    def _build(self):
        self.clear_items()
        items = list(SELF_ROLES.items())[:20]
        for rid, (label, _desc) in items:
            self.add_item(_SelfRoleButton(role_id=int(rid), label=label))

class _SelfRoleButton(discord.ui.Button):
    def __init__(self, role_id: int, label: str):
        super().__init__(
            label=(label[:80] if label else f"Role {role_id}"),
            style=discord.ButtonStyle.secondary,
            custom_id=f"selfrole_toggle_{role_id}",
        )
        self.role_id = int(role_id)

    async def callback(self, interaction: discord.Interaction):
        if not interaction.guild or not isinstance(interaction.user, discord.Member):
            return
        role = interaction.guild.get_role(self.role_id)
        if not role:
            return await interaction.response.send_message("❌ Role no longer exists.", ephemeral=True)

        try:
            if role in interaction.user.roles:
                await interaction.user.remove_roles(role, reason="Democracy Bot: self-role toggle")
                await interaction.response.send_message(f"✅ Removed **{role.name}**.", ephemeral=True)
            else:
                await interaction.user.add_roles(role, reason="Democracy Bot: self-role toggle")
                await interaction.response.send_message(f"✅ Added **{role.name}**.", ephemeral=True)
        except discord.Forbidden:
            await interaction.response.send_message(
                "❌ I can't manage that role. Ensure my bot role is ABOVE the target role and I have **Manage Roles**.",
                ephemeral=True,
            )
        except Exception as e:
            await interaction.response.send_message(f"❌ Failed: {type(e).__name__}: {e}", ephemeral=True)

def _build_self_roles_embed() -> discord.Embed:
    if not SELF_ROLES:
        lines = [
            "No self-assign roles have been configured yet.",
            "",
            "Staff can add roles using the Role Manager module.",
        ]
    else:
        lines = ["Press a button to toggle a role:", ""]
        for rid, (label, desc) in list(SELF_ROLES.items())[:20]:
            d = f" — {desc}" if desc else ""
            lines.append(f"• {label}{d}")
        if len(SELF_ROLES) > 20:
            lines.append("…and more (limit 20 buttons per panel).")
    e = discord.Embed(
        title="🏷️ Democracy Bot — Self Roles",
        description=_module_box("SELF ROLES", lines),
        color=0x95A5A6,
    )
    e.timestamp = datetime.utcnow()
    return e

async def ensure_get_role_panel(guild: discord.Guild) -> None:
    global _GET_ROLE_MESSAGE_ID_RUNTIME
    if not _is_digit_id(GET_ROLE_CHANNEL_ID):
        return

    msg_id = await _ensure_panel_message(
        guild=guild,
        channel_id_str=GET_ROLE_CHANNEL_ID,
        message_id_runtime_name="_GET_ROLE_MESSAGE_ID_RUNTIME",
        embed=_build_get_role_embed(guild),
        view=GetRoleView(),
        pin=False,
        expected_embed_title="🧬 Democracy Bot — Get Roles",
    )
    if msg_id and msg_id != _GET_ROLE_MESSAGE_ID_RUNTIME:
        _GET_ROLE_MESSAGE_ID_RUNTIME = msg_id
        print(f"[GET-ROLE] New GET_ROLE_MESSAGE_ID = {msg_id} (save this in Railway Variables)", flush=True)

async def ensure_self_roles_panel(guild: discord.Guild) -> None:
    if not _is_digit_id(GET_ROLE_CHANNEL_ID):
        return
    await _ensure_panel_message(
        guild=guild,
        channel_id_str=GET_ROLE_CHANNEL_ID,
        message_id_runtime_name="__unused_self_roles_msg_id_runtime",
        embed=_build_self_roles_embed(),
        view=SelfRolesView(),
        pin=False,
        expected_embed_title="🏷️ Democracy Bot — Self Roles",
    )

class RoleManagerView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if not interaction.guild or not isinstance(interaction.user, discord.Member):
            try:
                if interaction.response.is_done():
                    await interaction.followup.send("❌ Server context required.", ephemeral=True)
                else:
                    await interaction.response.send_message("❌ Server context required.", ephemeral=True)
            except Exception:
                pass
            return False
        if not is_staff_member(interaction.user):
            try:
                if interaction.response.is_done():
                    await interaction.followup.send("🔒 Staff only.", ephemeral=True)
                else:
                    await interaction.response.send_message("🔒 Staff only.", ephemeral=True)
            except Exception:
                pass
            return False
        return True

    @discord.ui.button(label="Add Role", style=discord.ButtonStyle.success, custom_id="roleman_add")
    async def add_btn(self, interaction: discord.Interaction, _: discord.ui.Button):
        await interaction.response.send_modal(_RoleAddModal())

    @discord.ui.button(label="Remove Role", style=discord.ButtonStyle.danger, custom_id="roleman_remove")
    async def remove_btn(self, interaction: discord.Interaction, _: discord.ui.Button):
        await interaction.response.send_modal(_RoleRemoveModal())

    @discord.ui.button(label="List Roles", style=discord.ButtonStyle.secondary, custom_id="roleman_list")
    async def list_btn(self, interaction: discord.Interaction, _: discord.ui.Button):
        if not interaction.guild:
            return
        if not SELF_ROLES:
            return await interaction.response.send_message("No self-assign roles configured.", ephemeral=True)

        lines = []
        for rid, (label, desc) in SELF_ROLES.items():
            role = interaction.guild.get_role(int(rid))
            name = role.name if role else f"<missing:{rid}>"
            extra = f" — {desc}" if desc else ""
            lines.append(f"• {name} (`{rid}`) — label: {label}{extra}")
        await interaction.response.send_message("\n".join(lines)[:1900], ephemeral=True)

    @discord.ui.button(label="Refresh Panels", style=discord.ButtonStyle.primary, custom_id="roleman_refresh")
    async def refresh_btn(self, interaction: discord.Interaction, _: discord.ui.Button):
        if not interaction.guild:
            return
        try:
            await ensure_role_manager_panel(interaction.guild)
            await ensure_get_role_panel(interaction.guild)
            await ensure_self_roles_panel(interaction.guild)
        except Exception:
            pass
        await interaction.response.send_message("✅ Refreshed role panels.", ephemeral=True)

async def ensure_role_manager_panel(guild: discord.Guild) -> None:
    global _ROLE_MANAGER_MESSAGE_ID_RUNTIME

    ch_id = _role_manager_channel_id()
    if not _is_digit_id(ch_id):
        return

    msg_id = await _ensure_panel_message(
        guild=guild,
        channel_id_str=ch_id,
        message_id_runtime_name="_ROLE_MANAGER_MESSAGE_ID_RUNTIME",
        embed=_build_role_manager_embed(guild),
        view=RoleManagerView(),
        pin=ROLE_MANAGER_PIN,
        expected_embed_title="🧩 Democracy Bot — Role Manager (Staff)",
    )
    if msg_id and msg_id != _ROLE_MANAGER_MESSAGE_ID_RUNTIME:
        _ROLE_MANAGER_MESSAGE_ID_RUNTIME = msg_id
        print(f"[ROLEMAN] New ROLE_MANAGER_MESSAGE_ID = {msg_id} (save this in Railway Variables)", flush=True)

# =====================================================================
# ✅ NEW: Tame Calculator (public) + Calc Settings (staff)
# =====================================================================

@dataclass
class CalcSettings:
    taming_speed: float = 5.0
    food_drain: float = 1.0
    use_single_player_settings: bool = False

async def calc_get_settings(guild_id: int) -> CalcSettings:
    """Fetch calc settings from DB; fall back to defaults if missing."""
    if not DB_POOL:
        return CalcSettings()
    try:
        async with DB_POOL.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT taming_speed, food_drain, use_single_player_settings
                FROM calc_settings
                WHERE guild_id = $1
                """,
                guild_id,
            )
            if not row:
                # Create default row lazily
                await conn.execute(
                    """
                    INSERT INTO calc_settings (guild_id, taming_speed, food_drain, use_single_player_settings, updated_at)
                    VALUES ($1, $2, $3, $4, $5)
                    ON CONFLICT (guild_id) DO NOTHING
                    """,
                    guild_id,
                    float(CalcSettings.taming_speed),
                    float(CalcSettings.food_drain),
                    bool(CalcSettings.use_single_player_settings),
                    int(time.time()),
                )
                return CalcSettings()
            return CalcSettings(
                taming_speed=float(row["taming_speed"]) if row["taming_speed"] is not None else 5.0,
                food_drain=float(row["food_drain"]) if row["food_drain"] is not None else 1.0,
                use_single_player_settings=bool(row["use_single_player_settings"]) if row["use_single_player_settings"] is not None else False,
            )
    except Exception:
        return CalcSettings()

async def calc_set_settings(guild_id: int, settings: CalcSettings) -> None:
    if not DB_POOL:
        return
    try:
        async with DB_POOL.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO calc_settings (guild_id, taming_speed, food_drain, use_single_player_settings, updated_at)
                VALUES ($1, $2, $3, $4, $5)
                ON CONFLICT (guild_id) DO UPDATE
                SET taming_speed = EXCLUDED.taming_speed,
                    food_drain = EXCLUDED.food_drain,
                    use_single_player_settings = EXCLUDED.use_single_player_settings,
                    updated_at = EXCLUDED.updated_at
                """,
                guild_id,
                float(settings.taming_speed),
                float(settings.food_drain),
                bool(settings.use_single_player_settings),
                int(time.time()),
            )
    except Exception:
        pass

def _find_channel_by_name(guild: discord.Guild, name: str) -> Optional[discord.TextChannel]:
    for ch in guild.text_channels:
        if ch.name.lower() == name.lower():
            return ch
    return None

async def _resolve_text_channel(guild: discord.Guild, channel_id_str: str, fallback_name: str) -> Optional[discord.TextChannel]:
    ch = await _get_text_channel(guild, channel_id_str) if _is_digit_id(channel_id_str) else None
    if ch:
        return ch
    return _find_channel_by_name(guild, fallback_name)

def _slugify_creature(name: str) -> str:
    s = name.strip().lower()
    s = re.sub(r"\s+", "-", s)
    s = re.sub(r"[^a-z0-9\-]", "", s)
    s = re.sub(r"\-+", "-", s).strip("-")
    return s

def _build_tame_calc_embed(guild: discord.Guild, settings: CalcSettings) -> discord.Embed:
    lines = [
        f"Taming Speed: **{settings.taming_speed}x**",
        f"Food Drain: **{settings.food_drain}x**",
        f"Single Player Settings: **{'ON' if settings.use_single_player_settings else 'OFF'}**",
        "Use **Calculate** below to get food, time, narcotics, and a KO estimate (based on standard weapon damage).",
    ]
    e = discord.Embed(
        title="🦖 Democracy Ark — Tame Calculator",
        description=_module_box("TAME CALCULATOR", lines),
        color=0x2ECC71,
    )
    e.set_footer(text="Powered by your server rates • Ragnarok")
    e.timestamp = datetime.utcnow()
    return e

def _build_calc_settings_embed(guild: discord.Guild, settings: CalcSettings) -> discord.Embed:
    lines = [
        f"Taming Speed: **{settings.taming_speed}x**",
        f"Food Drain: **{settings.food_drain}x**",
        f"Single Player Settings: **{'ON' if settings.use_single_player_settings else 'OFF'}**",
        "Staff: update these so the public calculator panel stays accurate.",
        "(Uses DB if available; otherwise defaults are used.)",
    ]
    e = discord.Embed(
        title="⚙️ Democracy Bot — Calculator Settings (Staff)",
        description=_module_box("CALC SETTINGS", lines),
        color=0xF1C40F,
    )
    e.timestamp = datetime.utcnow()
    return e

class _CalcSettingsModal(discord.ui.Modal, title="Set Calculator Rates"):
    taming_speed = discord.ui.TextInput(label="Taming Speed (e.g. 5)", placeholder="5", required=True, max_length=10)
    food_drain = discord.ui.TextInput(label="Food Drain (e.g. 1)", placeholder="1", required=True, max_length=10)
    single_player = discord.ui.TextInput(label="Use Single Player Settings? (yes/no)", placeholder="no", required=True, max_length=10)

    async def on_submit(self, interaction: discord.Interaction):
        try:
            ts = float(str(self.taming_speed.value).strip())
        except Exception:
            ts = 5.0
        try:
            fd = float(str(self.food_drain.value).strip())
        except Exception:
            fd = 1.0
        sp = str(self.single_player.value).strip().lower() in ("1", "true", "yes", "y", "on")
        await calc_set_settings(interaction.guild_id, CalcSettings(taming_speed=ts, food_drain=fd, use_single_player_settings=sp))
        # refresh both panels
        try:
            await ensure_calc_settings_panel(interaction.guild)
            await ensure_tame_calculator_panel(interaction.guild)
        except Exception:
            pass
        await interaction.response.send_message("✅ Calculator settings updated.", ephemeral=True)

class CalcSettingsView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if not interaction.guild or not isinstance(interaction.user, discord.Member):
            try:
                if interaction.response.is_done():
                    await interaction.followup.send("❌ Server context required.", ephemeral=True)
                else:
                    await interaction.response.send_message("❌ Server context required.", ephemeral=True)
            except Exception:
                pass
            return False
        if not is_staff_member(interaction.user):
            try:
                if interaction.response.is_done():
                    await interaction.followup.send("🔒 Staff only.", ephemeral=True)
                else:
                    await interaction.response.send_message("🔒 Staff only.", ephemeral=True)
            except Exception:
                pass
            return False
        return True

    @discord.ui.button(label="Set Rates", style=discord.ButtonStyle.primary, custom_id="calc_settings:set_rates")
    async def set_rates(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(_CalcSettingsModal())

    @discord.ui.button(label="Reset to Defaults", style=discord.ButtonStyle.secondary, custom_id="calc_settings:reset_defaults")
    async def reset_defaults(self, interaction: discord.Interaction, button: discord.ui.Button):
        await calc_set_settings(interaction.guild_id, CalcSettings())
        try:
            await ensure_calc_settings_panel(interaction.guild)
            await ensure_tame_calculator_panel(interaction.guild)
        except Exception:
            pass
        await interaction.response.send_message("✅ Reset to defaults.", ephemeral=True)

# ---- Taming data (auto-loaded from ARK Wiki/Fandom Module:TamingTable) ----
_TAMING_CREATURES: Optional[Dict[str, Any]] = None
_TAMING_FOOD: Optional[Dict[str, Any]] = None
_TAMING_LOADED_AT: int = 0
_TAMING_LOCK = asyncio.Lock()

_TAMING_CREATURES_RAW_URL = "https://ark.fandom.com/wiki/Module:TamingTable/creatures?action=raw"
_TAMING_FOOD_RAW_URL = "https://ark.fandom.com/wiki/Module:TamingTable/food?action=raw"

async def _fetch_text(url: str, timeout_s: int = 25) -> str:
    timeout = aiohttp.ClientTimeout(total=timeout_s)
    async with aiohttp.ClientSession(timeout=timeout) as session:
        async with session.get(url, headers={"User-Agent": "DemocracyBot/1.0"}) as resp:
            resp.raise_for_status()
            return await resp.text()

def _lua_strip_comments(src: str) -> str:
    # Modules are usually comment-light; keep simple: strip full-line and inline "--" comments.
    out_lines: List[str] = []
    for line in src.splitlines():
        if "--" in line:
            # keep strings safe by only stripping when '--' appears before any quote
            dq = line.find('"')
            sq = line.find("'")
            first_quote = min([x for x in [dq, sq] if x != -1], default=-1)
            comment_at = line.find("--")
            if comment_at != -1 and (first_quote == -1 or comment_at < first_quote):
                line = line[:comment_at]
        if line.strip().startswith("--"):
            continue
        out_lines.append(line)
    return "\n".join(out_lines)

_LUA_TOKEN_RE = re.compile(
    r'\s*(?:(\{)|(\})|(\[)|(\])|(=)|(,)|("([^"\\]|\\.)*")|(-?\d+\.\d+|-?\d+)|(\btrue\b|\bfalse\b|\bnil\b)|([A-Za-z_][A-Za-z0-9_]*))',
    re.IGNORECASE,
)

def _lua_tokenize(src: str) -> List[str]:
    tokens: List[str] = []
    i = 0
    n = len(src)
    while i < n:
        m = _LUA_TOKEN_RE.match(src, i)
        if not m:
            # skip unknown whitespace/characters (should be rare in these modules)
            i += 1
            continue
        tok = next((g for g in m.groups() if g is not None), None)
        if tok is not None:
            tokens.append(tok)
        i = m.end()
    return tokens

def _lua_unescape_string(s: str) -> str:
    # s includes surrounding quotes
    try:
        return bytes(s[1:-1], "utf-8").decode("unicode_escape")
    except Exception:
        return s[1:-1]

def _lua_parse_value(tokens: List[str], idx: int):
    if idx >= len(tokens):
        raise ValueError("Unexpected EOF")
    t = tokens[idx]
    if t == "{":
        return _lua_parse_table(tokens, idx + 1)
    if t.startswith('"') and t.endswith('"'):
        return _lua_unescape_string(t), idx + 1
    if re.fullmatch(r"-?\d+\.\d+|-?\d+", t):
        return float(t) if "." in t else int(t), idx + 1
    tl = t.lower()
    if tl == "true":
        return True, idx + 1
    if tl == "false":
        return False, idx + 1
    if tl == "nil":
        return None, idx + 1
    # identifier as bare string (rare)
    return t, idx + 1

def _lua_parse_table(tokens: List[str], idx: int):
    items: List[Any] = []
    d: Dict[Any, Any] = {}
    keyed = False

    while idx < len(tokens):
        t = tokens[idx]
        if t == "}":
            return (d if keyed else items), idx + 1

        # keyed entry: ["key"] = value
        if t == "[":
            key_val, idx = _lua_parse_value(tokens, idx + 1)
            if tokens[idx] != "]":
                raise ValueError("Expected ']'")
            if tokens[idx + 1] != "=":
                raise ValueError("Expected '='")
            val, idx2 = _lua_parse_value(tokens, idx + 2)
            d[key_val] = val
            keyed = True
            idx = idx2
        # keyed entry: ident = value  (rare here)
        elif re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", t) and (idx + 1 < len(tokens) and tokens[idx + 1] == "="):
            key = t
            val, idx2 = _lua_parse_value(tokens, idx + 2)
            d[key] = val
            keyed = True
            idx = idx2
        else:
            val, idx2 = _lua_parse_value(tokens, idx)
            items.append(val)
            idx = idx2

        # optional comma
        if idx < len(tokens) and tokens[idx] == ",":
            idx += 1

    raise ValueError("Unclosed table")

def _lua_parse_return_table(lua_src: str) -> Dict[str, Any]:
    # Find the "return { ... }" segment and parse its table.
    src = _lua_strip_comments(lua_src)
    m = re.search(r"\breturn\s*\{", src)
    if not m:
        raise ValueError("No return table found")
    start = m.end() - 1  # points at '{'
    tokens = _lua_tokenize(src[start:])
    value, next_idx = _lua_parse_value(tokens, 0)
    if not isinstance(value, dict):
        raise ValueError("Expected dict at top level")
    return value

async def ensure_taming_data_loaded(force: bool = False) -> bool:
    global _TAMING_CREATURES, _TAMING_FOOD, _TAMING_LOADED_AT
    # refresh every 7 days (or on demand)
    if not force and _TAMING_CREATURES and _TAMING_FOOD and (time.time() - _TAMING_LOADED_AT) < 7 * 24 * 3600:
        return True
    async with _TAMING_LOCK:
        if not force and _TAMING_CREATURES and _TAMING_FOOD and (time.time() - _TAMING_LOADED_AT) < 7 * 24 * 3600:
            return True
        try:
            creatures_src, food_src = await asyncio.gather(
                _fetch_text(_TAMING_CREATURES_RAW_URL),
                _fetch_text(_TAMING_FOOD_RAW_URL),
            )
            _TAMING_CREATURES = _lua_parse_return_table(creatures_src)
            _TAMING_FOOD = _lua_parse_return_table(food_src)
            _TAMING_LOADED_AT = int(time.time())
            print(f"✅ TAME: loaded {len(_TAMING_CREATURES)} creatures + {len(_TAMING_FOOD)} foods from wiki modules.", flush=True)
            return True
        except Exception:
            print("⚠️ TAME: failed to load wiki taming data, falling back to link-only mode.\n" + traceback.format_exc(), flush=True)
            _TAMING_CREATURES = None
            _TAMING_FOOD = None
            return False

def _normalize_name(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", s.strip().lower())

def _resolve_creature_key(user_input: str) -> Optional[str]:
    if not _TAMING_CREATURES:
        return None
    want = _normalize_name(user_input)
    if not want:
        return None
    # exact-ish match first
    for k in _TAMING_CREATURES.keys():
        if _normalize_name(k) == want:
            return k
    # contains match
    for k in _TAMING_CREATURES.keys():
        nk = _normalize_name(k)
        if want in nk or nk in want:
            return k
    # very small fuzzy: first 8 chars
    want8 = want[:8]
    for k in _TAMING_CREATURES.keys():
        if _normalize_name(k).startswith(want8):
            return k
    return None

def _pick_food(creature_data: Dict[str, Any], food_pref: str) -> Optional[str]:
    eats = creature_data.get("eats") or []
    if not isinstance(eats, list):
        return None
    pref = food_pref.strip().lower()
    if not pref:
        # default: kibble if available, else first listed
        if "Kibble" in eats:
            return "Kibble"
        return eats[0] if eats else None

    # simple keyword mapping
    mapping = {
        "kibble": "Kibble",
        "mutton": "Raw Mutton",
        "prime": "Raw Prime Meat",
        "raw prime": "Raw Prime Meat",
        "prime meat": "Raw Prime Meat",
        "raw meat": "Raw Meat",
        "meat": "Raw Meat",
        "fish": "Raw Fish Meat",
        "prime fish": "Raw Prime Fish Meat",
        "berry": "Mejoberry",
        "berries": "Mejoberry",
        "mejo": "Mejoberry",
        "crop": "Vegetables",
        "vegetable": "Vegetables",
        "veggie": "Vegetables",
        "spoiled": "Spoiled Meat",
        "cake": "Sweet Vegetable Cake",
    }
    for key, val in mapping.items():
        if key in pref:
            if val in eats:
                return val
    # direct match against eats
    for f in eats:
        if pref == str(f).strip().lower():
            return f
    # contains match
    for f in eats:
        if pref in str(f).lower():
            return f
    return eats[0] if eats else None

def _format_hms(seconds: int) -> str:
    seconds = max(0, int(seconds))
    h = seconds // 3600
    m = (seconds % 3600) // 60
    s = seconds % 60
    if h:
        return f"{h}h {m}m {s}s"
    if m:
        return f"{m}m {s}s"
    return f"{s}s"

def _weapon_from_text(s: str) -> str:
    t = (s or "").lower()
    if "shocking" in t:
        return "shocking_dart"
    if "dart" in t or "longneck" in t or "rifle" in t:
        return "tranq_dart"
    if "crossbow" in t:
        return "crossbow_arrow"
    if "bow" in t:
        return "bow_arrow"
    if "club" in t:
        return "club"
    return "crossbow_arrow"

_WEAPON_TORPOR_100 = {
    # Totals at 100% weapon damage from ARK wiki comparison table.
    "bow_arrow": 90.0,
    "crossbow_arrow": 157.5,
    "tranq_dart": 221.0,
    "shocking_dart": 442.0,
    # A rough placeholder (varies a lot); keep but label as estimate.
    "club": 50.0,
}

def _weapon_label(key: str) -> str:
    return {
        "bow_arrow": "Bow + Tranq Arrow",
        "crossbow_arrow": "Crossbow + Tranq Arrow",
        "tranq_dart": "Longneck + Tranq Dart",
        "shocking_dart": "Longneck + Shocking Tranq Dart",
        "club": "Wooden Club (rough estimate)",
    }.get(key, key)

def _compute_taming(creature_key: str, level: int, settings: CalcSettings, food_pref: str, weapon_text: str, weapon_damage_pct: float):
    """Compute food/time/torpor/narcotics using the same parameters as the wiki TamingTable module, adjusted for server multipliers."""
    if not _TAMING_CREATURES or not _TAMING_FOOD:
        raise RuntimeError("taming data not loaded")

    c = _TAMING_CREATURES.get(creature_key)
    if not isinstance(c, dict):
        raise RuntimeError("unknown creature")

    level = max(1, int(level))
    taming_speed = max(0.1, float(settings.taming_speed or 1.0))
    food_drain_mult = max(0.1, float(settings.food_drain or 1.0))

    # required affinity
    affinity_needed = float(c.get("affinityNeeded0", 0)) + float(c.get("affinityIncrease", 0)) * float(level)

    # pick food
    food_key = _pick_food(c, food_pref) or ""
    foodname_disp = food_key
    if food_key == "Kibble":
        fav = c.get("favoriteKibble") or "Kibble"
        foodname_disp = f"{fav} Kibble"

    # resolve affinity + foodValue
    food_affinity = 0.0
    food_value = 0.0
    sfv = c.get("specialFoodValues") or {}
    if isinstance(sfv, dict) and food_key in sfv and isinstance(sfv[food_key], dict):
        food_affinity = float(sfv[food_key].get("affinity") or 0.0)
        food_value = float(sfv[food_key].get("value") or 0.0)

    fdat = _TAMING_FOOD.get(food_key) if isinstance(_TAMING_FOOD, dict) else None
    if isinstance(fdat, dict):
        if food_affinity == 0.0:
            food_affinity = float(fdat.get("affinity") or 0.0)
        if food_value == 0.0:
            food_value = float(fdat.get("foodValue") or 0.0)

    if food_affinity <= 0 or food_value == 0:
        raise RuntimeError("unsupported food for this creature")

    # wiki module multiplies affinity by 4 (post-2020 change)
    non_violent = bool(c.get("nonViolentTame") == 1)
    wake_aff_mult = float(c.get("wakeAffinityMult") or 1.0) if non_violent else 1.0
    wake_food_mult = float(c.get("wakeFoodDeplMult") or 1.0) if non_violent else 1.0

    food_affinity_eff = food_affinity * wake_aff_mult * 4.0 * taming_speed
    food_value_eff = food_value * wake_food_mult

    food_pieces = int(math.ceil(affinity_needed / food_affinity_eff))

    # time: either constantFeedingInterval, else based on food drain
    if c.get("constantFeedingInterval") is not None:
        seconds = int(float(c.get("constantFeedingInterval")) * food_pieces)
    else:
        base = float(c.get("foodConsumptionBase") or 0.0)
        mult = float(c.get("foodConsumptionMult") or 0.0)
        denom = base * mult * food_drain_mult
        if denom <= 0:
            seconds = 0
        else:
            seconds = int(math.ceil(food_pieces * abs(food_value_eff) / denom))

    # correction hacks used on wiki
    if c.get("resultCorrection") is not None:
        try:
            seconds = int(float(seconds) * float(c.get("resultCorrection")))
        except Exception:
            pass

    # torpor + narcos only for KO tames
    torpor_block = None
    if not non_violent:
        total_torpor = float(c.get("torpor1") or 0.0) + float(c.get("torporIncrease") or 0.0) * float(level - 1)
        torpor_ps0 = float(c.get("torporDepletionPS0") or 0.0)
        torpor_depl_ps = 0.0
        if torpor_ps0 > 0 and level > 1:
            torpor_depl_ps = torpor_ps0 + math.exp(0.800403041 * math.log(level - 1)) / (22.39671632 / torpor_ps0)
        elif torpor_ps0 > 0:
            torpor_depl_ps = torpor_ps0

        torpor_needed = max(0, int(math.ceil(torpor_depl_ps * seconds - total_torpor))) if torpor_depl_ps > 0 else 0

        narco_berries = int(math.ceil(torpor_needed / (7.5 + 3 * torpor_depl_ps))) if torpor_depl_ps > 0 else 0
        narcotics = int(math.ceil(torpor_needed / (40 + 8 * torpor_depl_ps))) if torpor_depl_ps > 0 else 0
        bio_toxin = int(math.ceil(torpor_needed / (80 + 16 * torpor_depl_ps))) if torpor_depl_ps > 0 else 0

        # KO estimate
        weapon_key = _weapon_from_text(weapon_text)
        base_torpor = float(_WEAPON_TORPOR_100.get(weapon_key) or 0.0)
        dmg_mult = max(0.1, float(weapon_damage_pct or 100.0) / 100.0)
        shots = int(math.ceil(total_torpor / (base_torpor * dmg_mult))) if base_torpor > 0 else None

        torpor_block = {
            "total_torpor": total_torpor,
            "torpor_depl_ps": torpor_depl_ps,
            "torpor_needed": torpor_needed,
            "narco_berries": narco_berries,
            "narcotics": narcotics,
            "bio_toxin": bio_toxin,
            "weapon_key": weapon_key,
            "weapon_label": _weapon_label(weapon_key),
            "weapon_damage_pct": weapon_damage_pct,
            "shots": shots,
        }

    return {
        "creature_key": creature_key,
        "food_key": food_key,
        "food_display": foodname_disp,
        "food_pieces": food_pieces,
        "seconds": seconds,
        "non_violent": non_violent,
        "torpor": torpor_block,
    }

class _TameCalcModal(discord.ui.Modal, title="Tame Calculator"):
    creature = discord.ui.TextInput(label="Creature (e.g. Raptor)", placeholder="Raptor", required=True, max_length=60)
    level = discord.ui.TextInput(label="Wild Level (e.g. 150)", placeholder="150", required=True, max_length=10)
    food = discord.ui.TextInput(label="Food (optional: kibble/mutton/prime/meat/berries)", placeholder="kibble", required=False, max_length=60)
    weapon = discord.ui.TextInput(label="KO Weapon (optional: crossbow/bow/dart/shocking)", placeholder="crossbow", required=False, max_length=30)
    weapon_damage = discord.ui.TextInput(label="Weapon Damage % (optional, default 100)", placeholder="100", required=False, max_length=10)

async def on_submit(self, interaction: discord.Interaction):
    # ✅ IMPORTANT: acknowledge quickly to avoid "Interaction Failed" if we need to fetch wiki data.
    async def _send(*, content: Optional[str] = None, embed: Optional[discord.Embed] = None):
        try:
            if interaction.response.is_done():
                await interaction.followup.send(content=content, embed=embed, ephemeral=True)
            else:
                await interaction.response.send_message(content=content, embed=embed, ephemeral=True)
        except Exception:
            pass

    try:
        await interaction.response.defer(ephemeral=True)
    except Exception:
        # If defer fails for any reason, we still try to respond via _send().
        pass

    creature_name = str(self.creature.value).strip()
    try:
        lvl = int(re.sub(r"[^0-9]", "", str(self.level.value))) if str(self.level.value).strip() else 1
    except Exception:
        lvl = 1
    settings = await calc_get_settings(interaction.guild_id)

    # Attempt to load data; if it fails, fall back to link-only mode.
    ok = await ensure_taming_data_loaded()
    if not ok:
        slug = _slugify_creature(creature_name)
        url = f"https://www.dododex.com/taming/{slug}" if slug else "https://www.dododex.com/"
        desc_lines = [
            f"**Creature:** {creature_name}",
            f"**Wild Level:** {lvl}",
            f"**Server Rates:** Taming **{settings.taming_speed}x**, Food Drain **{settings.food_drain}x**",
            "",
            "⚠️ Calculator data failed to load right now, so here’s a quick link:",
        ]
        e = discord.Embed(title="🧮 Tame Calculation (Link Mode)", description="\n".join(desc_lines), color=0x3498DB)
        e.add_field(name="Dododex", value=url, inline=False)
        e.timestamp = datetime.utcnow()
        await _send(embed=e)
        return

    creature_key = _resolve_creature_key(creature_name)
    if not creature_key:
        await _send(content=(
            f"❌ I couldn't find that creature. Try a simpler name (example: **Raptor**, **Argentavis**, **Ankylosaurus**)."
        ))
        return

    wtxt = str(self.weapon.value).strip()
    try:
        w_dmg = float(re.sub(r"[^0-9.]", "", str(self.weapon_damage.value))) if str(self.weapon_damage.value).strip() else 100.0
    except Exception:
        w_dmg = 100.0

    try:
        result = _compute_taming(
            creature_key=creature_key,
            level=lvl,
            settings=settings,
            food_pref=str(self.food.value or "").strip(),
            weapon_text=wtxt,
            weapon_damage_pct=w_dmg,
        )
    except Exception:
        await _send(content="❌ I couldn't calculate that tame with the options provided. Try a different food (or leave it blank).")
        return

    lines = [
        f"**Creature:** {creature_key}",
        f"**Wild Level:** {lvl}",
        f"**Rates:** Taming **{settings.taming_speed}x**, Food Drain **{settings.food_drain}x**",
        f"**Food:** {result['food_display']} × **{result['food_pieces']}**",
        f"**Estimated Time:** **{_format_hms(result['seconds'])}**",
    ]

    e = discord.Embed(title="🦖 Democracy Ark — Tame Calculator", description="\n".join(lines), color=0x2ECC71)
    e.timestamp = datetime.utcnow()

    if result["non_violent"]:
        e.add_field(
            name="Notes",
            value="This creature uses **non-violent** taming. Torpor / narcotics are not required.",
            inline=False,
        )
    else:
        t = result["torpor"] or {}
        if t:
            e.add_field(
                name="Keep it asleep",
                value=(
                    f"Total Torpor: **{int(t['total_torpor'])}**\n"
                    f"Torpor drain: **{t['torpor_depl_ps']:.2f}/s**\n"
                    f"Extra Torpor needed during tame: **{int(t['torpor_needed'])}**\n"
                    f"Narcoberries: **{t['narco_berries']}** • Narcotics: **{t['narcotics']}** • Bio Toxin: **{t['bio_toxin']}**"
                ),
                inline=False,
            )
            if t.get("shots") is not None:
                e.add_field(
                    name="KO estimate (rough)",
                    value=f"{t['weapon_label']} @ **{t['weapon_damage_pct']:.0f}%** → **~{t['shots']}** shots/hits (100% accuracy, no headshot modifiers).",
                    inline=False,
                )

    e.set_footer(text="Estimates use official wiki taming tables, adjusted by your server multipliers.")
    await _send(embed=e)

class TameCalculatorView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="Calculate", style=discord.ButtonStyle.success, custom_id="tame_calc:calculate")
    async def calculate(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(_TameCalcModal())

async def ensure_tame_calculator_panel(guild: discord.Guild) -> None:
    global _TAME_CALC_MESSAGE_ID_RUNTIME
    ch = await _resolve_text_channel(guild, TAME_CALC_CHANNEL_ID, "tame-calculator")
    if not ch:
        return

    settings = await calc_get_settings(guild.id)
    msg_id = await _ensure_panel_message(
        guild=guild,
        channel_id_str=str(ch.id),
        message_id_runtime_name="_TAME_CALC_MESSAGE_ID_RUNTIME",
        embed=_build_tame_calc_embed(guild, settings),
        view=TameCalculatorView(),
        pin=False,
        expected_embed_title="🦖 Democracy Ark — Tame Calculator",
    )
    if msg_id and msg_id != _TAME_CALC_MESSAGE_ID_RUNTIME:
        _TAME_CALC_MESSAGE_ID_RUNTIME = msg_id
        print(f"[CALC] New TAME_CALC_MESSAGE_ID = {msg_id} (save this in Railway Variables)", flush=True)

async def ensure_calc_settings_panel(guild: discord.Guild) -> None:
    global _CALC_SETTINGS_MESSAGE_ID_RUNTIME
    ch = await _resolve_text_channel(guild, CALC_SETTINGS_CHANNEL_ID, "calc-settings")
    if not ch:
        return

    settings = await calc_get_settings(guild.id)
    msg_id = await _ensure_panel_message(
        guild=guild,
        channel_id_str=str(ch.id),
        message_id_runtime_name="_CALC_SETTINGS_MESSAGE_ID_RUNTIME",
        embed=_build_calc_settings_embed(guild, settings),
        view=CalcSettingsView(),
        pin=False,
        expected_embed_title="⚙️ Democracy Bot — Calculator Settings (Staff)",
    )
    if msg_id and msg_id != _CALC_SETTINGS_MESSAGE_ID_RUNTIME:
        _CALC_SETTINGS_MESSAGE_ID_RUNTIME = msg_id
        print(f"[CALC] New CALC_SETTINGS_MESSAGE_ID = {msg_id} (save this in Railway Variables)", flush=True)

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


def load_claimed_users_state() -> Set[int]:
    ensure_file_exists(CLAIMED_USERS_CSV_PATH, ["user_id", "first_claimed_at", "last_box", "last_pin"])
    users: Set[int] = set()
    try:
        with open(CLAIMED_USERS_CSV_PATH, "r", newline="", encoding="utf-8") as f:
            rdr = csv.DictReader(f)
            for row in rdr:
                try:
                    users.add(int(row.get("user_id") or 0))
                except Exception:
                    continue
    except Exception:
        return set()
    return {u for u in users if u}

def save_claimed_users_state(users: Set[int]) -> None:
    ensure_file_exists(CLAIMED_USERS_CSV_PATH, ["user_id", "first_claimed_at", "last_box", "last_pin"])
    # Preserve basic metadata if file already exists, otherwise write minimal rows.
    existing_meta: dict[int, dict] = {}
    try:
        with open(CLAIMED_USERS_CSV_PATH, "r", newline="", encoding="utf-8") as f:
            rdr = csv.DictReader(f)
            for row in rdr:
                try:
                    uid = int(row.get("user_id") or 0)
                    if uid:
                        existing_meta[uid] = row
                except Exception:
                    continue
    except Exception:
        pass



# -----------------------
# ✅ NEW: Self-assign roles (CSV fallback)
# -----------------------
def load_self_roles_state() -> Dict[int, Tuple[str, str]]:
    ensure_file_exists(SELF_ROLES_CSV_PATH, ["role_id", "label", "description", "added_at"])
    out: Dict[int, Tuple[str, str]] = {}
    try:
        with open(SELF_ROLES_CSV_PATH, "r", newline="", encoding="utf-8") as f:
            rdr = csv.DictReader(f)
            for row in rdr:
                try:
                    rid = int(str(row.get("role_id") or "").strip() or "0")
                    if not rid:
                        continue
                    label = str(row.get("label") or "").strip() or f"Role {rid}"
                    desc = str(row.get("description") or "").strip()
                    out[rid] = (label, desc)
                except Exception:
                    continue
    except Exception:
        return {}
    return out

def save_self_roles_state(roles: Dict[int, Tuple[str, str]]) -> None:
    ensure_file_exists(SELF_ROLES_CSV_PATH, ["role_id", "label", "description", "added_at"])
    now_ts = int(time.time())
    with open(SELF_ROLES_CSV_PATH, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["role_id", "label", "description", "added_at"])
        for rid, (label, desc) in sorted(roles.items(), key=lambda x: x[0]):
            w.writerow([int(rid), str(label or ""), str(desc or ""), now_ts])
    now_ts = int(time.time())
    with open(CLAIMED_USERS_CSV_PATH, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["user_id", "first_claimed_at", "last_box", "last_pin"])
        w.writeheader()
        for uid in sorted(users):
            meta = existing_meta.get(uid, {})
            w.writerow(
                {
                    "user_id": uid,
                    "first_claimed_at": meta.get("first_claimed_at") or str(now_ts),
                    "last_box": meta.get("last_box") or "",
                    "last_pin": meta.get("last_pin") or "",
                }
            )

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
    global PINS_POOL, CLAIMS, CLAIMED_USERS, SELF_ROLES
    if DB_POOL is not None:
        PINS_POOL = await db_load_pins_pool()
        CLAIMS = await db_load_claims_state()
        # Claimed users (ever claimed) live in DB so recycled vaults can't be re-claimed.
        try:
            async with DB_POOL.acquire() as con:
                CLAIMED_USERS = await db_load_claimed_users(con)
        except Exception as e:
            print(f"STATE: failed to load CLAIMED_USERS from DB: {e}")

        # ✅ preload active polls so votes and results survive restarts
        try:
            polls = await db_load_active_polls()
            for p in polls:
                try:
                    ch_id = int(p.get("channel_id") or 0)
                    if not ch_id:
                        continue
                    POLL_BY_CHANNEL[ch_id] = PollState(
                        message_id=int(p.get("message_id") or 0),
                        channel_id=ch_id,
                        question=str(p.get("question") or ""),
                        options=list(p.get("options") or []),
                        votes=dict(p.get("votes") or {}),
                        ended=bool(p.get("ended")),
                    )
                except Exception:
                    continue
        except Exception:
            pass

        # ✅ load self-assign roles list
        try:
            SELF_ROLES = await db_load_self_roles()
        except Exception:
            SELF_ROLES = {}

        return

    # Fallback to CSV
    PINS_POOL = load_pins_pool()
    CLAIMS = load_claims_state()
    CLAIMED_USERS = load_claimed_users_state()
    SELF_ROLES = load_self_roles_state()

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


async def save_claimed_users_only() -> None:
    """Persist CLAIMED_USERS.
    - If using DB: claims are written via db_mark_user_claimed() at claim-time, so nothing to do here.
    - If using CSV: write claimed_users.json so recycled vaults still block re-claim.
    """
    global CLAIMED_USERS
    if DATABASE_URL and DB_POOL:
        return
    save_claimed_users_state(CLAIMED_USERS)



async def save_self_roles_only() -> None:
    """Persist SELF_ROLES list (DB preferred, CSV fallback)."""
    global SELF_ROLES
    if DB_POOL is not None:
        # DB writes are done per add/remove via db_upsert_self_role / db_delete_self_role
        return
    save_self_roles_state(SELF_ROLES)
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

    # Register persistent views so old pinned panels/buttons keep working after restarts
    global VIEWS_REGISTERED
    if not VIEWS_REGISTERED:
        try:
            bot.add_view(PersistentServerControlView())
            bot.add_view(StarterKitPanelView())
            bot.add_view(PersistentPollPanelView())
            bot.add_view(StarterVaultAdminView())
            bot.add_view(TicketPanelView())
            bot.add_view(TicketControlsView())
            bot.add_view(GetRoleView())
            bot.add_view(SelfRolesView())
            bot.add_view(RoleManagerView())
            bot.add_view(TameCalculatorView())
            bot.add_view(CalcSettingsView())
            VIEWS_REGISTERED = True
            print("UI: persistent views registered", flush=True)
        except Exception:
            print("UI: failed to register persistent views:\n" + traceback.format_exc(), flush=True)

    # ✅ NEW: start Nitrado status/warn tasks (server-status module)
    try:
        start_nitrado_status_tasks()
    except Exception:
        print("NITRADO: start tasks failed:", traceback.format_exc(), flush=True)

    # ✅ Ensure module panels exist (each module isolated so one failure can't block others)
    for g in bot.guilds:
        for label, fn in [
            ("server_control_panel", ensure_server_control_panel),
            ("starter_panel", ensure_starter_panel),
            ("starter_admin_panel", ensure_starter_admin_panel),
            ("poll_panel", ensure_poll_panel),
            ("get_role_panel", ensure_get_role_panel),
            ("self_roles_panel", ensure_self_roles_panel),
            ("role_manager_panel", ensure_role_manager_panel),
            ("tame_calculator_panel", ensure_tame_calculator_panel),
            ("calc_settings_panel", ensure_calc_settings_panel),
        ]:
            try:
                await fn(g)
            except Exception:
                print(f"MODULES: {label} ensure failed:\\n{traceback.format_exc()}", flush=True)

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
        color=0xE67E22,
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
                  AND table_name IN ('pins_pool', 'claims', 'resets', 'tickets', 'ticket_events', 'ticket_notes', 'polls', 'poll_votes');
                """
            )
        host, dbname = _safe_db_info(LAST_DB_URL or DATABASE_URL)
        found = {r["table_name"] for r in tables}
        missing = sorted({"pins_pool", "claims", "resets", "tickets", "ticket_events", "ticket_notes", "polls", "poll_votes"} - found)
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

    # ✅ keep Starter Kit module panel counts accurate
    try:
        if interaction.guild:
            await refresh_starter_panel(interaction.guild)
    except Exception:
        pass

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

    # ✅ keep Starter Kit module panel counts accurate
    try:
        if interaction.guild:
            await refresh_starter_panel(interaction.guild)
    except Exception:
        pass

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
@bot.tree.command(name="claimstarter", description="Claim your free starter kit (one per person)")
async def claimstarter(interaction: discord.Interaction):
    if not interaction.user:
        return

    uid = interaction.user.id

    # If they currently have a vault, show it
    if uid in CLAIMS:
        box, pin = CLAIMS[uid]
        await interaction.response.send_message(
            f"✅ You already claimed your starter kit.\nVault: **#{box}**\nPIN: **{pin}**",
            ephemeral=True,
        )
        return

    # If they've ever claimed before (even if a vault was recycled), block re-claim
    if uid in CLAIMED_USERS:
        await interaction.response.send_message(
            "❌ You've already claimed a free starter kit on this server.\n"
            "If you need help, open a ticket and staff can assist.",
            ephemeral=True,
        )
        return

    if not PINS_POOL:
        await interaction.response.send_message(
            "❌ Sorry — starter kits are currently out of stock.\n"
            "Please ask an admin to restock the pool.",
            ephemeral=True,
        )
        return

    # Pick a vault from the pool (stable order for predictability)
    box = sorted(PINS_POOL.keys())[0]
    bp = PINS_POOL.pop(box)
    box, pin = bp.box, bp.pin

    CLAIMS[uid] = (box, pin)

    # Permanently record that this user has claimed (so recycled vaults don't allow re-claim)
    CLAIMED_USERS.add(uid)
    if DATABASE_URL:
        try:
            async with DB_POOL.acquire() as con:
                await db_mark_user_claimed(con, uid, box=box, pin=pin)
        except Exception:
            pass
    else:
        await save_claimed_users_only()

    await save_pool_state()
    await save_claims_only()

    # Update pinned panels if present
    try:
        if interaction.guild:
            await refresh_starter_panel(interaction.guild)
            await ensure_starter_admin_panel(interaction.guild)
    except Exception:
        pass

    await interaction.response.send_message(
        f"🎁 Starter kit claimed!\nVault: **#{box}**\nPIN: **{pin}**",
        ephemeral=True,
    )

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
    if not interaction.channel or not interaction.guild:
        return

    options = [option1.strip(), option2.strip()]
    for opt in [option3, option4, option5, option6, option7, option8, option9, option10]:
        if opt and opt.strip():
            options.append(opt.strip())

    # Create the poll message publicly
    try:
        poll = await _create_poll_message(interaction.channel, question.strip(), options)
    except Exception as e:
        await interaction.response.send_message(f"❌ Failed to create poll: {repr(e)}", ephemeral=True)
        return

    if not poll:
        await interaction.response.send_message(
            "⚠️ There is already an active poll in this channel.\nUse `/pollend` or `/polldelete`.",
            ephemeral=True,
        )
        return

    # Use original_response style (as before) so it feels instant
    try:
        await interaction.response.send_message("✅ Poll created.", ephemeral=True)
    except Exception:
        pass

    # Refresh poll panel
    try:
        await refresh_poll_panel(interaction.guild, int(interaction.channel.id))
    except Exception:
        pass

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
    if not interaction.channel or not interaction.guild:
        return
    poll = POLL_BY_CHANNEL.get(interaction.channel.id)
    if not poll:
        await interaction.response.send_message("No poll found in this channel.", ephemeral=True)
        return
    poll.ended = True

    try:
        await db_set_poll_ended(poll.message_id, True)
    except Exception:
        pass

    # Update the public message to show closed + final counts
    try:
        msg = await interaction.channel.fetch_message(poll.message_id)
        await msg.edit(embed=poll_embed(poll), view=None)
    except Exception:
        pass

    await interaction.response.send_message("✅ Poll ended. Voting is now closed.", ephemeral=True)

    try:
        await refresh_poll_panel(interaction.guild, int(interaction.channel.id))
    except Exception:
        pass

@bot.tree.command(name="polldelete", description="Admin: Delete the poll message and remove the poll.")
async def poll_delete(interaction: discord.Interaction):
    # ✅ lock poll admin commands to vote channel
    if not _only_in_channel(interaction, VOTE_CHANNEL_ID):
        await _wrong_channel(interaction, "#vote")
        return

    if not is_admin(interaction):
        await interaction.response.send_message("❌ Admins only.", ephemeral=True)
        return
    if not interaction.channel or not interaction.guild:
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
    try:
        await db_delete_poll(poll.message_id)
    except Exception:
        pass

    await interaction.response.send_message("🗑️ Poll deleted.", ephemeral=True)

    try:
        await refresh_poll_panel(interaction.guild, int(interaction.channel.id))
    except Exception:
        pass

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


class _TicketDeleteConfirmModal(discord.ui.Modal, title="Delete Ticket"):
    confirm_text = discord.ui.TextInput(
        label="Type DELETE to confirm",
        style=discord.TextStyle.short,
        required=True,
        max_length=10,
        placeholder="DELETE",
    )
    reason = discord.ui.TextInput(
        label="Reason (optional)",
        style=discord.TextStyle.short,
        required=False,
        max_length=100,
        placeholder="e.g. resolved, spam, duplicate",
    )

    async def on_submit(self, interaction: discord.Interaction):
        if str(self.confirm_text.value or "").strip().upper() != "DELETE":
            return await interaction.response.send_message("❌ Not deleted (confirmation text didn't match).", ephemeral=True)
        await ticket_delete_action(interaction, reason=str(self.reason.value or "deleted via button").strip() or "deleted via button")

class TicketControlsView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="Transcript", style=discord.ButtonStyle.secondary, custom_id="ticket_ctrl_transcript")
    async def transcript_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await ticket_transcript_action(interaction)


    @discord.ui.button(label="Delete", style=discord.ButtonStyle.danger, custom_id="ticket_ctrl_delete")
    async def delete_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        # Staff only
        if not interaction.guild or not isinstance(interaction.user, discord.Member) or not is_staff_member(interaction.user):
            await interaction.response.send_message("❌ Staff only.", ephemeral=True)
            return
        await interaction.response.send_modal(_TicketDeleteConfirmModal())
    

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
        color=0x95A5A6,
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
