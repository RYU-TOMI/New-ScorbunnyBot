import os
import sys
import json
import asyncio
import aiohttp
import certifi
import ssl as _ssl
from base64 import urlsafe_b64decode
from flask import Flask, request, jsonify

sys.path.append(os.path.join(os.path.dirname(__file__), ".."))

from dotenv import load_dotenv
load_dotenv()

from db.database import get_login_session, delete_login_session, save_user
from cogs.valorant.api import REGION_SHARD_MAP

app = Flask(__name__)

_SSL_CTX = _ssl.create_default_context(cafile=certifi.where())


def run_async(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


async def _process_token(access_token: str, id_token: str, discord_id: str):
    """토큰 처리 - entitlements, region 조회 및 저장"""
    payload = access_token.split(".")[1]
    puuid = json.loads(urlsafe_b64decode(f"{payload}===")).get("sub")

    async with aiohttp.ClientSession(connector=aiohttp.TCPConnector(ssl=_SSL_CTX)) as session:
        # entitlements 토큰 조회
        async with session.post(
            "https://entitlements.auth.riotgames.com/api/token/v1",
            headers={"Authorization": f"Bearer {access_token}", "Content-Type": "application/json"},
            json={},
        ) as resp:
            entitlements_token = (await resp.json())["entitlements_token"]

        # region 조회
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

    await save_user(
        discord_id=discord_id,
        puuid=puuid, region=region, shard=shard,
        access_token=access_token,
        entitlements_token=entitlements_token,
        cookies="{}",
    )


@app.route("/api/save-token", methods=["POST"])
def save_token():
    data = request.get_json()
    access_token = data.get("access_token")
    id_token = data.get("id_token")
    session_token = data.get("session_token")

    if not access_token or not session_token:
        return jsonify({"error": "토큰이 없어요."}), 400

    session = run_async(get_login_session(session_token))
    if not session:
        return jsonify({"error": "세션이 만료되었어요. 디스코드에서 /로그인을 다시 해주세요."}), 400

    try:
        run_async(_process_token(access_token, id_token, session["discord_id"]))
        run_async(delete_login_session(session_token))
        return jsonify({"success": True})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/health")
def health():
    return jsonify({"status": "ok"})


if __name__ == "__main__":
    app.run(
        host=os.getenv("WEB_HOST", "0.0.0.0"),
        port=int(os.getenv("WEB_PORT", 80)),
        debug=False,
    )