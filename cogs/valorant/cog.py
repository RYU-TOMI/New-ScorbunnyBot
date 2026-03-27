import discord
import json
import asyncio
from datetime import datetime, timedelta, timezone
from discord import app_commands
from discord.ext import commands

from db.database import get_user, save_user, delete_user, init_db
from .api import (
    authenticate, authenticate_2fa, refresh_token,
    get_entitlements_token, get_region, get_storefront,
    parse_daily_store, parse_night_market, _decode_puuid
)
from .assets import get_skin_info

# 2FA 대기 중인 유저 임시 저장
pending_2fa: dict[str, dict] = {}

class Valorant(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    async def cog_load(self):
        await init_db()

    async def _get_valid_tokens(self, user: dict) -> dict | None:
        """토큰 만료 시 자동 갱신. 실패 시 None 반환"""
        expires_at = user.get("expires_at")
        if expires_at:
            expires_dt = datetime.fromisoformat(expires_at)
            if datetime.now(timezone.utc) < expires_dt:
                return user  # 아직 유효

        # 토큰 만료 → cookies로 자동 갱신
        try:
            cookies = json.loads(user["cookies"])
            result = await refresh_token(cookies)

            expires_at = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()
            await save_user(
                discord_id=user["discord_id"],
                puuid=user["puuid"],
                region=user["region"],
                shard=user["shard"],
                access_token=result["access_token"],
                entitlements_token=result["entitlements_token"],
                cookies=json.dumps(result["cookies"]),
                expires_at=expires_at,
            )
            user["access_token"] = result["access_token"]
            user["entitlements_token"] = result["entitlements_token"]
            return user
        except Exception as e:
            print(f"토큰 갱신 실패: {e}")
            return None

    @app_commands.command(name="로그인", description="발로란트 계정을 연동합니다.")
    async def login(self, interaction: discord.Interaction, username: str, password: str):
        print("로그인 함수 호출됨")
        await interaction.response.defer(ephemeral=True)
        print("defer 완료")

        existing = await get_user(str(interaction.user.id))
        print(f"get_user 완료: {existing}")

        if existing:
            await interaction.followup.send(
                "✅ 이미 로그인되어 있어요. `/로그아웃` 후 다시 시도해주세요.", ephemeral=True
            )
            return

        print("authenticate 호출 전")
        try:
            result = await authenticate(username, password)
            print(f"authenticate 완료: {result['type']}")
        except Exception as e:
            print(f"로그인 오류: {e}")
            await interaction.followup.send(f"❌ 로그인 실패: {str(e)}", ephemeral=True)
            return

        if result['type'] == 'multifactor':
            pending_2fa[str(interaction.user.id)] = {
                'cookies': result['cookies'],
            }
            email = result.get('email', '')
            await interaction.followup.send(
                f"📧 2FA 인증이 필요해요. `{email}`로 전송된 코드를 `/인증코드` 명령어로 입력해주세요.",
                ephemeral=True
            )
            return

        await self._save_login(interaction, result['access_token'], result['id_token'], result['cookies'])

    @app_commands.command(name="인증코드", description="2FA 코드를 입력합니다.")
    async def verify_2fa(self, interaction: discord.Interaction, 코드: str):
        await interaction.response.defer(ephemeral=True)

        pending = pending_2fa.get(str(interaction.user.id))
        if not pending:
            await interaction.followup.send("❌ 진행 중인 로그인이 없어요. `/로그인`을 먼저 해주세요.", ephemeral=True)
            return

        try:
            result = await authenticate_2fa(코드, pending['cookies'])
            del pending_2fa[str(interaction.user.id)]
            await self._save_login(interaction, result['access_token'], result['id_token'], result['cookies'])
        except Exception as e:
            await interaction.followup.send(f"❌ 2FA 인증 실패: {str(e)}", ephemeral=True)

    async def _save_login(self, interaction: discord.Interaction, access_token: str, id_token: str, cookies: dict):
        """로그인 성공 후 DB 저장"""
        try:
            puuid = _decode_puuid(access_token)
            entitlements_token = await get_entitlements_token(access_token)
            region, shard = await get_region(access_token, id_token)
            expires_at = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()

            await save_user(
                discord_id=str(interaction.user.id),
                puuid=puuid,
                region=region,
                shard=shard,
                access_token=access_token,
                entitlements_token=entitlements_token,
                cookies=json.dumps(cookies),
                expires_at=expires_at,
            )
            await interaction.followup.send(
                "✅ 로그인 성공! `/상점`으로 오늘의 상점을 확인해보세요.", ephemeral=True
            )
        except Exception as e:
            await interaction.followup.send(f"❌ 저장 중 오류가 발생했어요: {str(e)}", ephemeral=True)

    @app_commands.command(name="상점", description="오늘의 발로란트 스킨 상점을 확인합니다.")
    async def store(self, interaction: discord.Interaction):
        await interaction.response.defer()

        user = await get_user(str(interaction.user.id))
        if not user:
            await interaction.followup.send("❌ 로그인이 필요해요. `/로그인`으로 먼저 계정을 연동해주세요.")
            return

        user = await self._get_valid_tokens(user)
        if not user:
            await interaction.followup.send(
                "⚠️ 토큰이 만료됐어요. `/로그아웃` 후 `/로그인`으로 다시 연동해주세요."
            )
            return

        try:
            storefront = await get_storefront(
                user["access_token"], user["entitlements_token"], user["puuid"], user["shard"]
            )
            daily, remaining = parse_daily_store(storefront)
            hours = remaining // 3600
            minutes = (remaining % 3600) // 60

            embeds = [discord.Embed(
                title="🛒 오늘의 상점",
                description=f"갱신까지 **{hours}시간 {minutes}분** 남았어요.",
                color=discord.Color.red(),
            )]

            for item in daily:
                skin = await get_skin_info(item["offer_id"])
                skin_embed = discord.Embed(
                    title=skin['name'],
                    description=f"💰 {item['cost']:,} VP | 등급: {skin['tier_name']}",
                    color=skin.get("color", 0x808080),
                )
                if skin["icon"]:
                    skin_embed.set_thumbnail(url=skin["icon"])
                embeds.append(skin_embed)

            await interaction.followup.send(embeds=embeds)

        except Exception as e:
            error_msg = str(e)
            if "400" in error_msg or "401" in error_msg:
                await interaction.followup.send("⚠️ 토큰이 만료됐어요. `/로그아웃` 후 `/로그인`으로 다시 연동해주세요.")
            else:
                await interaction.followup.send(f"❌ 상점 조회 중 오류가 발생했어요: {error_msg}")

    @app_commands.command(name="야시장", description="야시장을 확인합니다.")
    async def nightmarket(self, interaction: discord.Interaction):
        await interaction.response.defer()

        user = await get_user(str(interaction.user.id))
        if not user:
            await interaction.followup.send("❌ 로그인이 필요해요. `/로그인`으로 먼저 계정을 연동해주세요.")
            return

        user = await self._get_valid_tokens(user)
        if not user:
            await interaction.followup.send("⚠️ 토큰이 만료됐어요. `/로그아웃` 후 `/로그인`으로 다시 연동해주세요.")
            return

        try:
            storefront = await get_storefront(
                user["access_token"], user["entitlements_token"], user["puuid"], user["shard"]
            )
            night = parse_night_market(storefront)
            if not night:
                await interaction.followup.send("🌙 현재 야시장이 열려있지 않아요.")
                return

            embed = discord.Embed(title="🌙 야시장", color=discord.Color.dark_purple())
            for item in night:
                skin = await get_skin_info(item["offer_id"])
                embed.add_field(
                    name=skin['name'],
                    value=(
                        f"~~{item['cost']:,} VP~~ → **{item['discount_cost']:,} VP**\n"
                        f"🏷️ {item['discount_percent']}% 할인 | 등급: {skin['tier_name']}"
                    ),
                    inline=False,
                )
            await interaction.followup.send(embed=embed)

        except Exception as e:
            error_msg = str(e)
            if "400" in error_msg or "401" in error_msg:
                await interaction.followup.send("⚠️ 토큰이 만료됐어요. `/로그아웃` 후 `/로그인`으로 다시 연동해주세요.")
            else:
                await interaction.followup.send(f"❌ 야시장 조회 중 오류가 발생했어요: {error_msg}")

    @app_commands.command(name="로그아웃", description="발로란트 계정 연동을 해제합니다.")
    async def logout(self, interaction: discord.Interaction):
        user = await get_user(str(interaction.user.id))
        if not user:
            await interaction.response.send_message("❌ 로그인되어 있지 않아요.", ephemeral=True)
            return
        await delete_user(str(interaction.user.id))
        await interaction.response.send_message(
            "✅ 로그아웃됐어요. 저장된 인증 정보가 모두 삭제됐어요.", ephemeral=True
        )

    @app_commands.command(name="디비테스트", description="DB 테스트")
    async def db_test(self, interaction: discord.Interaction):
        print("디비테스트 시작")
        await interaction.response.defer(ephemeral=True)
        print("defer 완료")
        try:
            result = await get_user("123")
            print(f"get_user 결과: {result}")
            await interaction.followup.send(f"결과: {result}")
        except Exception as e:
            print(f"에러: {e}")
            await interaction.followup.send(f"에러: {e}")

async def setup(bot):
    await bot.add_cog(Valorant(bot))