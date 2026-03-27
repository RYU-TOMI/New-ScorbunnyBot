import asyncio
import json
import re
import ssl
from base64 import urlsafe_b64decode
from datetime import datetime, timedelta
from typing import Any
from urllib.parse import parse_qsl, urlsplit

import aiohttp
import certifi

# 상점 엔드포인트
STORE_URL = "https://pd.{shard}.a.pvp.net/store/v3/storefront/{puuid}"

CLIENT_PLATFORM = "ew0KCSJwbGF0Zm9ybVR5cGUiOiAiUEMiLA0KCSJwbGF0Zm9ybU9TIjogIldpbmRvd3MiLA0KCSJwbGF0Zm9ybU9TVmVyc2lvbiI6ICIxMC4wLjE5MDQyLjEuMjU2LjY0Yml0IiwNCgkicGxhdGZvcm1DaGlwc2V0IjogIlVua25vd24iDQp9"

REGION_SHARD_MAP = {
    "ap": "ap", "kr": "ap", "eu": "eu",
    "na": "na", "br": "na", "latam": "na", "pbe": "na",
}

# Cloudflare 우회용 cipher suites
FORCED_CIPHERS = [
    'ECDHE-ECDSA-AES256-GCM-SHA384',
    'ECDHE-ECDSA-AES128-GCM-SHA256',
    'ECDHE-ECDSA-CHACHA20-POLY1305',
    'ECDHE-RSA-AES128-GCM-SHA256',
    'ECDHE-RSA-CHACHA20-POLY1305',
    'ECDHE-RSA-AES128-SHA256',
    'ECDHE-RSA-AES128-SHA',
    'ECDHE-RSA-AES256-SHA',
    'ECDHE-ECDSA-AES128-SHA256',
    'ECDHE-ECDSA-AES128-SHA',
    'ECDHE-ECDSA-AES256-SHA',
    'ECDHE+AES128',
    'ECDHE+AES256',
    'ECDHE+3DES',
    'RSA+AES128',
    'RSA+AES256',
    'RSA+3DES',
]

RIOT_USER_AGENT = 'RiotClient/60.0.6.4770705.4749685 rso-auth (Windows;10;;Professional, x64)'

def _create_ssl_ctx() -> ssl.SSLContext:
    """TLS 1.3 + cipher suites 강제 설정"""
    ctx = ssl.create_default_context(ssl.Purpose.SERVER_AUTH)
    ctx.minimum_version = ssl.TLSVersion.TLSv1_3
    ctx.set_ciphers(':'.join(FORCED_CIPHERS))
    return ctx

def _create_session() -> aiohttp.ClientSession:
    return aiohttp.ClientSession(
        cookie_jar=aiohttp.CookieJar(),
        connector=aiohttp.TCPConnector(ssl=_create_ssl_ctx()),
        timeout=aiohttp.ClientTimeout(total=15)
    )

def _extract_tokens_from_uri(uri: str) -> tuple[str, str]:
    """리다이렉트 URI에서 access_token, id_token 추출"""
    try:
        access_token = uri.split('access_token=')[1].split('&scope')[0]
        id_token = uri.split('id_token=')[1].split('&')[0]
        return access_token, id_token
    except IndexError:
        raise Exception("토큰 추출 실패: 올바르지 않은 URI")

def _parse_cookies(response) -> dict:
    """응답에서 cookies 파싱"""
    cookies = {}
    for cookie in response.cookies.items():
        cookies[cookie[0]] = str(cookie).split('=')[1].split(';')[0]
    return cookies

def _decode_puuid(access_token: str) -> str:
    payload = access_token.split(".")[1]
    decoded = json.loads(urlsafe_b64decode(f"{payload}==="))
    return decoded.get("sub")

async def authenticate(username: str, password: str) -> dict:
    """아이디/비밀번호로 로그인. cookies + tokens 반환"""
    headers = {
        'Content-Type': 'application/json',
        'User-Agent': RIOT_USER_AGENT,
        'Accept': 'application/json, text/plain, */*',
    }

    session = _create_session()

    try:
        # 1단계: 쿠키 초기화
        await session.post(
            'https://auth.riotgames.com/api/v1/authorization',
            json={
                'client_id': 'play-valorant-web-prod',
                'nonce': '1',
                'redirect_uri': 'https://playvalorant.com/opt_in',
                'response_type': 'token id_token',
                'scope': 'account openid',
            },
            headers=headers
        )

        # 2단계: 로그인
        async with session.put(
            'https://auth.riotgames.com/api/v1/authorization',
            json={
                'type': 'auth',
                'username': username,
                'password': password,
                'remember': True,
            },
            headers=headers
        ) as r:
            data = await r.json()
            cookies = _parse_cookies(r)

        if data['type'] == 'multifactor':
            return {'type': 'multifactor', 'cookies': cookies, 'email': data['multifactor'].get('email', '')}

        if data['type'] != 'response':
            raise Exception("아이디 또는 비밀번호가 올바르지 않아요.")

        uri = data['response']['parameters']['uri']
        access_token, id_token = _extract_tokens_from_uri(uri)

        return {'type': 'response', 'access_token': access_token, 'id_token': id_token, 'cookies': cookies}

    finally:
        await session.close()

async def authenticate_2fa(code: str, cookies: dict) -> dict:
    """2FA 코드 인증"""
    headers = {
        'Content-Type': 'application/json',
        'User-Agent': RIOT_USER_AGENT,
    }

    session = _create_session()
    try:
        async with session.put(
            'https://auth.riotgames.com/api/v1/authorization',
            json={'type': 'multifactor', 'code': code, 'rememberDevice': True},
            headers=headers,
            cookies=cookies,
        ) as r:
            data = await r.json()
            new_cookies = _parse_cookies(r)

        if data['type'] != 'response':
            raise Exception("2FA 코드가 올바르지 않아요.")

        uri = data['response']['parameters']['uri']
        access_token, id_token = _extract_tokens_from_uri(uri)

        return {'access_token': access_token, 'id_token': id_token, 'cookies': new_cookies}
    finally:
        await session.close()

async def refresh_token(cookies: dict) -> dict:
    """저장된 cookies로 토큰 자동 갱신"""
    if isinstance(cookies, str):
        cookies = json.loads(cookies)

    session = _create_session()
    try:
        async with session.get(
            'https://auth.riotgames.com/authorize'
            '?redirect_uri=https%3A%2F%2Fplayvalorant.com%2Fopt_in'
            '&client_id=play-valorant-web-prod'
            '&response_type=token%20id_token'
            '&scope=account%20openid'
            '&nonce=1',
            cookies=cookies,
            allow_redirects=False,
        ) as r:
            if r.status != 303:
                raise Exception("cookies 만료")
            location = r.headers.get('Location', '')
            if location.startswith('/login'):
                raise Exception("cookies 만료")
            new_cookies = _parse_cookies(r)
            # 기존 cookies 업데이트
            merged_cookies = {**cookies, **new_cookies}

        access_token, id_token = _extract_tokens_from_uri(location)
        entitlements_token = await get_entitlements_token(access_token)

        return {
            'access_token': access_token,
            'id_token': id_token,
            'entitlements_token': entitlements_token,
            'cookies': merged_cookies,
        }
    finally:
        await session.close()

async def get_entitlements_token(access_token: str) -> str:
    """entitlements 토큰 발급"""
    session = _create_session()
    try:
        async with session.post(
            'https://entitlements.auth.riotgames.com/api/token/v1',
            headers={'Authorization': f'Bearer {access_token}', 'Content-Type': 'application/json'},
            json={}
        ) as r:
            data = await r.json()
            return data['entitlements_token']
    finally:
        await session.close()

async def get_region(access_token: str, id_token: str) -> tuple[str, str]:
    """유저 지역 + shard 반환"""
    session = _create_session()
    try:
        async with session.put(
            'https://riot-geo.pas.si.riotgames.com/pas/v1/product/valorant',
            headers={'Authorization': f'Bearer {access_token}', 'Content-Type': 'application/json'},
            json={'id_token': id_token}
        ) as r:
            if r.status == 200:
                data = await r.json()
                region = data.get('affinities', {}).get('live', 'kr')
                shard = REGION_SHARD_MAP.get(region, 'ap')
                return region, shard
    except Exception:
        pass
    finally:
        await session.close()
    return 'kr', 'ap'

async def get_client_version() -> str:
    ssl_ctx = ssl.create_default_context(cafile=certifi.where())
    async with aiohttp.ClientSession(connector=aiohttp.TCPConnector(ssl=ssl_ctx)) as session:
        async with session.get("https://valorant-api.com/v1/version") as resp:
            data = await resp.json()
            return data["data"]["riotClientVersion"]

async def get_storefront(access_token: str, entitlements_token: str, puuid: str, shard: str) -> dict:
    """데일리 상점 + 나이트 마켓 조회"""
    ssl_ctx = ssl.create_default_context(cafile=certifi.where())
    client_version = await get_client_version()
    headers = {
        "Authorization": f"Bearer {access_token}",
        "X-Riot-Entitlements-JWT": entitlements_token,
        "X-Riot-ClientPlatform": CLIENT_PLATFORM,
        "X-Riot-ClientVersion": client_version,
        "Content-Type": "application/json",
    }
    url = STORE_URL.format(shard=shard, puuid=puuid)
    async with aiohttp.ClientSession(connector=aiohttp.TCPConnector(ssl=ssl_ctx)) as session:
        async with session.post(url, headers=headers, json={}) as resp:
            if resp.status != 200:
                raise Exception(f"상점 조회 실패 (HTTP {resp.status})")
            return await resp.json(content_type=None)

def parse_daily_store(storefront: dict) -> tuple[list[dict], int]:
    panel = storefront.get("SkinsPanelLayout", {})
    skin_uuids = panel.get("SingleItemOffers", [])
    offer_details = panel.get("SingleItemStoreOffers", [])
    remaining = panel.get("SingleItemOffersRemainingDurationInSeconds", 0)
    result = []
    for skin_uuid in skin_uuids:
        cost = 0
        for offer in offer_details:
            if offer["OfferID"] == skin_uuid:
                cost = list(offer["Cost"].values())[0] if offer.get("Cost") else 0
                break
        result.append({"offer_id": skin_uuid, "cost": cost})
    return result, remaining

def parse_night_market(storefront: dict) -> list[dict] | None:
    bonus = storefront.get("BonusStore")
    if not bonus:
        return None
    result = []
    for item in bonus.get("BonusStoreOffers", []):
        offer = item["Offer"]
        result.append({
            "offer_id": offer["OfferID"],
            "cost": list(offer["Cost"].values())[0] if offer.get("Cost") else 0,
            "discount_cost": list(item["DiscountCosts"].values())[0] if item.get("DiscountCosts") else 0,
            "discount_percent": item.get("DiscountPercent", 0),
        })
    return result