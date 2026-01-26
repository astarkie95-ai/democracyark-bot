import os
import csv
import time
from dataclasses import dataclass
from typing import Dict, Optional, List, Tuple

import discord
from discord import app_commands
from discord.ext import commands

from flask import Flask
from threading import Thread

# -----------------------
# ENV
# -----------------------
DISCORD_TOKEN = os.getenv("DISCORD_TOKEN", "").strip()
GUILD_ID = os.getenv("GUILD_ID", "").strip()  # optional: faster slash command sync

PINS_CSV_PATH = os.getenv("PINS_CSV_PATH", "pins.csv")         # pool (unclaimed)
CLAIMS_CSV_PATH = os.getenv("CLAIMS_CSV_PATH", "claims.csv")   # state (claimed now)
RESETS_CSV_PATH = os.getenv("RESETS_CSV_PATH", "resets.csv")   # admin reset log

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
bot = commands.Bot(command_prefix="!", intents=intents)  # prefix irrelevant, we use slash

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
# Boot load
# -----------------------
PINS_POOL = load_pins_pool()
CLAIMS = load_claims_state()

# -----------------------
# Events
# -----------------------
@bot.event
async def on_ready():
    print(f"Logged in as {bot.user} (id: {bot.user.id})")

    try:
        if GUILD_ID.isdigit():
            guild = discord.Object(id=int(GUILD_ID))
            bot.tree.copy_global_to(guild=guild)
            synced = await bot.tree.sync(guild=guild)
            print(f"Synced {len(synced)} commands to guild {GUILD_ID}")
        else:
            synced = await bot.tree.sync()
            print(f"Synced {len(synced)} global commands")
    except Exception as e:
        print("Command sync failed:", e)

# -----------------------
# Old names (restored)
# -----------------------
@bot.tree.command(name="ping", description="Check if the bot is alive.")
async def ping(interaction: discord.Interaction):
    await interaction.response.send_message("Pong ✅", ephemeral=True)

# -----------------------
# ADMIN: add pins into pool
# -----------------------
@bot.tree.command(name="addpins", description="Admin: Add ONE new starter kit pin into the pool.")
@app_commands.describe(box="Box number (e.g. 5)", pin="PIN code (e.g. 1234)")
async def addpins(interaction: discord.Interaction, box: int, pin: str):
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
    save_pins_pool(PINS_POOL)

    await interaction.response.send_message(
        f"✅ Added starter kit to pool.\n**Box:** #{box}\n**PIN:** `{pin}`\n\n{pool_counts()}",
        ephemeral=True
    )

@bot.tree.command(name="addpinsbulk", description="Admin: Add MANY starter kit pins at once (one per line: box,pin).")
@app_commands.describe(lines="Paste lines like:\n1,1234\n2,5678\n3,9012")
async def addpinsbulk(interaction: discord.Interaction, lines: str):
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

    save_pins_pool(PINS_POOL)

    await interaction.response.send_message(
        f"✅ Bulk add complete.\nAdded: **{added}** | Skipped: **{skipped}**\n\n{pool_counts()}",
        ephemeral=True
    )

@bot.tree.command(name="poolcount", description="Admin: Show how many starter kits are available.")
async def poolcount(interaction: discord.Interaction):
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

    # Restore to pool
    PINS_POOL[box] = BoxPin(box=box, pin=claimant_pin)
    save_pins_pool(PINS_POOL)

    # Remove the claim (so they can claim again)
    CLAIMS.pop(claimant_uid, None)
    save_claims_state(CLAIMS)

    append_reset_log(
        admin_id=interaction.user.id,
        box=box,
        user_id=claimant_uid,
        pin=claimant_pin,
        reason="admin resetbox",
    )

    await interaction.response.send_message(
        f"✅ Reset complete.\n"
        f"Box **#{box}** has been returned to the pool with its PIN.\n"
        f"Previous claimant user id: `{claimant_uid}`\n\n"
        f"{pool_counts()}",
        ephemeral=True
    )

# -----------------------
# Existing resetboxes (kept)
# -----------------------
@bot.tree.command(name="resetboxes", description="Admin: Clear ALL claims (everyone can claim again).")
async def resetboxes(interaction: discord.Interaction):
    if not is_admin(interaction):
        await interaction.response.send_message("❌ Admins only.", ephemeral=True)
        return

    global CLAIMS
    CLAIMS = {}
    save_claims_state(CLAIMS)

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
    save_pins_pool(PINS_POOL)

    # Record claim in state
    CLAIMS[uid] = (bp.box, bp.pin)
    save_claims_state(CLAIMS)

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

                # Save vote (one vote per user; changing vote is allowed)
                poll2.votes[interaction.user.id] = option_index

                # Update the public poll message so everyone sees new counters
                try:
                    channel = interaction.channel
                    if channel is not None:
                        msg = await channel.fetch_message(poll2.message_id)
                        view = PollView(self.channel_id)
                        view.build_buttons()
                        await msg.edit(embed=poll_embed(poll2), view=view)
                except Exception:
                    # If edit fails, still save the vote and respond
                    pass

                await interaction.response.send_message(
                    f"✅ Vote saved: **{poll2.options[option_index]}**",
                    ephemeral=True,
                )

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
