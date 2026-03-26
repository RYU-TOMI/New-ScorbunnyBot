import discord
import uuid
from datetime import datetime, timedelta, timezone
from discord import app_commands
from discord.ext import commands
from base64 import urlsafe_b64decode
from urllib.parse import parse_qsl, urlsplit
import json
import aiohttp
import certifi
import ssl as _ssl

from db.database import (
    get_user, save_user, delete_user,
    save_login_session, init_db
)
from .api import get_storefront, parse_daily_store, parse_night_market, REGION_SHARD_MAP
from .assets import get_skin_info

import os
WEB_BASE_URL = os.getenv("WEB_BASE_URL", "http://localhost")

RIOT_LOGIN_URL = (
    "https://auth.riotgames.com/authorize"
    "?redirect_uri=https%3A%2F%2Fplayvalorant.com%2Fopt_in"
    "&client_id=play-valorant-web-prod"
    "&response_type=token%20id_token"
    "&nonce=1"
    "&scope=account%20openid"
)


class Valorant(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    async def cog_load(self):
        await init_db()

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
                "**2단계:** 로그인 후 빈 페이지가 뜨면, **주소창의 URL 전체**를 복사하세요.\n"
                "**3단계:** `/인증` 명령어에 복사한 URL을 붙여넣으세요."
            ),
            color=discord.Color.red(),
        )
        embed.add_field(
            name="🔗 로그인 링크",
            value=f"[여기를 클릭하세요]({RIOT_LOGIN_URL})",
            inline=False,
        )
        embed.set_footer(text="⚠️ 비밀번호는 Riot 공식 페이지에서만 입력됩니다.")

        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(name="인증", description="로그인 후 복사한 URL을 입력합니다.")
    async def verify(self, interaction: discord.Interaction, url: str):
        await interaction.response.defer(ephemeral=True)

        existing = await get_user(str(interaction.user.id))
        if existing:
            await interaction.followup.send(
                "✅ 이미 로그인되어 있어요. `/로그아웃` 후 다시 시도해주세요.",
                ephemeral=True,
            )
            return

        try:
            if "#" not in url:
                await interaction.followup.send(
                    "❌ 올바른 URL이 아니에요. 로그인 후 리다이렉트된 주소창의 URL 전체를 복사해주세요.",
                    ephemeral=True,
                )
                return

            fragment = urlsplit(url).fragment
            params = dict(parse_qsl(fragment))
            access_token = params.get("access_token")
            id_token = params.get("id_token")

            if not access_token:
                await interaction.followup.send(
                    "❌ URL에서 토큰을 찾을 수 없어요. 다시 시도해주세요.",
                    ephemeral=True,
                )
                return

            payload = access_token.split(".")[1]
            decoded = json.loads(urlsafe_b64decode(f"{payload}==="))
            puuid = decoded.get("sub")

            ssl_ctx = _ssl.create_default_context(cafile=certifi.where())
            async with aiohttp.ClientSession(connector=aiohttp.TCPConnector(ssl=ssl_ctx)) as session:
                async with session.post(
                    "https://entitlements.auth.riotgames.com/api/token/v1",
                    headers={
                        "Authorization": f"Bearer {access_token}",
                        "Content-Type": "application/json",
                    },
                    json={},
                ) as resp:
                    ent_data = await resp.json()
                    entitlements_token = ent_data["entitlements_token"]

                region = "kr"
                shard = "kr"
                try:
                    async with session.put(
                        "https://riot-geo.pas.si.riotgames.com/pas/v1/product/valorant",
                        headers={
                            "Authorization": f"Bearer {access_token}",
                            "Content-Type": "application/json",
                        },
                        json={"id_token": id_token or ""},
                    ) as resp:
                        if resp.status == 200:
                            geo_data = await resp.json()
                            region = geo_data.get("affinities", {}).get("live", "kr")
                            shard = REGION_SHARD_MAP.get(region, "kr")
                except Exception:
                    pass

            await save_user(
                discord_id=str(interaction.user.id),
                puuid=puuid,
                region=region,
                shard=shard,
                access_token=access_token,
                entitlements_token=entitlements_token,
                cookies="{}",
            )

            await interaction.followup.send(
                "✅ 로그인 성공! `/상점`으로 오늘의 상점을 확인해보세요.",
                ephemeral=True,
            )

        except Exception as e:
            await interaction.followup.send(
                f"❌ 인증 중 오류가 발생했어요: {str(e)}",
                ephemeral=True,
            )

    @app_commands.command(name="상점", description="오늘의 발로란트 스킨 상점을 확인합니다.")
    async def store(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=False)

        user = await get_user(str(interaction.user.id))
        if not user:
            await interaction.followup.send(
                "❌ 로그인이 필요해요. `/로그인`으로 먼저 계정을 연동해주세요.",
            )
            return

        try:
            storefront = await get_storefront(
                user["access_token"],
                user["entitlements_token"],
                user["puuid"],
                user["shard"],
            )

            daily, remaining = parse_daily_store(storefront)

            hours = remaining // 3600
            minutes = (remaining % 3600) // 60

            embeds = []

            header_embed = discord.Embed(
                title="🛒 오늘의 상점",
                description=f"갱신까지 **{hours}시간 {minutes}분** 남았어요.",
                color=discord.Color.red(),
            )
            embeds.append(header_embed)

            for item in daily:
                skin = await get_skin_info(item["offer_id"])
                cost_str = f"{item['cost']:,} VP"
                skin_embed = discord.Embed(
                    title=f"{skin['name']}",
                    description=f"💰 {cost_str} | 등급: {skin['tier_name']}",
                    color=skin.get("color", 0x808080),
                )
                if skin["icon"]:
                    skin_embed.set_thumbnail(url=skin["icon"])
                embeds.append(skin_embed)

            await interaction.followup.send(embeds=embeds)

        except Exception as e:
            await interaction.followup.send(
                f"❌ 상점 조회 중 오류가 발생했어요: {str(e)}",
            )

    @app_commands.command(name="나이트마켓", description="나이트 마켓을 확인합니다.")
    async def nightmarket(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=False)

        user = await get_user(str(interaction.user.id))
        if not user:
            await interaction.followup.send(
                "❌ 로그인이 필요해요. `/로그인`으로 먼저 계정을 연동해주세요.",
            )
            return

        try:
            storefront = await get_storefront(
                user["access_token"],
                user["entitlements_token"],
                user["puuid"],
                user["shard"],
            )

            night = parse_night_market(storefront)
            if not night:
                await interaction.followup.send(
                    "🌙 현재 나이트 마켓이 열려있지 않아요.",
                )
                return

            embed = discord.Embed(
                title="🌙 나이트 마켓",
                color=discord.Color.dark_purple(),
            )

            for item in night:
                skin = await get_skin_info(item["offer_id"])
                embed.add_field(
                    name=f"{skin['name']}",
                    value=(
                        f"~~{item['cost']:,} VP~~ → **{item['discount_cost']:,} VP**\n"
                        f"🏷️ {item['discount_percent']}% 할인 | 등급: {skin['tier_name']}"
                    ),
                    inline=False,
                )

            await interaction.followup.send(embed=embed)

        except Exception as e:
            await interaction.followup.send(
                f"❌ 나이트 마켓 조회 중 오류가 발생했어요: {str(e)}",
            )

    @app_commands.command(name="로그아웃", description="발로란트 계정 연동을 해제합니다.")
    async def logout(self, interaction: discord.Interaction):
        user = await get_user(str(interaction.user.id))
        if not user:
            await interaction.response.send_message(
                "❌ 로그인되어 있지 않아요.",
                ephemeral=True,
            )
            return

        await delete_user(str(interaction.user.id))
        await interaction.response.send_message(
            "✅ 로그아웃되었어요. 저장된 인증 정보가 모두 삭제되었어요.",
            ephemeral=True,
        )


async def setup(bot):
    await bot.add_cog(Valorant(bot))