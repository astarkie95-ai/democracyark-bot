import os
import csv
import sqlite3
from typing import Optional

import discord
from discord import app_commands
from flask import Flask
from threading import Thread
from dotenv import load_dotenv

# Load environment variables from .env (local dev)
load_dotenv()

# ---------------------------
# CONFIG (edit via commands)
# ---------------------------
DB_PATH = "starter_pins.db"
PINS_CSV_PATH = "pins.csv"

TOKEN = os.getenv("DISCORD_TOKEN")  # REQUIRED
ADMIN_USER_ID = int(os.getenv("ADMIN_USER_ID", "0"))  # optional but recommended (your user id)

# ---------------------------
# Keep-alive web server (useful on some hosts)
# ---------------------------
app = Flask(__name__)

@app.get("/")
def home():
    return "bot is alive", 200

def run_web():
    port = int(os.getenv("PORT", "8080"))
    app.run(host="0.0.0.0", port=port)

Thread(target=run_web, daemon=True).start()


# ---------------------------
# Database helpers
# ---------------------------
def db():
    return sqlite3.connect(DB_PATH)

def init_db():
    con = db()
    cur = con.cursor()

    # settings table for channel restrictions etc.
    cur.execute("""
        CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value TEXT
        )
    """)

    # pins table
    cur.execute("""
        CREATE TABLE IF NOT EXISTS pins (
            pin TEXT PRIMARY KEY,
            claimed_by_user_id INTEGER,
            claimed_at TEXT
        )
    """)

    con.commit()
    con.close()

def set_setting(key: str, value: str):
    con = db()
    cur = con.cursor()
    cur.execute("INSERT INTO settings(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (key, value))
    con.commit()
    con.close()

def get_setting(key: str) -> Optional[str]:
    con = db()
    cur = con.cursor()
    cur.execute("SELECT value FROM settings WHERE key=?", (key,))
    row = cur.fetchone()
    con.close()
    return row[0] if row else None

def load_pins_from_csv_if_db_empty():
    # If DB already has pins, do nothing
    con = db()
    cur = con.cursor()
    cur.execute("SELECT COUNT(*) FROM pins")
    count = cur.fetchone()[0]
    con.close()
    if count > 0:
        return

    if not os.path.exists(PINS_CSV_PATH):
        return

    pins = []
    with open(PINS_CSV_PATH, newline="", encoding="utf-8") as f:
        reader = csv.reader(f)
        for row in reader:
            if not row:
                continue
            pin = str(row[0]).strip()
            if pin and pin.isdigit() and len(pin) == 4:
                pins.append(pin)

    if not pins:
        return

    con = db()
    cur = con.cursor()
    for pin in pins:
        cur.execute("INSERT OR IGNORE INTO pins(pin, claimed_by_user_id, claimed_at) VALUES(?, NULL, NULL)", (pin,))
    con.commit()
    con.close()

def is_admin(interaction: discord.Interaction) -> bool:
    # Allow either:
    # - You set ADMIN_USER_ID in .env
    # - Or the user has Administrator permission in the server
    if ADMIN_USER_ID and interaction.user.id == ADMIN_USER_ID:
        return True
    if interaction.guild and isinstance(interaction.user, discord.Member):
        return interaction.user.guild_permissions.administrator
    return False

def channel_allowed(interaction: discord.Interaction, setting_key: str) -> bool:
    """
    setting_key = "claim_channel_id" or "admin_channel_id"
    If not set -> allow everywhere (so you don't lock yourself out by accident)
    If set -> only allow in that channel
    """
    allowed_id = get_setting(setting_key)
    if not allowed_id:
        return True
    try:
        return interaction.channel_id == int(allowed_id)
    except ValueError:
        return True


# ---------------------------
# Discord client
# ---------------------------
intents = discord.Intents.default()

class MyClient(discord.Client):
    def __init__(self):
        super().__init__(intents=intents)
        self.tree = app_commands.CommandTree(self)

    async def setup_hook(self):
        init_db()
        load_pins_from_csv_if_db_empty()
        await self.tree.sync()

    async def on_ready(self):
        print(f"Logged in as {self.user} (ID: {self.user.id})")
        # Pin stats
        con = db()
        cur = con.cursor()
        cur.execute("SELECT COUNT(*) FROM pins")
        total = cur.fetchone()[0]
        cur.execute("SELECT COUNT(*) FROM pins WHERE claimed_by_user_id IS NULL")
        remaining = cur.fetchone()[0]
        con.close()
        print(f"Bot is online")
        print(f"Pins: total={total}, remaining={remaining}")


client = MyClient()


# ---------------------------
# Commands
# ---------------------------

@client.tree.command(name="ping", description="Check if the bot is responsive.")
async def ping(interaction: discord.Interaction):
    await interaction.response.send_message("Pong ✅", ephemeral=True)


@client.tree.command(name="pinstatus", description="Show how many starter PINs remain.")
async def pinstatus(interaction: discord.Interaction):
    con = db()
    cur = con.cursor()
    cur.execute("SELECT COUNT(*) FROM pins")
    total = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM pins WHERE claimed_by_user_id IS NULL")
    remaining = cur.fetchone()[0]
    con.close()

    await interaction.response.send_message(
        f"📌 Pins: **{remaining}** remaining out of **{total}**.",
        ephemeral=True
    )


@client.tree.command(name="claimstarter", description="Claim a starter kit PIN (one per user).")
async def claimstarter(interaction: discord.Interaction):
    # Restrict this command to claim channel (if set)
    if not channel_allowed(interaction, "claim_channel_id"):
        claim_id = get_setting("claim_channel_id")
        msg = "This command is not allowed in this channel."
        if claim_id:
            msg += f" Use it in <#{claim_id}>."
        await interaction.response.send_message(msg, ephemeral=True)
        return

    con = db()
    cur = con.cursor()

    # already claimed?
    cur.execute("SELECT pin FROM pins WHERE claimed_by_user_id=?", (interaction.user.id,))
    row = cur.fetchone()
    if row:
        con.close()
        await interaction.response.send_message(
            f"You already claimed a starter PIN: **{row[0]}**",
            ephemeral=True
        )
        return

    # get an unclaimed pin
    cur.execute("SELECT pin FROM pins WHERE claimed_by_user_id IS NULL ORDER BY pin LIMIT 1")
    row = cur.fetchone()
    if not row:
        con.close()
        await interaction.response.send_message("No pins remaining 😭", ephemeral=True)
        return

    pin = row[0]
    cur.execute(
        "UPDATE pins SET claimed_by_user_id=? , claimed_at=datetime('now') WHERE pin=? AND claimed_by_user_id IS NULL",
        (interaction.user.id, pin)
    )
    con.commit()
    con.close()

    await interaction.response.send_message(
        f"✅ Your starter PIN is: **{pin}**\n"
        f"Use it on the in-game locker. (Keep this private.)",
        ephemeral=True
    )


@client.tree.command(name="setclaimchannel", description="Admin: set which channel /claimstarter works in.")
async def setclaimchannel(interaction: discord.Interaction):
    if not is_admin(interaction):
        await interaction.response.send_message("Admins only.", ephemeral=True)
        return

    # Restrict admin commands to admin channel (if set)
    if not channel_allowed(interaction, "admin_channel_id"):
        admin_id = get_setting("admin_channel_id")
        msg = "Admin commands are not allowed in this channel."
        if admin_id:
            msg += f" Use them in <#{admin_id}>."
        await interaction.response.send_message(msg, ephemeral=True)
        return

    set_setting("claim_channel_id", str(interaction.channel_id))
    await interaction.response.send_message(
        f"✅ Claim channel set to: <#{interaction.channel_id}>",
        ephemeral=True
    )


@client.tree.command(name="setadminchannel", description="Admin: set which channel admin commands work in.")
async def setadminchannel(interaction: discord.Interaction):
    if not is_admin(interaction):
        await interaction.response.send_message("Admins only.", ephemeral=True)
        return

    set_setting("admin_channel_id", str(interaction.channel_id))
    await interaction.response.send_message(
        f"✅ Admin commands now restricted to: <#{interaction.channel_id}>",
        ephemeral=True
    )


@client.tree.command(name="addpins", description="Admin: add pins (comma/space separated). Example: 1234 2345 3456")
@app_commands.describe(pins="Pins separated by spaces or commas")
async def addpins(interaction: discord.Interaction, pins: str):
    if not is_admin(interaction):
        await interaction.response.send_message("Admins only.", ephemeral=True)
        return

    # Restrict admin commands to admin channel (if set)
    if not channel_allowed(interaction, "admin_channel_id"):
        admin_id = get_setting("admin_channel_id")
        msg = "Admin commands are not allowed in this channel."
        if admin_id:
            msg += f" Use them in <#{admin_id}>."
        await interaction.response.send_message(msg, ephemeral=True)
        return

    raw = pins.replace(",", " ").split()
    cleaned = []
    for p in raw:
        p = p.strip()
        if p.isdigit() and len(p) == 4:
            cleaned.append(p)

    if not cleaned:
        await interaction.response.send_message("No valid 4-digit pins found.", ephemeral=True)
        return

    con = db()
    cur = con.cursor()
    added = 0
    for p in cleaned:
        cur.execute("INSERT OR IGNORE INTO pins(pin, claimed_by_user_id, claimed_at) VALUES(?, NULL, NULL)", (p,))
        if cur.rowcount > 0:
            added += 1
    con.commit()
    con.close()

    await interaction.response.send_message(f"✅ Added **{added}** pins.", ephemeral=True)


# ---------------------------
# Run
# ---------------------------
if not TOKEN:
    raise SystemExit("DISCORD_TOKEN missing. Put it in .env (local) or Railway Variables.")
client.run(TOKEN)
