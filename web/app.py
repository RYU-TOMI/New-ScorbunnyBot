import os
import sys
sys.path.append(os.path.join(os.path.dirname(__file__), ".."))

from dotenv import load_dotenv
load_dotenv()

from flask import Flask, request, jsonify
import asyncio
import json
from base64 import urlsafe_b64decode

from db.database import (
    get_login_session, delete_login_session, save_user
)

app = Flask(__name__)


def run_async(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


@app.route("/api/save-token", methods=["POST"])
def save_token():
    """북마클릿에서 전송된 토큰을 저장"""
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
        import aiohttp
        import certifi
        import ssl as _ssl

        payload = access_token.split(".")[1]
        decoded = json.loads(urlsafe_b64decode(f"{payload}==="))
        puuid = decoded.get("sub")

        ssl_ctx = _ssl.create_default_context(cafile=certifi.where())

        async def get_entitlements():
            async with aiohttp.ClientSession(connector=aiohttp.TCPConnector(ssl=ssl_ctx)) as s:
                async with s.post(
                    "https://entitlements.auth.riotgames.com/api/token/v1",
                    headers={
                        "Authorization": f"Bearer {access_token}",
                        "Content-Type": "application/json",
                    },
                    json={},
                ) as r:
                    return (await r.json())["entitlements_token"]

        entitlements_token = run_async(get_entitlements())

        async def get_region():
            async with aiohttp.ClientSession(connector=aiohttp.TCPConnector(ssl=ssl_ctx)) as s:
                async with s.put(
                    "https://riot-geo.pas.si.riotgames.com/pas/v1/product/valorant",
                    headers={
                        "Authorization": f"Bearer {access_token}",
                        "Content-Type": "application/json",
                    },
                    json={"id_token": id_token or ""},
                ) as r:
                    if r.status == 200:
                        geo_data = await r.json()
                        region = geo_data.get("affinities", {}).get("live", "kr")
                        shard_map = {
                            "ap": "ap", "kr": "kr", "eu": "eu", "na": "na",
                            "br": "na", "latam": "na", "pbe": "na",
                        }
                        return region, shard_map.get(region, "kr")
                    return "kr", "kr"

        region, shard = run_async(get_region())

        run_async(save_user(
            discord_id=session["discord_id"],
            puuid=puuid,
            region=region,
            shard=shard,
            access_token=access_token,
            entitlements_token=entitlements_token,
            cookies="{}",
        ))
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