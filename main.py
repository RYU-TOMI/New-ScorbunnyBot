import discord
import asyncio
import os
from discord import app_commands
from discord.ext import commands
from dotenv import load_dotenv
from db.database import init_db

load_dotenv()

intents = discord.Intents.default()
intents.message_content = True
intents.voice_states = True

bot = commands.Bot(command_prefix="!", owner_id=int(os.getenv("OWNER_ID", "0")), intents=intents)


async def load_extensions():
    await bot.load_extension("cogs.music.cog")
    await bot.load_extension("cogs.music.recap")
    await bot.load_extension("cogs.valorant.cog")
    await bot.load_extension("cogs.maple.cog")
    print("모든 확장 로드 완료")


@bot.event
async def on_ready():
    synced = await bot.tree.sync()
    print(f"{bot.user} 로그인 완료")
    print(f"동기화된 커맨드: {[cmd.name for cmd in synced]}")

@bot.event
async def on_app_command_error(interaction: discord.Interaction, error: app_commands.AppCommandError):
    print(f"커맨드 오류: {error}")
    await interaction.response.send_message(f"오류: {str(error)}", ephemeral=True)


async def main():
    async with bot:
        await init_db()
        await load_extensions()
        await bot.start(os.getenv("DISCORD_TOKEN"))


asyncio.run(main())