import os
import csv
import time
import traceback
from dataclasses import dataclass
from typing import Dict, Optional, List, Tuple

import discord
from discord import app_commands
from discord.ext import commands

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

# ✅ NEW: Neon Postgres connection string (set this in Railway Variables)
# Example: postgresql://user:pass@host/db?sslmode=require
DATABASE_URL = os.getenv("DATABASE_URL", "").strip()

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
            # Create tables if they don't exist
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
            print("✅ DB: tables ensured.", flush=True)
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
    import random

    used = _all_pins_in_use()

    for _ in range(max_tries):
        pin = "".join(str(random.randint(0, 9)) for _ in range(length))
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
        await channel.send(f"Welcome to the server, {member.mention}! 🎉")
    except Exception as e:
        print("Welcome message failed:", repr(e), flush=True)

# -----------------------
# Old names (restored)
# -----------------------
@bot.tree.command(name="ping", description="Check if the bot is alive.")
async def ping(interaction: discord.Interaction):
    await interaction.response.send_message("Pong ✅", ephemeral=True)

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
        await channel.send(f"Welcome to the server, {interaction.user.mention}! 🎉")
        await interaction.response.send_message("✅ Sent test welcome message.", ephemeral=True)
    except Exception as e:
        await interaction.response.send_message(f"❌ Failed to send welcome message: {repr(e)}", ephemeral=True)

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
                  AND table_name IN ('pins_pool', 'claims', 'resets');
                """
            )
        host, dbname = _safe_db_info(LAST_DB_URL or DATABASE_URL)
        found = {r["table_name"] for r in tables}
        missing = sorted({"pins_pool", "claims", "resets"} - found)
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

# -----------------------
# RUN
# -----------------------
bot.run(DISCORD_TOKEN)
