import aiohttp
import json
import certifi
import ssl as _ssl
from base64 import urlsafe_b64decode
from urllib.parse import parse_qsl, urlsplit

STORE_URL = "https://pd.{shard}.a.pvp.net/store/v3/storefront/{puuid}"
CLIENT_PLATFORM = "ew0KCSJwbGF0Zm9ybVR5cGUiOiAiUEMiLA0KCSJwbGF0Zm9ybU9TIjogIldpbmRvd3MiLA0KCSJwbGF0Zm9ybU9TVmVyc2lvbiI6ICIxMC4wLjE5MDQyLjEuMjU2LjY0Yml0IiwNCgkicGxhdGZvcm1DaGlwc2V0IjogIlVua25vd24iDQp9"
REGION_SHARD_MAP = {
    "ap": "ap", "kr": "kr", "eu": "eu", "na": "na",
    "br": "na", "latam": "na", "pbe": "na",
}

# SSL 컨텍스트 재사용 (매번 생성하지 않도록)
_SSL_CTX = _ssl.create_default_context(cafile=certifi.where())


def _get_connector() -> aiohttp.TCPConnector:
    return aiohttp.TCPConnector(ssl=_SSL_CTX)


def _extract_tokens_from_uri(uri: str) -> dict:
    """리다이렉트 URI에서 토큰 추출"""
    fragment = urlsplit(uri).fragment
    data = dict(parse_qsl(fragment))
    access_token = data.get("access_token")

    payload = access_token.split(".")[1]
    decoded = json.loads(urlsafe_b64decode(f"{payload}==="))

    return {
        "access_token": access_token,
        "id_token": data.get("id_token"),
        "token_type": data.get("token_type", "Bearer"),
        "user_id": decoded.get("sub"),
    }


async def get_client_version() -> str:
    """현재 발로란트 클라이언트 버전"""
    async with aiohttp.ClientSession(connector=_get_connector()) as session:
        async with session.get("https://valorant-api.com/v1/version") as resp:
            data = await resp.json()
            return data["data"]["riotClientVersion"]


async def get_storefront(access_token: str, entitlements_token: str,
                         puuid: str, shard: str) -> dict:
    """데일리 상점 + 나이트 마켓 조회 (v3 POST)"""
    client_version = await get_client_version()
    headers = {
        "Authorization": f"Bearer {access_token}",
        "X-Riot-Entitlements-JWT": entitlements_token,
        "X-Riot-ClientPlatform": CLIENT_PLATFORM,
        "X-Riot-ClientVersion": client_version,
        "Content-Type": "application/json",
    }
    url = STORE_URL.format(shard=shard, puuid=puuid)

    async with aiohttp.ClientSession(connector=_get_connector()) as session:
        async with session.post(url, headers=headers, json={}) as resp:
            if resp.status != 200:
                raise Exception(f"상점 조회 실패 (HTTP {resp.status})")
            return await resp.json(content_type=None)


def parse_daily_store(storefront: dict) -> tuple[list[dict], int]:
    """데일리 상점 파싱"""
    panel = storefront.get("SkinsPanelLayout", {})
    skin_uuids = panel.get("SingleItemOffers", [])
    offer_details = panel.get("SingleItemStoreOffers", [])
    remaining = panel.get("SingleItemOffersRemainingDurationInSeconds", 0)

    price_map = {
        offer["OfferID"]: list(offer["Cost"].values())[0]
        for offer in offer_details
        if offer.get("Cost")
    }

    return [
        {"offer_id": uuid, "cost": price_map.get(uuid, 0)}
        for uuid in skin_uuids
    ], remaining


def parse_night_market(storefront: dict) -> list[dict] | None:
    """나이트 마켓 파싱"""
    bonus = storefront.get("BonusStore")
    if not bonus:
        return None

    return [
        {
            "offer_id": item["Offer"]["OfferID"],
            "cost": list(item["Offer"]["Cost"].values())[0] if item["Offer"].get("Cost") else 0,
            "discount_cost": list(item["DiscountCosts"].values())[0] if item.get("DiscountCosts") else 0,
            "discount_percent": item.get("DiscountPercent", 0),
        }
        for item in bonus.get("BonusStoreOffers", [])
    ]