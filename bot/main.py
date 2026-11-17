import os
import sqlite3
import io
from datetime import datetime, timedelta, time, timezone
from zoneinfo import ZoneInfo

import discord
from discord import app_commands
from discord.ext import commands, tasks
from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill, Alignment
from openpyxl.utils import get_column_letter

BOT_NAME = "[E] Polcom"
DB_PATH = os.getenv("DATABASE_PATH", "polcom.sqlite3")
TZ = ZoneInfo("Europe/Copenhagen")

intents = discord.Intents.default()
bot = commands.Bot(command_prefix="!", intents=intents)

def db():
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    return con

def init_db():
    with db() as con:
        con.execute("""CREATE TABLE IF NOT EXISTS config (
            guild_id INTEGER PRIMARY KEY,
            police_role_id INTEGER,
            leadership_role_id INTEGER,
            log_channel_id INTEGER,
            report_channel_id INTEGER
        )""")
        con.execute("""CREATE TABLE IF NOT EXISTS shifts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            guild_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            started_at TEXT NOT NULL,
            ended_at TEXT,
            seconds INTEGER
        )""")

def get_config(guild_id):
    with db() as con:
        return con.execute("SELECT * FROM config WHERE guild_id=?", (guild_id,)).fetchone()

def save_config(guild_id, police_role, leadership_role, log_channel, report_channel):
    with db() as con:
        con.execute("""INSERT INTO config
            (guild_id, police_role_id, leadership_role_id, log_channel_id, report_channel_id)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(guild_id) DO UPDATE SET
            police_role_id=excluded.police_role_id,
            leadership_role_id=excluded.leadership_role_id,
            log_channel_id=excluded.log_channel_id,
            report_channel_id=excluded.report_channel_id
        """, (guild_id, police_role.id, leadership_role.id, log_channel.id, report_channel.id))

def has_role(member, role_id):
    return role_id is not None and any(r.id == role_id for r in getattr(member, "roles", []))

def is_police(member, guild_id):
    cfg = get_config(guild_id)
    return cfg and has_role(member, cfg["police_role_id"])

def is_leadership(member, guild_id):
    cfg = get_config(guild_id)
    return cfg and (member.guild_permissions.administrator or has_role(member, cfg["leadership_role_id"]))

def fmt_seconds(seconds):
    seconds = max(0, int(seconds or 0))
    hours, rem = divmod(seconds, 3600)
    minutes = rem // 60
    return f"{hours} t. {minutes:02d} min."

def now_utc():
    return datetime.now(timezone.utc)

def parse_dt(value):
    return datetime.fromisoformat(value)

async def send_log(guild, message):
    cfg = get_config(guild.id)
    if not cfg or not cfg["log_channel_id"]:
        return
    channel = guild.get_channel(cfg["log_channel_id"])
    if channel:
        await channel.send(message)

def open_shift(guild_id, user_id):
    with db() as con:
        active = con.execute("""SELECT id FROM shifts
            WHERE guild_id=? AND user_id=? AND ended_at IS NULL""",
            (guild_id, user_id)).fetchone()
        if active:
            return False
        con.execute("INSERT INTO shifts (guild_id,user_id,started_at) VALUES (?,?,?)",
                    (guild_id, user_id, now_utc().isoformat()))
        return True

def close_shift(guild_id, user_id):
    with db() as con:
        row = con.execute("""SELECT * FROM shifts
            WHERE guild_id=? AND user_id=? AND ended_at IS NULL
            ORDER BY id DESC LIMIT 1""", (guild_id, user_id)).fetchone()
        if not row:
            return None
        end = now_utc()
        start = parse_dt(row["started_at"])
        seconds = int((end - start).total_seconds())
        con.execute("UPDATE shifts SET ended_at=?, seconds=? WHERE id=?",
                    (end.isoformat(), seconds, row["id"]))
        return start, end, seconds

def create_report(guild_id, days=7):
    since = (now_utc() - timedelta(days=days)).isoformat()
    with db() as con:
        rows = con.execute("""SELECT user_id, started_at, ended_at, seconds
            FROM shifts WHERE guild_id=? AND started_at>=?
            ORDER BY started_at DESC""", (guild_id, since)).fetchall()
    totals = {}
    for r in rows:
        uid = r["user_id"]
        totals[uid] = totals.get(uid, 0) + (r["seconds"] or 0)
    return rows, totals

def excel_file(guild, rows):
    wb = Workbook()
    ws = wb.active
    ws.title = "Vagtregistrering"
    ws.append(["Betjent", "Start (København)", "Slut (København)", "Varighed"])
    for cell in ws[1]:
        cell.font = Font(bold=True, color="FFFFFF")
        cell.fill = PatternFill("solid", fgColor="17365D")
        cell.alignment = Alignment(horizontal="center")
    for r in rows:
        member = guild.get_member(r["user_id"])
        name = member.display_name if member else f"Discord-ID {r['user_id']}"
        start = parse_dt(r["started_at"]).astimezone(TZ).strftime("%d-%m-%Y %H:%M")
        end = parse_dt(r["ended_at"]).astimezone(TZ).strftime("%d-%m-%Y %H:%M") if r["ended_at"] else "Stadig på vagt"
        duration = fmt_seconds(r["seconds"]) if r["seconds"] is not None else "Ikke afsluttet"
        ws.append([name, start, end, duration])
    for col, width in enumerate([28, 23, 23, 20], start=1):
        ws.column_dimensions[get_column_letter(col)].width = width
    out = io.BytesIO()
    wb.save(out)
    out.seek(0)
    return out

class ClockPanel(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="STEMPEL IND", style=discord.ButtonStyle.success, emoji="🟢", custom_id="polcom:clock_in")
    async def clock_in(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not interaction.guild or not is_police(interaction.user, interaction.guild.id):
            return await interaction.response.send_message("Du har ikke adgang. Kun medlemmer med politiets rolle kan stemple.", ephemeral=True)
        if not open_shift(interaction.guild.id, interaction.user.id):
            return await interaction.response.send_message("Du er allerede stemplet ind.", ephemeral=True)
        local = now_utc().astimezone(TZ).strftime("%d-%m-%Y kl. %H:%M")
        await interaction.response.send_message(f"Du er stemplet ind. God vagt! 🚔 ({local})", ephemeral=True)
        await send_log(interaction.guild, f"🟢 **VAGT STARTET** · {interaction.user.mention} · {local}")

    @discord.ui.button(label="STEMPEL UD", style=discord.ButtonStyle.danger, emoji="🔴", custom_id="polcom:clock_out")
    async def clock_out(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not interaction.guild or not is_police(interaction.user, interaction.guild.id):
            return await interaction.response.send_message("Du har ikke adgang. Kun medlemmer med politiets rolle kan stemple.", ephemeral=True)
        result = close_shift(interaction.guild.id, interaction.user.id)
        if not result:
            return await interaction.response.send_message("Du har ikke en aktiv vagt.", ephemeral=True)
        start, end, seconds = result
        local = end.astimezone(TZ).strftime("%d-%m-%Y kl. %H:%M")
        await interaction.response.send_message(f"Du er stemplet ud. Din vagt varede **{fmt_seconds(seconds)}**. Tak for indsatsen!", ephemeral=True)
        await send_log(interaction.guild, f"🔴 **VAGT AFSLUTTET** · {interaction.user.mention} · Varighed: **{fmt_seconds(seconds)}** · {local}")

@bot.event
async def on_ready():
    init_db()
    bot.add_view(ClockPanel())
    try:
        await bot.tree.sync()
    except Exception as e:
        print(f"Kunne ikke synkronisere kommandoer: {e}")
    if not weekly_report.is_running():
        weekly_report.start()
    print(f"{BOT_NAME} er online som {bot.user}")

@bot.tree.command(name="opsætning", description="Opsæt Polcoms roller og logkanaler")
@app_commands.checks.has_permissions(administrator=True)
@app_commands.describe(
    politirolle="Rollen som giver betjente adgang til at stemple",
    ledelsesrolle="Rollen som må se rapporter og oversigter",
    logkanal="Kanal til alle ind- og udstemplinger",
    rapportkanal="Kanal til ugentlige rapporter"
)
async def setup(interaction: discord.Interaction, politirolle: discord.Role,
                ledelsesrolle: discord.Role, logkanal: discord.TextChannel,
                rapportkanal: discord.TextChannel):
    save_config(interaction.guild_id, politirolle, ledelsesrolle, logkanal, rapportkanal)
    await interaction.response.send_message(
        "✅ **Polcom er sat op!**\n"
        f"Politirolle: {politirolle.mention}\nLedelsesrolle: {ledelsesrolle.mention}\n"
        f"Logkanal: {logkanal.mention}\nRapportkanal: {rapportkanal.mention}",
        ephemeral=True)

@bot.tree.command(name="vagtpanel", description="Opret panelet til ind- og udstempling")
@app_commands.checks.has_permissions(administrator=True)
async def panel(interaction: discord.Interaction):
    await interaction.response.send_message(
        "🚔 **[E] POLCOM – VAGTREGISTRERING**\n"
        "Brug knapperne nedenfor til at starte og afslutte din vagt.\n"
        "Kun medlemmer med politiets rolle har adgang.",
        view=ClockPanel())

@bot.tree.command(name="mine_timer", description="Se dine egne registrerede timer")
async def my_hours(interaction: discord.Interaction):
    if not interaction.guild or not is_police(interaction.user, interaction.guild.id):
        return await interaction.response.send_message("Denne funktion er kun for politiets medlemmer.", ephemeral=True)
    rows, totals = create_report(interaction.guild.id, 3650)
    seconds = totals.get(interaction.user.id, 0)
    with db() as con:
        active = con.execute("""SELECT started_at FROM shifts WHERE guild_id=? AND user_id=?
            AND ended_at IS NULL""", (interaction.guild.id, interaction.user.id)).fetchone()
    extra = ""
    if active:
        extra = f"\nDu er aktuelt på vagt siden {parse_dt(active['started_at']).astimezone(TZ).strftime('%d-%m-%Y %H:%M')}."
    await interaction.response.send_message(f"📊 **Dine registrerede timer**\nAfsluttede vagter: **{fmt_seconds(seconds)}**{extra}", ephemeral=True)

@bot.tree.command(name="vagtoversigt", description="Se betjentenes timer (ledelsen)")
async def overview(interaction: discord.Interaction):
    if not interaction.guild or not is_leadership(interaction.user, interaction.guild.id):
        return await interaction.response.send_message("Du har ikke adgang til ledelsens oversigt.", ephemeral=True)
    rows, totals = create_report(interaction.guild.id, 7)
    if not totals:
        return await interaction.response.send_message("Der er endnu ingen registrerede vagter i de seneste 7 dage.", ephemeral=True)
    lines = ["**📊 VAGTOVERSIGT – SENESTE 7 DAGE**"]
    for uid, seconds in sorted(totals.items(), key=lambda x: x[1], reverse=True):
        member = interaction.guild.get_member(uid)
        name = member.display_name if member else f"Ukendt bruger ({uid})"
        lines.append(f"• **{name}** – {fmt_seconds(seconds)}")
    await interaction.response.send_message("\n".join(lines), ephemeral=True)

@bot.tree.command(name="excelrapport", description="Hent Excel-rapport for de seneste 7 dage (ledelsen)")
async def excel_report(interaction: discord.Interaction):
    if not interaction.guild or not is_leadership(interaction.user, interaction.guild.id):
        return await interaction.response.send_message("Du har ikke adgang til Excel-rapporten.", ephemeral=True)
    rows, _ = create_report(interaction.guild.id, 7)
    if not rows:
        return await interaction.response.send_message("Der er ingen vagter at eksportere i perioden.", ephemeral=True)
    file = discord.File(excel_file(interaction.guild, rows), filename="Polcom_ugerapport.xlsx")
    await interaction.response.send_message("📄 Her er Excel-rapporten for de seneste 7 dage.", file=file, ephemeral=True)

@tasks.loop(time=time(hour=20, minute=0, tzinfo=TZ))
async def weekly_report():
    # Sendes hver søndag kl. 20.00 dansk tid.
    if datetime.now(TZ).weekday() != 6:
        return
    for guild in bot.guilds:
        cfg = get_config(guild.id)
        if not cfg or not cfg["report_channel_id"]:
            continue
        channel = guild.get_channel(cfg["report_channel_id"])
        if not channel:
            continue
        rows, totals = create_report(guild.id, 7)
        if not totals:
            await channel.send("📊 **[E] Polcom – ugentlig rapport**\nDer er ingen afsluttede vagter registreret i denne uge.")
            continue
        lines = ["📊 **[E] POLCOM – UGENTLIG AKTIVITETSRAPPORT**", "Periode: seneste 7 dage"]
        for uid, seconds in sorted(totals.items(), key=lambda x: x[1], reverse=True):
            member = guild.get_member(uid)
            name = member.display_name if member else f"Discord-ID {uid}"
            lines.append(f"• **{name}** – {fmt_seconds(seconds)}")
        report_file = discord.File(excel_file(guild, rows), filename="Polcom_ugerapport.xlsx")
        await channel.send("\n".join(lines), file=report_file)

@weekly_report.before_loop
async def before_weekly_report():
    await bot.wait_until_ready()

@setup.error
async def setup_error(interaction: discord.Interaction, error):
    if isinstance(error, app_commands.MissingPermissions):
        await interaction.response.send_message("Kun Discord-administratorer kan bruge denne kommando.", ephemeral=True)
    else:
        if not interaction.response.is_done():
            await interaction.response.send_message("Der opstod en fejl under opsætningen.", ephemeral=True)
        print(error)

TOKEN = os.getenv("DISCORD_TOKEN")
if not TOKEN:
    raise RuntimeError("DISCORD_TOKEN mangler. Opret en miljøvariabel med din bot-token.")
bot.run(TOKEN)
