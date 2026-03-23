import discord
import asyncio
from discord import app_commands
from discord.ext import commands

from .player import YTDLSource
from .queue import QueueManager
from .views import SearchView
from utils.embeds import now_playing_embed, queue_embed, search_embed, error_embed

queue_manager = QueueManager()

class Music(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    def get_queue(self, guild_id: int):
        return queue_manager.get(guild_id)

    async def play_next(self, guild: discord.Guild, channel: discord.TextChannel):
        queue = self.get_queue(guild.id)
        vc = guild.voice_client

        if not vc:
            return

        next_track = queue.next()
        if not next_track:
            return

        url, title, requester = next_track
        try:
            player = await YTDLSource.from_url(url, loop=self.bot.loop)
            queue.current = (url, title, requester)

            def after_playing(error):
                if error:
                    print(f"재생 오류: {error}")
                asyncio.run_coroutine_threadsafe(
                    self.play_next(guild, channel), self.bot.loop
                )

            vc.play(player, after=after_playing)
            await channel.send(embed=now_playing_embed(player, requester))
        except Exception as e:
            print(f"play_next 오류: {e}")
            await channel.send(embed=error_embed(f"재생 중 오류가 발생했어요: {str(e)}"))

    @app_commands.command(name="입장", description="염버니를 음성 채널로 불러옵니다.")
    async def join(self, interaction: discord.Interaction):
        if not interaction.user.voice:
            await interaction.response.send_message(embed=error_embed("먼저 음성 채널에 접속해 주세요."), ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True)
        try:
            channel = interaction.user.voice.channel
            await channel.connect()
            await interaction.followup.send(f"🐰 염버니가 {channel} 채널에 들어왔어요!")
        except Exception as e:
            print(f"입장 오류: {e}")
            await interaction.followup.send(embed=error_embed(f"입장 중 오류가 발생했어요: {str(e)}"))

    @app_commands.command(name="재생", description="URL로 음악을 재생합니다.")
    async def play(self, interaction: discord.Interaction, url: str):
        if not interaction.user.voice:
            await interaction.response.send_message(embed=error_embed("먼저 음성 채널에 접속해 주세요."), ephemeral=True)
            return
        if not url.startswith(("http://", "https://")):
            await interaction.response.send_message(embed=error_embed("URL 형식이 아닙니다. /검색을 이용해주세요!"), ephemeral=True)
            return

        await interaction.response.defer()

        if not interaction.guild.voice_client:
            await interaction.user.voice.channel.connect()

        queue = self.get_queue(interaction.guild.id)

        try:
            player = await YTDLSource.from_url(url, loop=self.bot.loop)
        except Exception as e:
            await interaction.followup.send(embed=error_embed(f"오류가 발생했어요: {str(e)}"))
            return

        vc = interaction.guild.voice_client

        if not vc.is_playing():
            queue.current = (url, player.title, interaction.user)
            vc.play(player, after=lambda e: asyncio.run_coroutine_threadsafe(
                self.play_next(interaction.guild, interaction.channel), self.bot.loop
            ))
            await interaction.followup.send(embed=now_playing_embed(player, interaction.user))
        else:
            if not queue.add(url, player.title, interaction.user):
                await interaction.followup.send(embed=error_embed(f"대기열이 가득 찼어요. 최대 {queue.max_size}곡까지 추가할 수 있어요."))
                return
            await interaction.followup.send(embed=queue_embed(queue.items(), queue.max_size, f"{player.title} 이 대기열에 추가됐어요!"))

    @app_commands.command(name="검색", description="유튜브에서 음악을 검색합니다.")
    async def search(self, interaction: discord.Interaction, 검색어: str):
        if not interaction.user.voice:
            await interaction.response.send_message(embed=error_embed("먼저 음성 채널에 접속해 주세요."), ephemeral=True)
            return

        await interaction.response.defer()
        results = await YTDLSource.search(검색어, loop=self.bot.loop)

        if not results:
            await interaction.followup.send(embed=error_embed("검색 결과가 없어요."))
            return

        view = SearchView()
        search_msg = await interaction.followup.send(embed=search_embed(검색어, results), view=view)
        await view.wait()
        await search_msg.delete()

        if view.value is None:
            cancel_msg = await interaction.channel.send("❌ 검색이 취소되었어요.")
            await asyncio.sleep(5)
            await cancel_msg.delete()
            return

        selected = results[view.value - 1]

        if not interaction.guild.voice_client:
            await interaction.user.voice.channel.connect()

        queue = self.get_queue(interaction.guild.id)

        if len(queue) >= queue.max_size:
            await interaction.channel.send(embed=error_embed(f"대기열이 가득 찼어요. 최대 {queue.max_size}곡까지 추가할 수 있어요."))
            return

        try:
            player = await YTDLSource.from_url(selected['url'], loop=self.bot.loop)
        except Exception as e:
            await interaction.channel.send(embed=error_embed(f"오류가 발생했어요: {str(e)}"))
            return

        vc = interaction.guild.voice_client

        if not vc.is_playing():
            queue.current = (selected['url'], player.title, interaction.user)
            vc.play(player, after=lambda e: asyncio.run_coroutine_threadsafe(
                self.play_next(interaction.guild, interaction.channel), self.bot.loop
            ))
            await interaction.channel.send(embed=now_playing_embed(player, interaction.user))
        else:
            queue.add(selected['url'], player.title, interaction.user)
            await interaction.channel.send(embed=queue_embed(queue.items(), queue.max_size, f"{player.title} 이 대기열에 추가됐어요!"))

    @app_commands.command(name="스킵", description="현재 재생 중인 음악을 건너뜁니다.")
    async def skip(self, interaction: discord.Interaction):
        vc = interaction.guild.voice_client
        if not vc:
            await interaction.response.send_message(embed=error_embed("염버니가 음성 채널에 없어요."), ephemeral=True)
            return
        queue = self.get_queue(interaction.guild.id)
        if queue.loop or queue.loop_current:
            await interaction.response.send_message(embed=error_embed("루프 모드가 활성화되어 있을 때는 스킵할 수 없어요."), ephemeral=True)
            return
        if vc.is_playing():
            vc.stop()
        await interaction.response.send_message("⏭️ 현재 곡을 건너뛰었어요.", ephemeral=True)

    @app_commands.command(name="일시정지", description="음악을 일시정지합니다.")
    async def pause(self, interaction: discord.Interaction):
        vc = interaction.guild.voice_client
        if not vc or not vc.is_playing():
            await interaction.response.send_message(embed=error_embed("재생 중인 음악이 없어요."), ephemeral=True)
            return
        vc.pause()
        await interaction.response.send_message("⏸️ 음악이 일시정지됐어요.", ephemeral=True)

    @app_commands.command(name="다시재생", description="일시정지된 음악을 다시 재생합니다.")
    async def resume(self, interaction: discord.Interaction):
        vc = interaction.guild.voice_client
        if not vc or not vc.is_paused():
            await interaction.response.send_message(embed=error_embed("일시정지된 음악이 없어요."), ephemeral=True)
            return
        vc.resume()
        await interaction.response.send_message("▶️ 음악이 다시 재생됐어요.", ephemeral=True)

    @app_commands.command(name="대기열", description="현재 대기열을 보여줍니다.")
    async def showqueue(self, interaction: discord.Interaction):
        queue = self.get_queue(interaction.guild.id)
        if queue.is_empty():
            await interaction.response.send_message(embed=error_embed("대기열에 음악이 없어요."), ephemeral=True)
            return
        await interaction.response.send_message(embed=queue_embed(queue.items(), queue.max_size), ephemeral=True)

    @app_commands.command(name="삭제", description="대기열에서 특정 곡을 삭제합니다.")
    async def remove(self, interaction: discord.Interaction, 번호: int):
        queue = self.get_queue(interaction.guild.id)
        removed = queue.remove(번호)
        if not removed:
            await interaction.response.send_message(embed=error_embed(f"올바른 번호를 입력해 주세요. (1~{len(queue)})"), ephemeral=True)
            return
        await interaction.response.send_message(f"🗑️ {번호}번 곡 '{removed[1]}'이 삭제됐어요.", ephemeral=True)

    @app_commands.command(name="반복", description="대기열 전체를 반복합니다.")
    async def loop(self, interaction: discord.Interaction):
        queue = self.get_queue(interaction.guild.id)
        queue.loop = not queue.loop
        queue.loop_current = False
        status = "활성화" if queue.loop else "비활성화"
        await interaction.response.send_message(f"🔁 전체 반복 모드가 {status}됐어요.")

    @app_commands.command(name="한곡반복", description="현재 곡을 반복합니다.")
    async def loop_one(self, interaction: discord.Interaction):
        queue = self.get_queue(interaction.guild.id)
        queue.loop_current = not queue.loop_current
        queue.loop = False
        status = "활성화" if queue.loop_current else "비활성화"
        await interaction.response.send_message(f"🔂 한 곡 반복 모드가 {status}됐어요.")

    @app_commands.command(name="나가", description="음악을 멈추고 음성 채널에서 나갑니다.")
    async def stop(self, interaction: discord.Interaction):
        vc = interaction.guild.voice_client
        if not vc:
            await interaction.response.send_message(embed=error_embed("염버니가 음성 채널에 없어요."), ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True)
        queue = self.get_queue(interaction.guild.id)
        queue.clear()
        queue_manager.remove(interaction.guild.id)
        if vc.is_playing():
            vc.stop()
        await vc.disconnect()
        await interaction.followup.send("🐰 염버니가 음악을 멈추고 집으로 돌아갔어요.")

async def setup(bot):
    await bot.add_cog(Music(bot))