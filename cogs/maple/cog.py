import asyncio
import os
import discord
from discord.ext import commands, tasks
from discord import app_commands
from datetime import datetime, timezone, timedelta
from . import api
from db.database import (
    init_sunday_channels, set_sunday_channel,
    get_all_sunday_channels, delete_sunday_channel,
    get_last_sunday_url, set_last_sunday_url,
    set_sunday_role, get_sunday_role
)

KST = timezone(timedelta(hours=9))

SLOT_ORDER = [
    "모자", "얼굴장식", "눈장식", "귀고리",
    "상의", "하의", "한벌옷", "신발", "장갑", "망토", "벨트", "어깨장식",
    "무기", "보조무기", "엠블렘",
    "반지1", "반지2", "반지3", "반지4",
    "펜던트", "펜던트2",
    "포켓 아이템", "뱃지", "훈장", "안드로이드", "기계 심장",
]

POTENTIAL_GRADE_COLOR = {
    "레어":     0x77BFD4,
    "에픽":     0x9B59B6,
    "유니크":   0xF1C40F,
    "레전드리": 0x2ECC71,
}

POTENTIAL_GRADE_EMOJI = {
    "레어":     "🔵",
    "에픽":     "🟣",
    "유니크":   "🟡",
    "레전드리": "🟢",
}

# ── Owner 체크 ────────────────────────────────────────────

def is_owner():
    async def predicate(interaction: discord.Interaction) -> bool:
        owner_id = int(os.getenv("OWNER_ID", "0"))
        if interaction.user.id != owner_id:
            await interaction.response.send_message(
                "❌ 이 커맨드는 봇 관리자만 사용할 수 있어요.", ephemeral=True
            )
            return False
        return True
    return app_commands.check(predicate)

# ── 임베드 빌더 ──────────────────────────────────────────

def build_basic_embed(basic: dict, stat: dict) -> discord.Embed:
    stat_map = {s["stat_name"]: s["stat_value"] for s in stat.get("final_stat", [])}
    embed = discord.Embed(title=f"🍁 {basic['character_name']}", color=0xE7221B)
    embed.set_thumbnail(url=basic.get("character_image", ""))
    embed.add_field(name="월드",   value=basic.get("world_name", "-"),      inline=True)
    embed.add_field(name="직업",   value=basic.get("character_class", "-"), inline=True)
    embed.add_field(name="레벨",   value=f"Lv. {basic.get('character_level', '-')}", inline=True)
    embed.add_field(name="인기도", value=str(basic.get("character_popularity", "-")), inline=True)
    embed.add_field(name="길드",   value=basic.get("character_guild_name") or "없음", inline=True)
    embed.add_field(name="\u200b", value="\u200b", inline=True)

    cp = stat_map.get("전투력", "-")
    embed.add_field(name="전투력", value=f"{int(cp):,}" if cp != "-" else "-", inline=False)

    key_stats = ["STR", "DEX", "INT", "LUK", "최대 HP"]
    lines = [f"**{k}**: {stat_map[k]}" for k in key_stats if k in stat_map]
    if lines:
        embed.add_field(name="주요 스탯", value="\n".join(lines), inline=False)

    embed.set_footer(text="📋 기본 정보  |  전날 기준 데이터 (Nexon Open API)")
    return embed


def build_equipment_list_embed(basic: dict, equipment: dict) -> discord.Embed:
    embed = discord.Embed(
        title=f"🍁 {basic['character_name']} — 장비 목록",
        description="아래 목록에서 장비를 선택하면 상세 정보를 볼 수 있어요.",
        color=0xE7221B
    )
    embed.set_thumbnail(url=basic.get("character_image", ""))
    slot_map = {item["item_equipment_slot"]: item for item in equipment.get("item_equipment", [])}
    lines = []
    for slot in SLOT_ORDER:
        item = slot_map.get(slot)
        if not item:
            continue
        stars = item.get("starforce", "0")
        star_str = f"⭐{stars} " if stars and stars != "0" else ""
        grade = item.get("potential_option_grade", "")
        grade_emoji = POTENTIAL_GRADE_EMOJI.get(grade, "⚪")
        lines.append(f"{grade_emoji} `{slot}` {star_str}**{item['item_name']}**")

    mid = (len(lines) + 1) // 2
    if lines[:mid]:
        embed.add_field(name="\u200b", value="\n".join(lines[:mid]), inline=True)
    if lines[mid:]:
        embed.add_field(name="\u200b", value="\n".join(lines[mid:]), inline=True)

    embed.set_footer(text="🎽 장비 목록  |  슬롯 선택 메뉴에서 상세 정보 확인")
    return embed


def build_item_detail_embed(basic: dict, item: dict) -> discord.Embed:
    grade = item.get("potential_option_grade", "")
    color = POTENTIAL_GRADE_COLOR.get(grade, 0xE7221B)
    grade_emoji = POTENTIAL_GRADE_EMOJI.get(grade, "")
    stars = item.get("starforce", "0")
    star_display = f"{'⭐' * min(int(stars), 25)} ({stars}성)" if stars and stars != "0" else "없음"

    embed = discord.Embed(
        title=f"{grade_emoji} {item['item_name']}",
        description=f"`{item.get('item_equipment_slot', '')}` 슬롯",
        color=color
    )
    embed.set_thumbnail(url=item.get("item_icon", ""))

    upgrade_count = item.get("item_upgrade_count", 0)
    golden_hammer = item.get("golden_hammer_flag", "")
    upgrade_str = f"{upgrade_count}회" + (" (황금망치 사용)" if golden_hammer == "1" else "")
    embed.add_field(name="스타포스",    value=star_display, inline=False)
    embed.add_field(name="업그레이드",  value=upgrade_str,  inline=True)
    embed.add_field(name="아이템 레벨", value=str(item.get("item_base_option", {}).get("base_equipment_level", "-")), inline=True)
    embed.add_field(name="\u200b", value="\u200b", inline=True)

    pot_opts = [item.get(f"potential_option_{i}", "") for i in range(1, 4)]
    pot_lines = [f"• {o}" for o in pot_opts if o]
    if pot_lines:
        embed.add_field(name=f"잠재능력 {grade_emoji} {grade}", value="\n".join(pot_lines), inline=False)

    add_grade = item.get("additional_potential_option_grade", "")
    add_emoji = POTENTIAL_GRADE_EMOJI.get(add_grade, "")
    add_opts = [item.get(f"additional_potential_option_{i}", "") for i in range(1, 4)]
    add_lines = [f"• {o}" for o in add_opts if o]
    if add_lines:
        embed.add_field(name=f"에디셔널 잠재능력 {add_emoji} {add_grade}", value="\n".join(add_lines), inline=False)

    embed.set_footer(text=f"🍁 {basic['character_name']}  |  전날 기준 데이터 (Nexon Open API)")
    return embed


def build_sunday_embed(data: dict, image_url: str = None) -> discord.Embed:
    embed = discord.Embed(
        title=f"🍁 {data['title']}",
        url=data["url"],
        color=0xE7221B
    )
    if data.get("period"):
        embed.add_field(name="📅 이벤트 기간", value=data["period"], inline=False)
    if image_url:
        embed.set_image(url=image_url)
    embed.set_footer(text="출처: 메이플스토리 공식 홈페이지")
    return embed


async def send_sunday(channel: discord.TextChannel, data: dict):
    images = data.get("images", [])

    # 역할 멘션 텍스트
    role_id = await get_sunday_role(channel.guild.id)
    mention = f"<@&{role_id}>" if role_id else ""

    if not images:
        await channel.send(content=mention or None, embed=build_sunday_embed(data))
        return

    # 첫 번째 이미지만 전송
    await channel.send(content=mention or None, embed=build_sunday_embed(data, image_url=images[0]))


# ── View ─────────────────────────────────────────────────

class MapleView(discord.ui.View):
    def __init__(self, basic, stat, equipment):
        super().__init__(timeout=120)
        self.basic = basic
        self.stat = stat
        self.equipment = equipment
        self.tab = "basic"

        slot_map = {item["item_equipment_slot"]: item for item in equipment.get("item_equipment", [])}
        options = []
        for slot in SLOT_ORDER:
            item = slot_map.get(slot)
            if not item:
                continue
            grade = item.get("potential_option_grade", "")
            emoji = POTENTIAL_GRADE_EMOJI.get(grade, "⚪")
            stars = item.get("starforce", "0")
            star_str = f"⭐{stars} " if stars and stars != "0" else ""
            label = f"{slot} — {star_str}{item['item_name']}"[:100]
            options.append(discord.SelectOption(label=label, value=slot, emoji=emoji))

        if options:
            self.select = EquipmentSelect(options[:25], basic, equipment)
            self.add_item(self.select)

        self._refresh_buttons()

    def _refresh_buttons(self):
        self.btn_basic.disabled     = (self.tab == "basic")
        self.btn_equipment.disabled = (self.tab == "equipment")

    def current_embed(self):
        if self.tab == "basic":
            return build_basic_embed(self.basic, self.stat)
        return build_equipment_list_embed(self.basic, self.equipment)

    @discord.ui.button(label="📋 기본 정보", style=discord.ButtonStyle.primary, row=0)
    async def btn_basic(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.tab = "basic"
        self._refresh_buttons()
        if hasattr(self, "select"):
            self.select.disabled = True
        await interaction.response.edit_message(embed=self.current_embed(), view=self)

    @discord.ui.button(label="🎽 장비 정보", style=discord.ButtonStyle.secondary, row=0)
    async def btn_equipment(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.tab = "equipment"
        self._refresh_buttons()
        if hasattr(self, "select"):
            self.select.disabled = False
        await interaction.response.edit_message(embed=self.current_embed(), view=self)

    async def on_timeout(self):
        for child in self.children:
            child.disabled = True


class EquipmentSelect(discord.ui.Select):
    def __init__(self, options, basic, equipment):
        super().__init__(
            placeholder="슬롯을 선택하면 장비 상세 정보를 볼 수 있어요",
            options=options,
            row=1
        )
        self.basic = basic
        self.slot_map = {item["item_equipment_slot"]: item for item in equipment.get("item_equipment", [])}

    async def callback(self, interaction: discord.Interaction):
        item = self.slot_map.get(self.values[0])
        if not item:
            await interaction.response.send_message("장비 정보를 찾을 수 없어요.", ephemeral=True)
            return
        await interaction.response.edit_message(embed=build_item_detail_embed(self.basic, item))


# ── Cog ──────────────────────────────────────────────────

class MapleCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.sunday_check.start()

    async def cog_load(self):
        await init_sunday_channels()

    def cog_unload(self):
        self.sunday_check.cancel()

    @tasks.loop(minutes=30)
    async def sunday_check(self):
        now = datetime.now(KST)
        is_friday_window = now.weekday() == 4 and (
            (now.hour == 10 and now.minute >= 10) or
            (now.hour == 11) or
            (now.hour == 12 and now.minute <= 10)
        )
        is_sunday_backup = now.weekday() == 6 and now.hour == 0 and now.minute < 5

        if not (is_friday_window or is_sunday_backup):
            return  # 해당 시간대 아니면 즉시 종료, Playwright 호출 없음

        # DB에서 마지막 전송 URL 확인
        last_url = await get_last_sunday_url()

        data = await api.fetch_sunday_maple()
        if not data:
            return

        # 같은 URL이면 이미 보낸 것 → 스킵
        if data["url"] == last_url:
            return

        # 새 썬데이 발견 → 전송
        targets = await get_all_sunday_channels()
        for guild_id, channel_id in targets:
            channel = self.bot.get_channel(channel_id)
            if channel:
                await send_sunday(channel, data)

        # DB에 저장 → 재시작해도 중복 전송 없음
        await set_last_sunday_url(data["url"])

    @sunday_check.before_loop
    async def before_sunday_check(self):
        await self.bot.wait_until_ready()

    # ── 슬래시 커맨드 ─────────────────────────────────────

    @app_commands.command(name="메이플", description="메이플스토리 캐릭터 정보를 조회합니다.")
    @app_commands.describe(닉네임="조회할 캐릭터 닉네임")
    @is_owner()
    async def maple(self, interaction: discord.Interaction, 닉네임: str):
        await interaction.response.defer()
        try:
            data = await api.fetch_all(닉네임)
        except ValueError as e:
            await interaction.followup.send(f"❌ {e}")
            return
        except Exception as e:
            await interaction.followup.send(f"❌ 오류가 발생했습니다: {e}")
            return

        view = MapleView(data["basic"], data["stat"], data["equipment"])
        await interaction.followup.send(embed=view.current_embed(), view=view)

    @app_commands.command(name="썬데이", description="이번 주 썬데이 메이플 정보를 조회합니다.")
    @is_owner()
    async def sunday(self, interaction: discord.Interaction):
        await interaction.response.defer()
        data = await api.fetch_sunday_maple()
        if not data:
            await interaction.followup.send("❌ 썬데이 메이플 정보를 가져올 수 없어요.")
            return
        await send_sunday(interaction.channel, data)
        await interaction.followup.send("✅ 완료!", ephemeral=True)

    # ── 관리자용 커맨드 ─────────────────────────────────────

    @commands.command(name="메이플알림설정")
    @commands.is_owner()
    async def set_sunday(self, ctx, 채널: discord.TextChannel, 역할: discord.Role = None):
        await set_sunday_channel(ctx.guild.id, 채널.id)
        if 역할:
            await set_sunday_role(ctx.guild.id, 역할.id)

        msg = f"✅ {채널.mention} 채널을 썬데이 메이플 알림 채널로 설정했어요!\n"
        if 역할:
            msg += f"📢 {역할.mention} 역할을 멘션할게요.\n"
        msg += "매주 금요일 오전 10시경 공지가 올라오면 자동으로 전송돼요."
        await ctx.send(msg)

    @commands.command(name="메이플알림해제")
    @commands.is_owner()
    async def unset_sunday(self, ctx):
        await delete_sunday_channel(ctx.guild.id)
        await ctx.send("✅ 썬데이 메이플 알림을 해제했어요.")

    @set_sunday.error
    @unset_sunday.error
    async def admin_error(self, ctx, error):
        if isinstance(error, commands.NotOwner):
            await ctx.send("❌ 봇 관리자만 사용할 수 있어요.", delete_after=5)
        elif isinstance(error, commands.MissingRequiredArgument):
            await ctx.send("❌ 사용법: `!메이플알림설정 #채널 [@역할]`", delete_after=5)
        elif isinstance(error, commands.BadArgument):
            await ctx.send("❌ 채널 또는 역할을 찾을 수 없어요.", delete_after=5)

    @commands.command(name="썬데이테스트")
    @commands.is_owner()
    async def sunday_test(self, ctx):
        targets = await get_all_sunday_channels()
        if not targets:
            await ctx.send("❌ 설정된 알림 채널이 없어요. `!메이플알림설정`으로 먼저 채널을 등록해줘요.")
            return

        data = await api.fetch_sunday_maple()
        if not data:
            await ctx.send("❌ 파싱 실패.")
            return

        sent = []
        for guild_id, channel_id in targets:
            channel = self.bot.get_channel(channel_id)
            if channel:
                await send_sunday(channel, data)
                sent.append(f"#{channel.name} ({channel.guild.name})")

        result = "\n".join(sent) if sent else "전송 가능한 채널 없음"
        await ctx.send(f"✅ 전송 완료:\n{result}")

    @sunday_test.error
    async def sunday_test_error(self, ctx, error):
        if isinstance(error, commands.NotOwner):
            await ctx.send("❌ 봇 관리자만 사용할 수 있어요.", delete_after=5)

    @commands.command(name="메이플커맨드")
    @commands.is_owner()
    async def command_guide(self, ctx):
        embed = discord.Embed(
            title="📋 관리자 커맨드 가이드",
            color=0xE7221B
        )
        embed.add_field(
            name="🍁 썬데이 메이플 알림 설정",
            value=(
                "`!메이플알림설정 #채널` — 알림 채널 설정 (역할 멘션 없음)\n"
                "`!메이플알림설정 #채널 @역할` — 알림 채널 + 역할 멘션 설정\n"
                "`!메이플알림해제` — 알림 채널 해제"
            ),
            inline=False
        )
        embed.add_field(
            name="🔧 테스트",
            value="`!썬데이테스트` — 등록된 채널에 즉시 전송",
            inline=False
        )
        await ctx.send(embed=embed)

    @command_guide.error
    async def command_guide_error(self, ctx, error):
        if isinstance(error, commands.NotOwner):
            await ctx.send("❌ 봇 관리자만 사용할 수 있어요.", delete_after=5)


async def setup(bot):
    await bot.add_cog(MapleCog(bot))