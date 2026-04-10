import aiohttp
import os
from datetime import datetime, timedelta, timezone

BASE_URL = "https://open.api.nexon.com/maplestory/v1"

def _headers():
    return {"x-nxopen-api-key": os.getenv("NEXON_API_KEY")}

def _yesterday() -> str:
    kst = timezone(timedelta(hours=9))
    return (datetime.now(kst) - timedelta(days=1)).strftime("%Y-%m-%d")

async def _get(session: aiohttp.ClientSession, endpoint: str, params: dict) -> dict:
    async with session.get(f"{BASE_URL}{endpoint}", headers=_headers(), params=params) as res:
        if res.status == 400:
            raise ValueError("존재하지 않는 캐릭터입니다.")
        res.raise_for_status()
        return await res.json()

async def fetch_all(character_name: str) -> dict:
    """ocid 조회 후 기본정보/스탯/장비 병렬 요청"""
    async with aiohttp.ClientSession() as session:
        ocid_data = await _get(session, "/id", {"character_name": character_name})
        ocid = ocid_data["ocid"]
        date = _yesterday()
        params = {"ocid": ocid, "date": date}

        import asyncio
        basic, stat, equipment = await asyncio.gather(
            _get(session, "/character/basic", params),
            _get(session, "/character/stat", params),
            _get(session, "/character/item-equipment", params),
        )
        return {"basic": basic, "stat": stat, "equipment": equipment}