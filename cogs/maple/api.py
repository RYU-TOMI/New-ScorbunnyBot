import asyncio
import re
import aiohttp
import os
from datetime import datetime, timedelta, timezone
from bs4 import BeautifulSoup

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
    async with aiohttp.ClientSession() as session:
        ocid_data = await _get(session, "/id", {"character_name": character_name})
        ocid = ocid_data["ocid"]
        date = _yesterday()
        params = {"ocid": ocid, "date": date}

        basic, stat, equipment = await asyncio.gather(
            _get(session, "/character/basic", params),
            _get(session, "/character/stat", params),
            _get(session, "/character/item-equipment", params),
        )
        return {"basic": basic, "stat": stat, "equipment": equipment}

async def fetch_sunday_maple() -> dict | None:
    from playwright.async_api import async_playwright

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()
        await page.goto("https://maplestory.nexon.com/News/Event")
        await asyncio.sleep(3)

        # 썬데이 메이플 링크 + 날짜 추출
        entry = await page.evaluate("""
            () => {
                for (const a of document.querySelectorAll('a')) {
                    const text = a.textContent.trim();
                    if (text === '썬데이 메이플' || text.includes('스페셜 썬데이')) {
                        const parent = a.closest('li') || a.parentElement;
                        return { href: a.href, title: text, context: parent ? parent.innerText : '' };
                    }
                }
                return null;
            }
        """)

        if not entry:
            await browser.close()
            return None

        url = entry["href"].replace("/News/Event/", "/News/Event/Ongoing/")
        await page.goto(url)
        await asyncio.sleep(5)

        # 본문 이미지 중 lwi.nexon.com 것만 추출 (실제 혜택 이미지)
        imgs = await page.evaluate("""
            () => {
                const imgs = document.querySelectorAll('.new_board_con img, .view_content img, .event_view_roll img');
                return [...imgs]
                    .map(img => img.src)
                    .filter(src => src.includes('lwi.nexon.com'));
            }
        """)

        date_match = re.search(r'\d{4}\.\d{2}\.\d{2}.*?\d{4}\.\d{2}\.\d{2}', entry["context"])
        period = date_match.group(0) if date_match else ""

        await browser.close()

    return {
        "title": entry["title"],
        "url": url,
        "period": period,
        "images": imgs,
    }