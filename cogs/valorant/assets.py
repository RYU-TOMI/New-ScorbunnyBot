import aiohttp

SKINS_URL = "https://valorant-api.com/v1/weapons/skins"
TIERS_URL = "https://valorant-api.com/v1/contenttiers"

# 캐시 (봇 실행 중 한 번만 로드)
_skins_cache: dict = {}
_tiers_cache: dict = {}


async def load_skins():
    """스킨 데이터 로드 및 캐시"""
    global _skins_cache

    if _skins_cache:
        return

    async with aiohttp.ClientSession() as session:
        async with session.get(SKINS_URL, params={"language": "ko-KR"}) as resp:
            data = await resp.json()

            for skin in data.get("data", []):
                for level in skin.get("levels", []):
                    _skins_cache[level["uuid"].lower()] = {
                        "name": skin.get("displayName", "알 수 없는 스킨"),
                        "icon": level.get("displayIcon"),
                        "tier_id": skin.get("contentTierUuid"),
                    }


async def load_tiers():
    """등급(티어) 데이터 로드 및 캐시"""
    global _tiers_cache

    if _tiers_cache:
        return

    async with aiohttp.ClientSession() as session:
        async with session.get(TIERS_URL) as resp:
            data = await resp.json()

            for tier in data.get("data", []):
                _tiers_cache[tier["uuid"].lower()] = {
                    "name": tier.get("devName", "Unknown"),
                    "icon": tier.get("displayIcon"),
                    "color": tier.get("highlightColor"),
                }


# 티어별 색상 (임베드용 hex)
TIER_COLORS = {
    "Select": 0x5A9FE2,
    "Deluxe": 0x009B82,
    "Premium": 0xD1548D,
    "Ultra": 0xF5E05B,
    "Exclusive": 0xF5955B,
}


async def get_skin_info(offer_id: str) -> dict:
    """스킨 UUID로 이름, 이미지, 등급 정보 반환"""
    await load_skins()
    await load_tiers()

    skin = _skins_cache.get(offer_id.lower(), {})
    tier_id = skin.get("tier_id")
    tier = _tiers_cache.get(tier_id.lower()) if tier_id else None

    tier_name = tier["name"] if tier else "Unknown"

    return {
        "name": skin.get("name", "알 수 없는 스킨"),
        "icon": skin.get("icon"),
        "tier_name": tier_name,
        "tier_icon": tier["icon"] if tier else None,
        "color": TIER_COLORS.get(tier_name, 0x808080),
    }