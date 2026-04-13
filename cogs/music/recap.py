import discord
import asyncio
import os
from datetime import datetime, timezone
from discord import app_commands
from discord.ext import commands, tasks

from db.database import (
    get_recap_stats, get_recap_history_count,
    set_guild_setting, get_guild_setting
)

OWNER_ID = int(os.getenv("OWNER_ID", "0"))

# 분기 정의
QUARTERS = {
    1: ("1분기", 1, 3),
    2: ("2분기", 4, 6),
    3: ("3분기", 7, 9),
    4: ("4분기", 10, 12),
}

MIN_SONGS = 100  # 최소 곡 수


def is_owner():
    async def predicate(interaction: discord.Interaction) -> bool:
        if interaction.user.id != OWNER_ID:
            await interaction.response.send_message(
                "❌ 이 커맨드는 관리자만 사용할 수 있어요.", ephemeral=True
            )
            return False
        return True
    return app_commands.check(predicate)


def get_quarter_dates(year: int, quarter: int) -> tuple[str, str]:
    """분기의 시작일과 종료일 반환"""
    _, start_month, end_month = QUARTERS[quarter]
    start = f"{year}-{start_month:02d}-01 00:00:00"
    if end_month == 12:
        end = f"{year}-12-31 23:59:59"
    else:
        # 다음 달 1일 - 1초
        next_month = end_month + 1
        end = f"{year}-{next_month:02d}-01 00:00:00"
    return start, end


async def send_recap(guild: discord.Guild, year: int, quarter: int):
    """RECAP 임베드 생성 및 전송"""
    setting = await get_guild_setting(str(guild.id))
    if not setting or not setting.get("recap_channel_id"):
        return

    channel = guild.get_channel(int(setting["recap_channel_id"]))
    if not channel:
        return

    count = await get_recap_history_count(str(guild.id))
    if count < MIN_SONGS:
        print(f"곡 수 부족 ({count} < {MIN_SONGS})")
        return

    start, end = get_quarter_dates(year, quarter)
    stats = await get_recap_stats(str(guild.id), start, end)

    if stats["total"] == 0:
        return

    quarter_name, _, _ = QUARTERS[quarter]

    # 임베드 1: 통계
    stats_embed = discord.Embed(
        title=f"🎵 {year}년 {quarter_name} RECAP",
        description=f"**{year}년 {quarter_name}**의 음악 결산이에요!",
        color=discord.Color.blurple(),
    )
    stats_embed.add_field(name="🎧 총 재생 횟수", value=f"**{stats['total']:,}회**", inline=True)
    stats_embed.add_field(name="🎵 총 곡 수", value=f"**{stats['unique_count']:,}곡**", inline=True)
    stats_embed.set_footer(text=f"{year}년 {quarter_name} • {start[:10]} ~ {end[:10]}")

    # 임베드 2: TOP 5
    top_embed = discord.Embed(
        title="🏆 이번 분기 TOP 5",
        color=discord.Color.gold(),
    )
    medals = ["🥇", "🥈", "🥉", "4️⃣", "5️⃣"]
    for i, track in enumerate(stats["top_tracks"]):
        top_embed.add_field(
            name=f"{medals[i]} {track['title']}",
            value=f"▶ {track['play_count']}회 재생",
            inline=False,
        )

    # 임베드 3: 플레이리스트 안내
    playlist_embed = discord.Embed(
        title="📋 RECAP 플레이리스트",
        description=f"`/recap`으로 이번 분기 TOP 10곡을 대기열에 추가할 수 있어요!",
        color=discord.Color.green(),
    )

    await channel.send(
        content=f"@everyone 🎵 **{year}년 {quarter_name} RECAP**이 도착했어요!",
        embeds=[stats_embed, top_embed, playlist_embed],
    )


class Recap(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.recap_task.start()

    def cog_unload(self):
        self.recap_task.cancel()

    @tasks.loop(hours=1)
    async def recap_task(self):
        """매 시간 자정 체크 - 분기 첫날이면 RECAP 발송"""
        now = datetime.now(timezone.utc)

        # 분기 첫날 자정 체크 (1/4/7/10월 1일)
        if now.day != 1 or now.month not in [1, 4, 7, 10] or now.hour != 0:
            return

        # 직전 분기 계산
        if now.month == 1:
            year, quarter = now.year - 1, 4
        else:
            year = now.year
            quarter = {4: 1, 7: 2, 10: 3}[now.month]

        for guild in self.bot.guilds:
            try:
                await send_recap(guild, year, quarter)
            except Exception as e:
                print(f"RECAP 발송 오류 ({guild.name}): {e}")

    @recap_task.before_loop
    async def before_recap_task(self):
        await self.bot.wait_until_ready()

    @commands.command(name="봇채널설정")
    @commands.is_owner()
    async def set_channel(self, ctx, 채널: discord.TextChannel):
        await set_guild_setting(str(ctx.guild.id), str(채널.id))
        await ctx.send(f"✅ RECAP 채널이 {채널.mention}으로 설정됐어요.")

    @set_channel.error
    async def set_channel_error(self, ctx, error):
        if isinstance(error, commands.NotOwner):
            await ctx.send("❌ 봇 관리자만 사용할 수 있어요.", delete_after=5)
        elif isinstance(error, commands.MissingRequiredArgument):
            await ctx.send("❌ 사용법: `!봇채널설정 #채널`", delete_after=5)
        elif isinstance(error, commands.BadArgument):
            await ctx.send("❌ 채널을 찾을 수 없어요.", delete_after=5)

    @app_commands.command(name="리캡", description="분기별 RECAP 플레이리스트를 대기열에 추가합니다.")
    @app_commands.describe(분기="RECAP을 볼 분기를 선택하세요.")
    @app_commands.choices(분기=[
        app_commands.Choice(name="2026년 1분기 (1~3월)", value="2026-1"),
        app_commands.Choice(name="2026년 2분기 (4~6월)", value="2026-2"),
        app_commands.Choice(name="2026년 3분기 (7~9월)", value="2026-3"),
        app_commands.Choice(name="2026년 4분기 (10~12월)", value="2026-4"),
        app_commands.Choice(name="2027년 1분기 (1~3월)", value="2027-1"),
        app_commands.Choice(name="2027년 2분기 (4~6월)", value="2027-2"),
        app_commands.Choice(name="2027년 3분기 (7~9월)", value="2027-3"),
        app_commands.Choice(name="2027년 4분기 (10~12월)", value="2027-4"),
    ])
    async def recap(self, interaction: discord.Interaction, 분기: str):
        await interaction.response.defer()

        if not interaction.user.voice:
            await interaction.followup.send(
                embed=discord.Embed(description="❌ 먼저 음성 채널에 접속해 주세요.", color=discord.Color.red())
            )
            return

        year, quarter = map(int, 분기.split("-"))
        start, end = get_quarter_dates(year, quarter)
        quarter_name = QUARTERS[quarter][0]

        stats = await get_recap_stats(str(interaction.guild.id), start, end)

        if not stats["top_playlist"]:
            await interaction.followup.send(
                embed=discord.Embed(
                    description=f"❌ {year}년 {quarter_name}의 재생 기록이 없어요.",
                    color=discord.Color.red()
                )
            )
            return

        # 음성 채널 연결
        if not interaction.guild.voice_client:
            await interaction.user.voice.channel.connect()

        # 대기열에 추가
        from .queue import QueueManager
        queue_manager = QueueManager()
        # cog.py의 queue_manager를 참조하기 위해 bot에서 Music cog 가져오기
        music_cog = interaction.client.cogs.get("Music")
        if not music_cog:
            await interaction.followup.send(embed=discord.Embed(description="❌ 음악 기능을 찾을 수 없어요.", color=discord.Color.red()))
            return

        queue = music_cog.get_queue(interaction.guild.id)
        added = 0
        for track in stats["top_playlist"]:
            if queue.add(track["url"], track["title"], interaction.user):
                added += 1

        embed = discord.Embed(
            title=f"📋 {year}년 {quarter_name} RECAP 플레이리스트",
            description=f"TOP {added}곡을 대기열에 추가했어요!",
            color=discord.Color.green(),
        )
        for i, track in enumerate(stats["top_playlist"][:added], 1):
            embed.add_field(
                name=f"{i}. {track['title']}",
                value=f"▶ {track['play_count']}회 재생",
                inline=False,
            )
        await interaction.followup.send(embed=embed)

        # 재생 중이 아니면 바로 재생
        vc = interaction.guild.voice_client
        if vc and not vc.is_playing():
            await music_cog.play_next(interaction.guild, interaction.channel)

    @commands.command(name="recap테스트")
    @commands.is_owner()
    async def recap_test(self, ctx):
        now = datetime.now(timezone.utc)
        quarter = (now.month - 1) // 3 + 1
        year = now.year
        await send_recap(ctx.guild, year, quarter)
        await ctx.send("✅ RECAP 테스트 발송 완료!")

    @recap_test.error
    async def recap_test_error(self, ctx, error):
        if isinstance(error, commands.NotOwner):
            await ctx.send("❌ 봇 관리자만 사용할 수 있어요.", delete_after=5)


    @commands.command(name="recap미리보기")
    @commands.is_owner()
    async def recap_preview(self, ctx):
        now = datetime.now(timezone.utc)
        quarter = (now.month - 1) // 3 + 1
        year = now.year
        quarter_name = QUARTERS[quarter][0]

        start, end = get_quarter_dates(year, quarter)
        stats = await get_recap_stats(str(ctx.guild.id), start, end)

        if stats["total"] == 0:
            await ctx.send("❌ 이번 분기 재생 기록이 없어요.")
            return

        embed = discord.Embed(
            title=f"🔍 {year}년 {quarter_name} RECAP 미리보기",
            color=discord.Color.blurple(),
        )
        embed.add_field(name="🎧 총 재생 횟수", value=f"**{stats['total']:,}회**", inline=True)
        embed.add_field(name="🎵 총 곡 수", value=f"**{stats['unique_count']:,}곡**", inline=True)

        medals = ["🥇", "🥈", "🥉", "4️⃣", "5️⃣"]
        for i, track in enumerate(stats["top_tracks"]):
            embed.add_field(
                name=f"{medals[i]} {track['title']}",
                value=f"▶ {track['play_count']}회 재생",
                inline=False,
            )

        await ctx.send(embed=embed)

    @recap_preview.error
    async def recap_preview_error(self, ctx, error):
        if isinstance(error, commands.NotOwner):
            await ctx.send("❌ 봇 관리자만 사용할 수 있어요.", delete_after=5)

    @commands.command(name="음악커맨드")
    @commands.is_owner()
    async def music_command_guide(self, ctx):
        embed = discord.Embed(
            title="📋 음악 관리자 커맨드 가이드",
            color=discord.Color.blurple()
        )
        embed.add_field(
            name="🎵 RECAP 설정",
            value="`!봇채널설정 #채널` — RECAP 발송 채널 설정",
            inline=False
        )
        embed.add_field(
            name="🔧 테스트",
            value=(
                "`!recap테스트` — RECAP 즉시 발송\n"
                "`!recap미리보기` — 현재 분기 RECAP 미리 확인"
            ),
            inline=False
        )
        await ctx.send(embed=embed)

    @music_command_guide.error
    async def music_command_guide_error(self, ctx, error):
        if isinstance(error, commands.NotOwner):
            await ctx.send("❌ 봇 관리자만 사용할 수 있어요.", delete_after=5)


async def setup(bot):
    await bot.add_cog(Recap(bot))