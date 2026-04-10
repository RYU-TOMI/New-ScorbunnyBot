import asyncio
import discord
from discord.ext import commands
from discord import app_commands
from . import api

# ── 상수 ──────────────────────────────────────────────────

SLOT_ORDER = [
    "모자", "얼굴장식", "눈장식", "귀고리",
    "상의", "하의", "한벌옷", "신발", "장갑", "망토", "벨트", "어깨장식",
    "무기", "보조무기", "엠블렘",
    "반지1", "반지2", "반지3", "반지4",
    "펜던트", "펜던트2",
    "포켓 아이템", "뱃지", "훈장", "안드로이드", "기계 심장",
]

POTENTIAL_GRADE_COLOR = {
    "레어":    0x77BFD4,
    "에픽":    0x9B59B6,
    "유니크":  0xF1C40F,
    "레전드리": 0x2ECC71,
}

POTENTIAL_GRADE_EMOJI = {
    "레어":    "🔵",
    "에픽":    "🟣",
    "유니크":  "🟡",
    "레전드리": "🟢",
}

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
    """장비 목록 — 슬롯별 요약"""
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
    """장비 상세 — 잠재/에디셔널/스타포스/업그레이드"""
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

    # 기본 정보
    upgrade_count = item.get("item_upgrade_count", 0)
    golden_hammer = item.get("golden_hammer_flag", "")
    upgrade_str = f"{upgrade_count}회"
    if golden_hammer == "1":
        upgrade_str += " (황금망치 사용)"
    embed.add_field(name="스타포스",   value=star_display,  inline=False)
    embed.add_field(name="업그레이드", value=upgrade_str,   inline=True)
    embed.add_field(name="아이템 레벨", value=str(item.get("item_base_option", {}).get("base_equipment_level", "-")), inline=True)
    embed.add_field(name="\u200b", value="\u200b", inline=True)

    # 잠재능력
    pot_opts = [
        item.get("potential_option_1", ""),
        item.get("potential_option_2", ""),
        item.get("potential_option_3", ""),
    ]
    pot_lines = [f"• {o}" for o in pot_opts if o]
    if pot_lines:
        embed.add_field(
            name=f"잠재능력 {grade_emoji} {grade}",
            value="\n".join(pot_lines),
            inline=False
        )

    # 에디셔널 잠재능력
    add_grade = item.get("additional_potential_option_grade", "")
    add_emoji = POTENTIAL_GRADE_EMOJI.get(add_grade, "")
    add_opts = [
        item.get("additional_potential_option_1", ""),
        item.get("additional_potential_option_2", ""),
        item.get("additional_potential_option_3", ""),
    ]
    add_lines = [f"• {o}" for o in add_opts if o]
    if add_lines:
        embed.add_field(
            name=f"에디셔널 잠재능력 {add_emoji} {add_grade}",
            value="\n".join(add_lines),
            inline=False
        )

    embed.set_footer(text=f"🍁 {basic['character_name']}  |  전날 기준 데이터 (Nexon Open API)")
    return embed


# ── View ─────────────────────────────────────────────────

class MapleView(discord.ui.View):
    def __init__(self, basic: dict, stat: dict, equipment: dict):
        super().__init__(timeout=120)
        self.basic = basic
        self.stat = stat
        self.equipment = equipment
        self.tab = "basic"

        # 장비 선택 드롭다운 추가
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

    def current_embed(self) -> discord.Embed:
        if self.tab == "basic":
            return build_basic_embed(self.basic, self.stat)
        return build_equipment_list_embed(self.basic, self.equipment)

    @discord.ui.button(label="📋 기본 정보", style=discord.ButtonStyle.primary, row=0)
    async def btn_basic(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.tab = "basic"
        self._refresh_buttons()
        # 드롭다운 숨김 처리
        if hasattr(self, "select"):
            self.select.disabled = (self.tab == "basic")
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
    def __init__(self, options, basic: dict, equipment: dict):
        super().__init__(
            placeholder="슬롯을 선택하면 장비 상세 정보를 볼 수 있어요",
            options=options,
            row=1
        )
        self.basic = basic
        self.slot_map = {
            item["item_equipment_slot"]: item
            for item in equipment.get("item_equipment", [])
        }

    async def callback(self, interaction: discord.Interaction):
        slot = self.values[0]
        item = self.slot_map.get(slot)
        if not item:
            await interaction.response.send_message("장비 정보를 찾을 수 없어요.", ephemeral=True)
            return
        embed = build_item_detail_embed(self.basic, item)
        await interaction.response.edit_message(embed=embed)


# ── Cog ──────────────────────────────────────────────────

class MapleCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="메이플", description="메이플스토리 캐릭터 정보를 조회합니다.")
    @app_commands.describe(닉네임="조회할 캐릭터 닉네임")
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


async def setup(bot):
    await bot.add_cog(MapleCog(bot))