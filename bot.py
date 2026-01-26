import os
import csv
import asyncio
from dataclasses import dataclass
from typing import Dict, Optional, List, Tuple

import discord
from discord import app_commands
from discord.ext import commands

from flask import Flask
from threading import Thread

# -----------------------
# Config / Environment
# -----------------------
DISCORD_TOKEN = os.getenv("DISCORD_TOKEN", "").strip()
GUILD_ID = os.getenv("GUILD_ID", "").strip()  # optional, speeds up slash updates
PINS_CSV_PATH = os.getenv("PINS_CSV_PATH", "pins.csv")  # default: repo root

if not DISCORD_TOKEN:
    # Railway logs will show this clearly if you forgot to set the variable
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
# We only use slash commands, so message_content not needed.
bot = commands.Bot(command_prefix="!", intents=intents)  # prefix irrelevant, slash only

# -----------------------
# Starter Kit Pin Storage
# -----------------------
@dataclass
class BoxPin:
    box: int
    pin: str
    claimed_by: Optional[int] = None  # Discord user id if claimed

def load_pins_from_csv(path: str) -> Dict[int, BoxPin]:
    pins: Dict[int, BoxPin] = {}
    if not os.path.exists(path):
        # File missing is allowed; admin can add later, but commands will warn.
        return pins

    with open(path, "r", newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        # Expect columns: box,pin
        for row in reader:
            try:
                box = int(str(row.get("box", "")).strip())
                pin = str(row.get("pin", "")).strip()
                if not pin:
                    continue
                pins[box] = BoxPin(box=box, pin=pin, claimed_by=None)
            except Exception:
                continue
    return pins

def save_pins_to_csv(path: str, pins: Dict[int, BoxPin]) -> None:
    # Save with claimed_by in file so it persists
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["box", "pin", "claimed_by"])
        for box in sorted(pins.keys()):
            bp = pins[box]
            writer.writerow([bp.box, bp.pin, bp.claimed_by if bp.claimed_by is not None else ""])

def load_claims_if_present(path: str, pins: Dict[int, BoxPin]) -> None:
    # If CSV includes claimed_by column, load it
    if not os.path.exists(path):
        return
    with open(path, "r", newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        if "claimed_by" not in reader.fieldnames:
            return
        for row in reader:
            try:
                box = int(str(row.get("box", "")).strip())
                claimed = str(row.get("claimed_by", "")).strip()
                if box in pins and claimed.isdigit():
                    pins[box].claimed_by = int(claimed)
            except Exception:
                continue

PINS: Dict[int, BoxPin] = load_pins_from_csv(PINS_CSV_PATH)
load_claims_if_present(PINS_CSV_PATH, PINS)

def get_unclaimed_boxes(pins: Dict[int, BoxPin]) -> List[BoxPin]:
    return [bp for bp in pins.values() if bp.claimed_by is None]

def find_user_claim(pins: Dict[int, BoxPin], user_id: int) -> Optional[BoxPin]:
    for bp in pins.values():
        if bp.claimed_by == user_id:
            return bp
    return None

# -----------------------
# Poll System (Admin-only)
# -----------------------
@dataclass
class PollState:
    message_id: int
    channel_id: int
    question: str
    options: List[str]
    votes: Dict[int, int]          # user_id -> option_index
    ended: bool

POLL_BY_CHANNEL: Dict[int, PollState] = {}  # channel_id -> poll

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
        # Clear existing items then add buttons for current poll options
        self.clear_items()
        poll = POLL_BY_CHANNEL.get(self.channel_id)
        if not poll:
            return

        for idx, label in enumerate(poll.options):
            # Button custom_id must be stable
            btn = discord.ui.Button(
                label=f"{idx+1}. {label[:70]}",
                style=discord.ButtonStyle.primary,
                custom_id=f"poll_vote_{self.channel_id}_{idx}"
            )
            async def callback(interaction: discord.Interaction, option_index=idx):
                poll2 = POLL_BY_CHANNEL.get(self.channel_id)
                if not poll2 or poll2.ended:
                    await interaction.response.send_message("This poll is closed.", ephemeral=True)
                    return

                poll2.votes[interaction.user.id] = option_index
                await interaction.response.send_message(
                    f"✅ Vote saved: **{poll2.options[option_index]}**",
                    ephemeral=True
                )

            btn.callback = callback
            self.add_item(btn)

def poll_embed(poll: PollState) -> discord.Embed:
    e = discord.Embed(title="📊 Poll", description=poll.question)
    lines = []
    for i, opt in enumerate(poll.options):
        lines.append(f"**{i+1}.** {opt}")
    e.add_field(name="Options", value="\n".join(lines), inline=False)
    e.set_footer(text="Click a button to vote. Admins can /pollresults, /pollend, /polldelete.")
    return e

def poll_results_text(poll: PollState) -> str:
    counts = [0] * len(poll.options)
    for _, idx in poll.votes.items():
        if 0 <= idx < len(counts):
            counts[idx] += 1
    total = sum(counts)
    out = [f"📊 **Results:** {poll.question}", f"Total votes: **{total}**"]
    for i, opt in enumerate(poll.options):
        out.append(f"**{i+1}. {opt}** — {counts[i]}")
    return "\n".join(out)

# -----------------------
# Permissions helper
# -----------------------
def is_admin(interaction: discord.Interaction) -> bool:
    if not interaction.guild or not interaction.user:
        return False
    if isinstance(interaction.user, discord.Member):
        perms = interaction.user.guild_permissions
        return perms.administrator or perms.manage_guild or perms.manage_channels
    return False

# -----------------------
# EVENTS
# -----------------------
@bot.event
async def on_ready():
    print(f"Logged in as {bot.user} (id: {bot.user.id})")

    # Sync commands
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
# OLD COMMAND NAMES (RESTORED)
# -----------------------
@bot.tree.command(name="ping", description="Check if the bot is alive.")
async def ping(interaction: discord.Interaction):
    await interaction.response.send_message("Pong ✅", ephemeral=True)

@bot.tree.command(name="addpins", description="Admin: reload pins from pins.csv (old name restored).")
async def addpins(interaction: discord.Interaction):
    if not is_admin(interaction):
        await interaction.response.send_message("❌ Admins only.", ephemeral=True)
        return

    global PINS
    PINS = load_pins_from_csv(PINS_CSV_PATH)
    load_claims_if_present(PINS_CSV_PATH, PINS)

    await interaction.response.send_message(
        f"✅ Reloaded pins from `{PINS_CSV_PATH}`.\n"
        f"Boxes loaded: **{len(PINS)}** | Unclaimed: **{len(get_unclaimed_boxes(PINS))}**",
        ephemeral=True
    )

# -----------------------
# STARTER KIT COMMANDS
# -----------------------
@bot.tree.command(name="claimstarter", description="Claim your starter kit PIN + assigned box number (one per person).")
async def claimstarter(interaction: discord.Interaction):
    if not interaction.user:
        return

    if not PINS:
        await interaction.response.send_message(
            f"⚠️ No pins loaded yet.\nAsk an admin to create `{PINS_CSV_PATH}` and run `/addpins`.",
            ephemeral=True
        )
        return

    existing = find_user_claim(PINS, interaction.user.id)
    if existing:
        await interaction.response.send_message(
            f"✅ You already claimed a kit.\n"
            f"**Your box:** #{existing.box}\n"
            f"**Your PIN:** `{existing.pin}`",
            ephemeral=True
        )
        return

    free_boxes = get_unclaimed_boxes(PINS)
    if not free_boxes:
        await interaction.response.send_message(
            "❌ No starter kits available right now. Ask an admin to add more boxes/pins.",
            ephemeral=True
        )
        return

    # Pick the lowest unclaimed box
    free_boxes.sort(key=lambda b: b.box)
    chosen = free_boxes[0]
    chosen.claimed_by = interaction.user.id

    # Persist claim into CSV (adds claimed_by column)
    save_pins_to_csv(PINS_CSV_PATH, PINS)

    await interaction.response.send_message(
        f"🎁 Starter kit claimed!\n"
        f"**Your box:** #{chosen.box}\n"
        f"**Your PIN:** `{chosen.pin}`\n\n"
        f"Go to the Community Hub and unlock **Box #{chosen.box}** with that PIN.",
        ephemeral=True
    )

@bot.tree.command(name="resetboxes", description="Admin: reset all starter kit claims (keeps pins, clears claimed users).")
async def resetboxes(interaction: discord.Interaction):
    if not is_admin(interaction):
        await interaction.response.send_message("❌ Admins only.", ephemeral=True)
        return

    if not PINS:
        await interaction.response.send_message("⚠️ No pins loaded.", ephemeral=True)
        return

    for bp in PINS.values():
        bp.claimed_by = None

    save_pins_to_csv(PINS_CSV_PATH, PINS)

    await interaction.response.send_message(
        f"✅ All starter kit claims cleared.\n"
        f"Boxes available now: **{len(PINS)}**",
        ephemeral=True
    )

# -----------------------
# POLL COMMANDS (ADMIN ONLY)
# -----------------------
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

    # One poll per channel (simple and clean)
    existing = POLL_BY_CHANNEL.get(channel_id)
    if existing and not existing.ended:
        await interaction.response.send_message(
            "⚠️ There is already an active poll in this channel.\n"
            "Use `/pollend` to end it or `/polldelete` to remove it.",
            ephemeral=True
        )
        return

    options = [option1, option2]
    for opt in [option3, option4, option5, option6, option7, option8, option9, option10]:
        if opt and opt.strip():
            options.append(opt.strip())

    if len(options) < 2:
        await interaction.response.send_message("Need at least 2 options.", ephemeral=True)
        return

    # Build state
    poll_state = PollState(
        message_id=0,
        channel_id=channel_id,
        question=question.strip(),
        options=options[:10],
        votes={},
        ended=False,
    )
    POLL_BY_CHANNEL[channel_id] = poll_state

    view = PollView(channel_id=channel_id)
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

@bot.tree.command(name="pollend", description="Admin: End/lock the current poll (stops voting).")
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
    await interaction.response.send_message("✅ Poll ended. Voting is now closed.", ephemeral=True)

@bot.tree.command(name="polldelete", description="Admin: Delete the poll message and remove the poll state.")
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

    # Try delete the poll message
    try:
        channel = interaction.channel
        msg = await channel.fetch_message(poll.message_id)
        await msg.delete()
    except Exception:
        pass

    POLL_BY_CHANNEL.pop(channel_id, None)
    await interaction.response.send_message("🗑️ Poll deleted.", ephemeral=True)

# -----------------------
# Run
# -----------------------
bot.run(DISCORD_TOKEN)
