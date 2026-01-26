import os
import json
import csv
import threading
from typing import List, Optional, Dict, Any

from flask import Flask
import discord
from discord.ext import commands
from dotenv import load_dotenv

load_dotenv()

# ----------------------------
# Config / Files
# ----------------------------
DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")

PINS_CSV_PATH = os.getenv("PINS_CSV_PATH", "pins.csv")
CLAIMS_PATH = os.getenv("CLAIMS_PATH", "claims.json")
POLL_STORE_PATH = os.getenv("POLL_STORE_PATH", "polls.json")

BOX_COUNT = int(os.getenv("BOX_COUNT", "10"))  # boxes 1..BOX_COUNT

# Up to 10 options
NUMBER_EMOJIS = ["1️⃣","2️⃣","3️⃣","4️⃣","5️⃣","6️⃣","7️⃣","8️⃣","9️⃣","🔟"]

# ----------------------------
# Flask keep-alive (Railway friendly)
# ----------------------------
app = Flask(__name__)

@app.get("/")
def home():
    return "OK", 200

def run_web():
    port = int(os.getenv("PORT", "8080"))
    app.run(host="0.0.0.0", port=port)

# ----------------------------
# Discord bot setup
# ----------------------------
intents = discord.Intents.default()
intents.message_content = True  # needed for prefix commands
intents.reactions = True        # needed to enforce one vote per person
intents.guilds = True

bot = commands.Bot(command_prefix="!", intents=intents)

# ----------------------------
# Helpers: JSON storage
# ----------------------------
def _load_json(path: str, default: Any) -> Any:
    if not os.path.exists(path):
        return default
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default

def _save_json(path: str, data: Any) -> None:
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)

# ----------------------------
# Starter kit pins/claims helpers
# ----------------------------
def _load_claims() -> dict:
    return _load_json(CLAIMS_PATH, {})

def _save_claims(claims: dict) -> None:
    _save_json(CLAIMS_PATH, claims)

def _load_pins() -> List[str]:
    if not os.path.exists(PINS_CSV_PATH):
        return []
    pins: List[str] = []
    with open(PINS_CSV_PATH, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            p = (row.get("pin") or "").strip()
            if p:
                pins.append(p)
    return pins

def _save_pins(pins: List[str]) -> None:
    with open(PINS_CSV_PATH, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["pin"])
        writer.writeheader()
        for p in pins:
            writer.writerow({"pin": p})

def _pop_next_pin() -> Optional[str]:
    pins = _load_pins()
    if not pins:
        return None
    next_pin = pins.pop(0)
    _save_pins(pins)
    return next_pin

def _get_next_available_box(claims: dict) -> Optional[int]:
    used = set()
    for v in claims.values():
        try:
            b = int(v.get("box", 0))
            if b > 0:
                used.add(b)
        except Exception:
            pass
    for box_num in range(1, BOX_COUNT + 1):
        if box_num not in used:
            return box_num
    return None

# ----------------------------
# Poll storage helpers
# ----------------------------
# Stored as:
# {
#   "<message_id>": {
#       "guild_id": 123,
#       "channel_id": 456,
#       "creator_id": 789,
#       "title": "...",
#       "options": ["...", "..."],
#       "emoji_map": {"1️⃣": 0, "2️⃣": 1, ...},
#       "closed": false
#   }
# }
def _load_polls() -> Dict[str, Any]:
    return _load_json(POLL_STORE_PATH, {})

def _save_polls(polls: Dict[str, Any]) -> None:
    _save_json(POLL_STORE_PATH, polls)

def _is_admin(ctx: commands.Context) -> bool:
    if not isinstance(ctx.author, discord.Member):
        return False
    perms = ctx.author.guild_permissions
    return perms.administrator or perms.manage_messages

# ----------------------------
# Events
# ----------------------------
@bot.event
async def on_ready():
    print(f"✅ Logged in as {bot.user} (ID: {bot.user.id})")

@bot.event
async def on_reaction_add(reaction: discord.Reaction, user: discord.User):
    # Enforce "one vote per person" on tracked polls only
    if user.bot:
        return

    message = reaction.message
    polls = _load_polls()
    poll = polls.get(str(message.id))
    if not poll:
        return

    # If closed, remove their reaction
    if poll.get("closed", False):
        try:
            await reaction.remove(user)
        except Exception:
            pass
        return

    emoji_str = str(reaction.emoji)
    emoji_map = poll.get("emoji_map", {})
    if emoji_str not in emoji_map:
        # Not one of the poll options; remove it to keep poll clean
        try:
            await reaction.remove(user)
        except Exception:
            pass
        return

    # One vote per person: remove any other poll-option reactions from this user
    try:
        for r in message.reactions:
            r_emoji = str(r.emoji)
            if r_emoji in emoji_map and r_emoji != emoji_str:
                await r.remove(user)
    except Exception:
        # If bot lacks permission to manage reactions, this won't work
        pass

# ----------------------------
# Starter kit claim (PIN + BOX #)
# ----------------------------
@bot.command(name="claimstarter")
async def claimstarter(ctx: commands.Context):
    if ctx.guild is None:
        await ctx.reply("Run this in the server, not in DMs.")
        return

    user_id = str(ctx.author.id)
    claims = _load_claims()

    if user_id in claims:
        box = claims[user_id].get("box", "?")
        await ctx.reply(f"You’ve already claimed your starter kit. Your box is **#{box}**. Check your DMs for the PIN.")
        return

    box_num = _get_next_available_box(claims)
    if box_num is None:
        await ctx.reply("All starter kit boxes are currently assigned. Ask an admin to reset boxes when ready.")
        return

    pin = _pop_next_pin()
    if not pin:
        await ctx.reply("No starter kit PINs are available right now. Ask an admin to add more.")
        return

    claims[user_id] = {"username": str(ctx.author), "pin": pin, "box": box_num}
    _save_claims(claims)

    try:
        await ctx.author.send(
            f"✅ **Democracy Ark Starter Kit**\n\n"
            f"📦 **Your box number:** **#{box_num}**\n"
            f"🔐 **Your PIN:** **{pin}**\n\n"
            f"Go to the Community Hub and open **Box #{box_num}** with that PIN.\n"
            f"Keep this private."
        )
        await ctx.reply(f"✅ Check your DMs — I’ve sent your PIN and your box number (**#{box_num}**).")
    except discord.Forbidden:
        await ctx.reply("I can’t DM you (your DMs are closed). Please open DMs and try again.")

# ----------------------------
# Admin: pins/claims/boxes
# ----------------------------
@bot.command(name="addpin")
@commands.has_permissions(administrator=True)
async def addpin(ctx: commands.Context, pin: str):
    pin = pin.strip()
    if not pin:
        await ctx.reply("Missing PIN.")
        return
    pins = _load_pins()
    pins.append(pin)
    _save_pins(pins)
    await ctx.reply(f"✅ Added PIN. Remaining unclaimed PINs: **{len(pins)}**")

@bot.command(name="pinsleft")
@commands.has_permissions(administrator=True)
async def pinsleft(ctx: commands.Context):
    pins = _load_pins()
    await ctx.reply(f"📦 Remaining unclaimed PINs: **{len(pins)}**")

@bot.command(name="resetclaim")
@commands.has_permissions(administrator=True)
async def resetclaim(ctx: commands.Context, member: discord.Member):
    claims = _load_claims()
    uid = str(member.id)
    if uid not in claims:
        await ctx.reply("That user has no claim recorded.")
        return
    old = claims.pop(uid)
    _save_claims(claims)
    await ctx.reply(f"✅ Reset claim for {member.mention}. (Old PIN: {old.get('pin')} • Box: #{old.get('box')})")

@bot.command(name="resetboxes")
@commands.has_permissions(administrator=True)
async def resetboxes(ctx: commands.Context):
    _save_claims({})
    await ctx.reply("✅ All starter kit boxes have been reset (all claims cleared).")

@bot.command(name="boxstatus")
@commands.has_permissions(administrator=True)
async def boxstatus(ctx: commands.Context):
    claims = _load_claims()
    used = sorted({int(v.get("box", 0)) for v in claims.values() if str(v.get("box", "")).isdigit()})
    used = [b for b in used if b > 0]
    if not used:
        await ctx.reply("📦 No boxes are currently assigned.")
        return
    await ctx.reply("📦 Assigned boxes: " + ", ".join([f"#{b}" for b in used]))

# ----------------------------
# Poll system (proper)
# ----------------------------
@bot.command(name="pollcreate")
@commands.has_permissions(manage_messages=True)
async def pollcreate(ctx: commands.Context, title: str, *options: str):
    # admins only (Manage Messages)
    if len(options) < 2:
        await ctx.reply("Need at least 2 options.")
        return
    if len(options) > 10:
        await ctx.reply("Max 10 options.")
        return

    # build embed
    lines: List[str] = []
    emoji_map: Dict[str, int] = {}
    for i, opt in enumerate(options):
        em = NUMBER_EMOJIS[i]
        emoji_map[em] = i
        lines.append(f"{em} {opt}")

    embed = discord.Embed(
        title="📊 Poll",
        description=f"**{title}**\n\n" + "\n".join(lines),
        color=discord.Color.blurple()
    )
    embed.set_footer(text=f"One vote per person • Started by {ctx.author.display_name}")

    msg = await ctx.send(embed=embed)

    # add reactions
    for i in range(len(options)):
        await msg.add_reaction(NUMBER_EMOJIS[i])

    # store poll
    polls = _load_polls()
    polls[str(msg.id)] = {
        "guild_id": ctx.guild.id if ctx.guild else None,
        "channel_id": ctx.channel.id,
        "creator_id": ctx.author.id,
        "title": title,
        "options": list(options),
        "emoji_map": emoji_map,
        "closed": False
    }
    _save_polls(polls)

    await ctx.reply(f"✅ Poll created. Message ID: `{msg.id}`", mention_author=False)

@bot.command(name="pollresults")
async def pollresults(ctx: commands.Context, message_id: int):
    polls = _load_polls()
    poll = polls.get(str(message_id))
    if not poll:
        await ctx.reply("Poll not found.")
        return

    # fetch message
    try:
        channel = await bot.fetch_channel(int(poll["channel_id"]))
        msg = await channel.fetch_message(int(message_id))
    except Exception:
        await ctx.reply("I can’t fetch that poll message.")
        return

    emoji_map = poll.get("emoji_map", {})
    options = poll.get("options", [])
    counts = [0] * len(options)

    # count reactions (exclude bot’s own reaction)
    for r in msg.reactions:
        e = str(r.emoji)
        if e in emoji_map:
            # r.count includes the bot's own reaction; subtract 1 if bot reacted (it did)
            n = max(0, r.count - 1)
            idx = int(emoji_map[e])
            if 0 <= idx < len(counts):
                counts[idx] = n

    total = sum(counts)
    lines = []
    for i, opt in enumerate(options):
        lines.append(f"{NUMBER_EMOJIS[i]} {opt} — **{counts[i]}**")

    status = "CLOSED" if poll.get("closed", False) else "OPEN"
    embed = discord.Embed(
        title=f"📊 Poll Results ({status})",
        description="\n".join(lines) + f"\n\nTotal votes: **{total}**",
        color=discord.Color.green() if poll.get("closed", False) else discord.Color.blurple()
    )
    await ctx.send(embed=embed)

@bot.command(name="pollclose")
@commands.has_permissions(manage_messages=True)
async def pollclose(ctx: commands.Context, message_id: int):
    polls = _load_polls()
    poll = polls.get(str(message_id))
    if not poll:
        await ctx.reply("Poll not found.")
        return

    if poll.get("closed", False):
        await ctx.reply("That poll is already closed.")
        return

    # mark closed
    poll["closed"] = True
    polls[str(message_id)] = poll
    _save_polls(polls)

    # update poll message footer
    try:
        channel = await bot.fetch_channel(int(poll["channel_id"]))
        msg = await channel.fetch_message(int(message_id))
        if msg.embeds:
            embed = msg.embeds[0]
            embed.set_footer(text=f"CLOSED • One vote per person • Started by <@{poll['creator_id']}>")
            await msg.edit(embed=embed)
    except Exception:
        pass

    await ctx.reply("✅ Poll closed. Votes are now locked (reactions removed if people try).")

@bot.command(name="polldelete")
@commands.has_permissions(manage_messages=True)
async def polldelete(ctx: commands.Context, message_id: int):
    polls = _load_polls()
    poll = polls.get(str(message_id))
    if not poll:
        await ctx.reply("Poll not found.")
        return

    # delete message
    try:
        channel = await bot.fetch_channel(int(poll["channel_id"]))
        msg = await channel.fetch_message(int(message_id))
        await msg.delete()
    except Exception:
        # even if deletion fails, remove from storage so it's not stuck
        pass

    polls.pop(str(message_id), None)
    _save_polls(polls)
    await ctx.reply("✅ Poll deleted.")

@bot.command(name="polllist")
@commands.has_permissions(manage_messages=True)
async def polllist(ctx: commands.Context):
    polls = _load_polls()
    channel_id = ctx.channel.id
    items = []
    for mid, p in polls.items():
        if int(p.get("channel_id", -1)) == channel_id:
            status = "CLOSED" if p.get("closed", False) else "OPEN"
            items.append(f"• `{mid}` — {status} — {p.get('title','(no title)')[:60]}")

    if not items:
        await ctx.reply("No tracked polls in this channel.")
        return

    await ctx.reply("\n".join(items))

# ----------------------------
# Main
# ----------------------------
if __name__ == "__main__":
    if not DISCORD_TOKEN:
        raise RuntimeError("DISCORD_TOKEN missing. Put it in Railway Variables.")

    threading.Thread(target=run_web, daemon=True).start()
    bot.run(DISCORD_TOKEN)
