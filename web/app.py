import os
import sys
sys.path.append(os.path.join(os.path.dirname(__file__), ".."))

from dotenv import load_dotenv
load_dotenv()

from flask import Flask, render_template, request, redirect, jsonify
import asyncio
import json
from datetime import datetime, timedelta, timezone
from secrets import token_urlsafe

from db.database import (
    get_login_session, delete_login_session, save_user,
    save_login_session as db_save_login_session
)

app = Flask(__name__)
app.secret_key = os.getenv("WEB_SECRET_KEY", "dev-secret-key")

RIOT_AUTH_URL = (
    "https://auth.riotgames.com/authorize"
    "?redirect_uri=http%3A%2F%2Flocalhost%2Fredirect"
    "&client_id=riot-client"
    "&response_type=token%20id_token"
    "&nonce=1"
    "&scope=openid%20link%20ban%20lol_region%20account%20openid"
)


def run_async(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


@app.route("/login/<token>")
def login_page(token):
    """로그인 세션 확인 후 Riot 로그인 페이지로 리다이렉트"""
    session = run_async(get_login_session(token))

    if not session:
        return render_template("error.html", message="링크가 만료되었거나 유효하지 않아요.")

    expires = datetime.fromisoformat(session["expires_at"])
    if datetime.now(timezone.utc) > expires:
        run_async(delete_login_session(token))
        return render_template("error.html", message="링크가 만료되었어요. 디스코드에서 /로그인을 다시 해주세요.")

    # token을 state로 전달해서 콜백에서 식별
    auth_url = RIOT_AUTH_URL + f"&state={token}"
    return render_template("login.html", token=token, auth_url=auth_url)


@app.route("/callback")
def callback_page():
    """리다이렉트 후 fragment에서 토큰을 추출하는 페이지"""
    return render_template("callback.html")


@app.route("/api/save-token", methods=["POST"])
def save_token():
    """JavaScript에서 추출한 토큰을 저장"""
    data = request.get_json()

    access_token = data.get("access_token")
    id_token = data.get("id_token")
    state = data.get("state")  # login session token

    if not access_token or not state:
        return jsonify({"error": "토큰이 없어요."}), 400

    session = run_async(get_login_session(state))
    if not session:
        return jsonify({"error": "세션이 만료되었어요."}), 400

    try:
        import aiohttp
        import certifi
        import ssl
        from base64 import urlsafe_b64decode

        # JWT에서 puuid 추출
        payload = access_token.split(".")[1]
        decoded = json.loads(urlsafe_b64decode(f"{payload}==="))
        puuid = decoded.get("sub")

        # entitlements token 가져오기
        async def get_entitlements():
            ssl_ctx = ssl.create_default_context(cafile=certifi.where())
            async with aiohttp.ClientSession(connector=aiohttp.TCPConnector(ssl=ssl_ctx)) as s:
                async with s.post(
                    "https://entitlements.auth.riotgames.com/api/token/v1",
                    headers={
                        "Authorization": f"Bearer {access_token}",
                        "Content-Type": "application/json",
                    },
                    json={},
                ) as r:
                    ent_data = await r.json()
                    return ent_data["entitlements_token"]

        entitlements_token = run_async(get_entitlements())

        # region/shard 가져오기
        async def get_region():
            ssl_ctx = ssl.create_default_context(cafile=certifi.where())
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

        # DB에 저장
        run_async(save_user(
            discord_id=session["discord_id"],
            puuid=puuid,
            region=region,
            shard=shard,
            access_token=access_token,
            entitlements_token=entitlements_token,
            cookies="{}",  # 리다이렉트 방식에서는 쿠키 없음
        ))
        run_async(delete_login_session(state))

        return jsonify({"success": True})

    except Exception as e:
        return jsonify({"error": str(e)}), 500
    
@app.route("/redirect")
def riot_redirect():
    """Riot 리다이렉트 수신 - callback으로 전달"""
    return render_template("callback.html")


if __name__ == "__main__":
    app.run(
        host=os.getenv("WEB_HOST", "0.0.0.0"),
        port=int(os.getenv("WEB_PORT", 80)),
        debug=False,
    )