import discord
import asyncio
import os
from discord.ext import commands
from dotenv import load_dotenv

load_dotenv()

intents = discord.Intents.default()
intents.message_content = True
intents.voice_states = True

bot = commands.Bot(command_prefix="!", intents=intents)

async def load_extensions():
    await bot.load_extension("cogs.music.cog")
    await bot.load_extension("cogs.valorant.cog")

@bot.event
async def on_ready():
    await bot.tree.sync()
    print(f"{bot.user} 로그인 완료")

async def main():
    async with bot:
        await load_extensions()
        await bot.start(os.getenv("DISCORD_TOKEN"))

asyncio.run(main())