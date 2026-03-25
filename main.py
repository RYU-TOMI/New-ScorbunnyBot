import discord
import asyncio
import os
import threading
from discord.ext import commands
from dotenv import load_dotenv

load_dotenv()

intents = discord.Intents.default()
intents.message_content = True
intents.voice_states = True

bot = commands.Bot(command_prefix="!", intents=intents)

def start_web_server():
    """웹 서버를 별도 스레드에서 실행"""
    from web.app import app
    app.run(
        host=os.getenv("WEB_HOST", "0.0.0.0"),
        port=int(os.getenv("WEB_PORT", 80)),
        debug=False,
        use_reloader=False,
    )

async def load_extensions():
    await bot.load_extension("cogs.music.cog")
    await bot.load_extension("cogs.valorant.cog")

@bot.event
async def on_ready():
    await bot.tree.sync()
    print(f"{bot.user} 로그인 완료")

async def main():
    # 웹 서버를 별도 스레드에서 시작
    web_thread = threading.Thread(target=start_web_server, daemon=True)
    web_thread.start()
    print("웹 서버 시작됨")

    async with bot:
        await load_extensions()
        await bot.start(os.getenv("DISCORD_TOKEN"))

asyncio.run(main())