import discord
import asyncio
from discord import app_commands
from discord.ext import commands

from .player import YTDLSource
from .queue import QueueManager
from .views import SearchView
from db.database import add_play_history, add_recap_history, get_random_from_history, get_history_count, get_history
from utils.embeds import now_playing_embed, queue_embed, search_embed, error_embed

queue_manager = QueueManager()


class Music(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self._empty_timers: dict[int, asyncio.Task] = {}

    def get_queue(self, guild_id: int):
        return queue_manager.get(guild_id)

    async def play_next(self, guild: discord.Guild, channel: discord.TextChannel):
        queue = self.get_queue(guild.id)
        vc = guild.voice_client

        if not vc:
            return

        is_autoplay = False
        next_track = queue.next()

        if not next_track:
            if not queue.autoplay:
                return

            count = await get_history_count(str(guild.id))
            if count == 0:
                return
            
            if count == 0:
                return
            
            if count < 30:
                 await channel.send(f"📚 자동재생은 재생 기록이 30곡 이상 쌓이면 활성화돼요. (현재 **{count}곡**)")
                 return

            # 최근 10개 제외 후 랜덤 선택, 없으면 전체에서 선택
            results = await get_random_from_history(str(guild.id), exclude_recent=10) \
                      or await get_random_from_history(str(guild.id), exclude_recent=0)

            if not results:
                return

            rec = results[0]
            queue.add(rec['url'], rec['title'])
            next_track = queue.next()
            is_autoplay = True
            await channel.send(f"🎵 자동재생: **{rec['title']}**")

        url, title, *rest = next_track
        requester = rest[0] if rest else guild.me  # 요청자 추출

        try:
            player = await YTDLSource.from_url(url, loop=self.bot.loop)
            queue.current = (url, title)
            queue.last_video_id = player.id
            queue.last_title = player.title

            def after_playing(error):
                if error:
                    print(f"재생 오류: {error}")
                asyncio.run_coroutine_threadsafe(
                    self.play_next(guild, channel), self.bot.loop
                )

            #
            if vc.is_playing():
                return

            vc.play(player, after=after_playing)

            if player.duration and player.duration <= 600:
                asyncio.create_task(add_play_history(
                    guild_id=str(guild.id),
                    video_id=player.id,
                    title=player.title,
                    url=url,
                ))
                asyncio.create_task(add_recap_history(
                    guild_id=str(guild.id),
                    video_id=player.id,
                    title=player.title,
                    url=url,
                ))
            await channel.send(embed=now_playing_embed(player, requester, autoplay=is_autoplay))

        except Exception as e:
            print(f"play_next 오류: {e}")
            await channel.send(embed=error_embed(f"재생 중 오류가 발생했어요: {str(e)}"))

    async def _play_track(self, interaction: discord.Interaction, url: str, player, is_url: bool):
        """공통 재생 로직"""
        if not interaction.guild.voice_client:
            await interaction.user.voice.channel.connect()

        queue = self.get_queue(interaction.guild.id)
        vc = interaction.guild.voice_client
        send = interaction.followup.send if is_url else interaction.channel.send

        # is_playing()과 is_paused() 둘 다 체크
        if not vc.is_playing() and not vc.is_paused():
            queue.current = (url, player.title, interaction.user)
            queue.last_video_id = player.id

            vc.play(player, after=lambda e: asyncio.run_coroutine_threadsafe(
                self.play_next(interaction.guild, interaction.channel), self.bot.loop
            ))

            if player.duration and player.duration <= 600:
                asyncio.create_task(add_play_history(
                    guild_id=str(interaction.guild.id),
                    video_id=player.id,
                    title=player.title,
                    url=url,
                ))
                asyncio.create_task(add_recap_history(
                    guild_id=str(interaction.guild.id),
                    video_id=player.id,
                    title=player.title,
                    url=url,
                ))
            await send(embed=now_playing_embed(player, interaction.user))
        else:
            if not queue.add(url, player.title, interaction.user):
                await send(embed=error_embed(f"대기열이 가득 찼어요. 최대 {queue.max_size}곡까지 추가할 수 있어요."))
                return
            await send(embed=queue_embed(queue.items(), queue.max_size, f"{player.title} 이 대기열에 추가됐어요!"))

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
            await interaction.followup.send(embed=error_embed(f"입장 중 오류가 발생했어요: {str(e)}"))

    @app_commands.command(name="재생", description="URL 또는 검색어로 음악을 재생합니다.")
    async def play(self, interaction: discord.Interaction, 검색어: str):
        if not interaction.user.voice:
            await interaction.response.send_message(embed=error_embed("먼저 음성 채널에 접속해 주세요."), ephemeral=True)
            return

        await interaction.response.defer()
        is_url = 검색어.startswith(("http://", "https://"))

        if is_url:
            try:
                player = await YTDLSource.from_url(검색어, loop=self.bot.loop)
            except Exception as e:
                await interaction.followup.send(embed=error_embed(f"오류가 발생했어요: {str(e)}"))
                return
            await self._play_track(interaction, 검색어, player, is_url=True)
        else:
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
            try:
                player = await YTDLSource.from_url(selected['url'], loop=self.bot.loop)
            except Exception as e:
                await interaction.channel.send(embed=error_embed(f"오류가 발생했어요: {str(e)}"))
                return
            await self._play_track(interaction, selected['url'], player, is_url=False)

    @app_commands.command(name="자동재생", description="자동재생을 끄거나 켭니다.")
    async def autoplay(self, interaction: discord.Interaction):
        queue = self.get_queue(interaction.guild.id)
        queue.autoplay = not queue.autoplay
        status = "활성화" if queue.autoplay else "비활성화"
        await interaction.response.send_message(f"🐰 자동재생 모드가 {status}됐어요.")

    @app_commands.command(name="히스토리", description="최근 재생한 곡 목록을 보여줍니다.")
    async def history(self, interaction: discord.Interaction):
        await interaction.response.defer()
        records = await get_history(str(interaction.guild.id), limit=10)

        if not records:
            await interaction.followup.send(embed=error_embed("아직 재생 기록이 없어요."))
            return

        embed = discord.Embed(title="🎵 최근 재생 목록", color=discord.Color.blurple())
        for i, record in enumerate(records, 1):
            embed.add_field(
                name=f"{i}. {record['title']}",
                value=f"▶ {record['play_count']}회 재생 | 마지막: {record['last_played_at'][:10]}",
                inline=False
            )
        await interaction.followup.send(embed=embed)

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
        await interaction.response.send_message("⏭️ 현재 곡을 건너뛰었어요.")

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
        queue.autoplay = False
        if vc.is_playing():
            vc.stop()
        await vc.disconnect()
        await interaction.followup.send("🐰 염버니가 음악을 멈추고 집으로 돌아갔어요.")


    @commands.Cog.listener()
    async def on_voice_state_update(self, member: discord.Member, before: discord.VoiceState, after: discord.VoiceState):
        """음성 채널 상태 변경 감지"""
        vc = member.guild.voice_client
        if not vc:
            return

        # 봇 자신의 상태 변경은 무시
        if member == member.guild.me:
            return

        # 봇이 있는 채널의 인원 체크
        channel = vc.channel
        non_bot_members = [m for m in channel.members if not m.bot]

        if len(non_bot_members) == 0:
            # 1분 타이머 시작
            guild_id = member.guild.id
            # 기존 타이머 취소
            if guild_id in self._empty_timers:
                self._empty_timers[guild_id].cancel()
            self._empty_timers[guild_id] = asyncio.create_task(
                self._auto_leave(member.guild, vc.channel)
            )
        else:
            # 누군가 들어오면 타이머 취소
            guild_id = member.guild.id
            if guild_id in self._empty_timers:
                self._empty_timers[guild_id].cancel()
                del self._empty_timers[guild_id]

    async def _auto_leave(self, guild: discord.Guild, channel: discord.VoiceChannel):
        """1분 후 자동 나가기"""
        try:
            await asyncio.sleep(60)
            vc = guild.voice_client
            if not vc:
                return

            # 아직 채널에 아무도 없으면 나가기
            non_bot_members = [m for m in channel.members if not m.bot]
            if len(non_bot_members) == 0:
                queue = self.get_queue(guild.id)
                queue.clear()
                queue.autoplay = False
                if vc.is_playing():
                    vc.stop()
                await vc.disconnect()

                # 텍스트 채널에 알림 (마지막으로 사용한 채널 찾기)
                text_channel = guild.system_channel or next(
                    (c for c in guild.text_channels if c.permissions_for(guild.me).send_messages),
                    None
                )
                if text_channel:
                    await text_channel.send("🐰 아무도 없어서 염버니가 집으로 돌아갔어요.")

        except asyncio.CancelledError:
            pass
        finally:
            self._empty_timers.pop(guild.id, None)


async def setup(bot):
    await bot.add_cog(Music(bot))