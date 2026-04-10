import discord
import json
import os
import certifi
import ssl as _ssl
import aiohttp
from datetime import datetime, timedelta, timezone
from base64 import urlsafe_b64decode
from urllib.parse import parse_qsl, urlsplit
from discord import app_commands
from discord.ext import commands

from db.database import get_user, save_user, delete_user, init_db
from .api import get_storefront, parse_daily_store, parse_night_market, REGION_SHARD_MAP
from .assets import get_skin_info

WEB_BASE_URL = os.getenv("WEB_BASE_URL", "http://localhost")
RIOT_LOGIN_URL = (
    "https://auth.riotgames.com/authorize"
    "?redirect_uri=https%3A%2F%2Fplayvalorant.com%2Fopt_in"
    "&client_id=play-valorant-web-prod"
    "&response_type=token%20id_token"
    "&nonce=1"
    "&scope=account%20openid"
)
_SSL_CTX = _ssl.create_default_context(cafile=certifi.where())


class Valorant(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    async def cog_load(self):
        pass

    async def _get_valid_user(self, interaction: discord.Interaction) -> dict | None:
        """유저 조회 + 토큰 만료 체크 공통 로직"""
        user = await get_user(str(interaction.user.id))
        if not user:
            await interaction.followup.send("❌ 로그인이 필요해요. `/로그인`으로 먼저 계정을 연동해주세요.")
            return None
        if user.get("expires_at"):
            expires_at = datetime.fromisoformat(user["expires_at"])
            if datetime.now(timezone.utc) >= expires_at:
                await interaction.followup.send("⚠️ 토큰이 만료됐어요. `/로그아웃` 후 `/로그인`으로 다시 연동해주세요.")
                return None
        return user

    @app_commands.command(name="로그인", description="발로란트 계정을 연동합니다.")
    async def login(self, interaction: discord.Interaction):
        user = await get_user(str(interaction.user.id))
        if user:
            await interaction.response.send_message(
                "✅ 이미 로그인되어 있어요. 다시 로그인하려면 `/로그아웃` 후 다시 시도해주세요.",
                ephemeral=True,
            )
            return

        embed = discord.Embed(
            title="🔐 발로란트 로그인",
            description=(
                "**1단계:** 아래 링크에서 라이엇 계정으로 로그인하세요.\n"
                "**2단계:** 로그인 후 빈 페이지(404)가 뜨면, **주소창의 URL 전체**를 복사하세요.\n"
                "**3단계:** `/인증` 명령어에 복사한 URL을 붙여넣으세요."
            ),
            color=discord.Color.red(),
        )
        embed.add_field(name="🔗 로그인 링크", value=f"[여기를 클릭하세요]({RIOT_LOGIN_URL})", inline=False)
        embed.set_footer(text="⚠️ 비밀번호는 Riot 공식 페이지에서만 입력됩니다.")
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(name="인증", description="로그인 후 복사한 URL을 입력합니다.")
    async def verify(self, interaction: discord.Interaction, url: str):
        await interaction.response.defer(ephemeral=True)

        if await get_user(str(interaction.user.id)):
            await interaction.followup.send("✅ 이미 로그인되어 있어요. `/로그아웃` 후 다시 시도해주세요.", ephemeral=True)
            return

        try:
            if "#" not in url:
                await interaction.followup.send("❌ 올바른 URL이 아니에요. 로그인 후 리다이렉트된 주소창의 URL 전체를 복사해주세요.", ephemeral=True)
                return

            fragment = urlsplit(url).fragment
            params = dict(parse_qsl(fragment))
            access_token = params.get("access_token")
            id_token = params.get("id_token")

            if not access_token:
                await interaction.followup.send("❌ URL에서 토큰을 찾을 수 없어요. 다시 시도해주세요.", ephemeral=True)
                return

            payload = access_token.split(".")[1]
            puuid = json.loads(urlsafe_b64decode(f"{payload}===")).get("sub")

            async with aiohttp.ClientSession(connector=aiohttp.TCPConnector(ssl=_SSL_CTX)) as session:
                async with session.post(
                    "https://entitlements.auth.riotgames.com/api/token/v1",
                    headers={"Authorization": f"Bearer {access_token}", "Content-Type": "application/json"},
                    json={},
                ) as resp:
                    entitlements_token = (await resp.json())["entitlements_token"]

                region, shard = "kr", "kr"
                try:
                    async with session.put(
                        "https://riot-geo.pas.si.riotgames.com/pas/v1/product/valorant",
                        headers={"Authorization": f"Bearer {access_token}", "Content-Type": "application/json"},
                        json={"id_token": id_token or ""},
                    ) as resp:
                        if resp.status == 200:
                            live = (await resp.json()).get("affinities", {}).get("live", "kr")
                            region = live
                            shard = REGION_SHARD_MAP.get(live, "kr")
                except Exception:
                    pass

            expires_at = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()
            await save_user(
                discord_id=str(interaction.user.id),
                puuid=puuid, region=region, shard=shard,
                access_token=access_token, entitlements_token=entitlements_token,
                cookies="{}", expires_at=expires_at,
            )
            await interaction.followup.send("✅ 로그인 성공! `/상점`으로 오늘의 상점을 확인해보세요.", ephemeral=True)

        except Exception as e:
            await interaction.followup.send(f"❌ 인증 중 오류가 발생했어요: {str(e)}", ephemeral=True)

    @app_commands.command(name="상점", description="오늘의 발로란트 스킨 상점을 확인합니다.")
    async def store(self, interaction: discord.Interaction):
        await interaction.response.defer()

        user = await self._get_valid_user(interaction)
        if not user:
            return

        try:
            storefront = await get_storefront(
                user["access_token"], user["entitlements_token"], user["puuid"], user["shard"]
            )
            daily, remaining = parse_daily_store(storefront)
            hours, minutes = remaining // 3600, (remaining % 3600) // 60

            embeds = [discord.Embed(
                title="🛒 오늘의 상점",
                description=f"갱신까지 **{hours}시간 {minutes}분** 남았어요.",
                color=discord.Color.red(),
            )]
            for item in daily:
                skin = await get_skin_info(item["offer_id"])
                embed = discord.Embed(
                    title=skin['name'],
                    description=f"💰 {item['cost']:,} VP | 등급: {skin['tier_name']}",
                    color=skin.get("color", 0x808080),
                )
                if skin["icon"]:
                    embed.set_thumbnail(url=skin["icon"])
                embeds.append(embed)

            await interaction.followup.send(embeds=embeds)

        except Exception as e:
            msg = "⚠️ 토큰이 만료됐어요. `/로그아웃` 후 `/로그인`으로 다시 연동해주세요." \
                if "400" in str(e) or "401" in str(e) else f"❌ 상점 조회 중 오류가 발생했어요: {e}"
            await interaction.followup.send(msg)

    @app_commands.command(name="야시장", description="야시장을 확인합니다.")
    async def nightmarket(self, interaction: discord.Interaction):
        await interaction.response.defer()

        user = await self._get_valid_user(interaction)
        if not user:
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
            msg = "⚠️ 토큰이 만료됐어요. `/로그아웃` 후 `/로그인`으로 다시 연동해주세요." \
                if "400" in str(e) or "401" in str(e) else f"❌ 야시장 조회 중 오류가 발생했어요: {e}"
            await interaction.followup.send(msg)

    @app_commands.command(name="로그아웃", description="발로란트 계정 연동을 해제합니다.")
    async def logout(self, interaction: discord.Interaction):
        if not await get_user(str(interaction.user.id)):
            await interaction.response.send_message("❌ 로그인되어 있지 않아요.", ephemeral=True)
            return
        await delete_user(str(interaction.user.id))
        await interaction.response.send_message("✅ 로그아웃되었어요. 저장된 인증 정보가 모두 삭제되었어요.", ephemeral=True)


async def setup(bot):
    await bot.add_cog(Valorant(bot))