import aiosqlite
import os
from cryptography.fernet import Fernet

DB_PATH = os.path.join(os.path.dirname(__file__), "bot.db")

# .env에 ENCRYPTION_KEY가 없으면 자동 생성 (최초 1회)
def get_fernet() -> Fernet:
    key = os.getenv("ENCRYPTION_KEY")
    if not key:
        key = Fernet.generate_key().decode()
        print(f"⚠️ ENCRYPTION_KEY가 없어요. .env에 아래 키를 추가해주세요:\nENCRYPTION_KEY={key}")
    return Fernet(key.encode() if isinstance(key, str) else key)

fernet = get_fernet()

def encrypt(text: str) -> str:
    return fernet.encrypt(text.encode()).decode()

def decrypt(text: str) -> str:
    return fernet.decrypt(text.encode()).decode()


async def init_db():
    """DB 초기화 - 테이블 생성"""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS users (
                discord_id TEXT PRIMARY KEY,
                puuid TEXT,
                region TEXT,
                shard TEXT,
                access_token TEXT,
                entitlements_token TEXT,
                cookies TEXT,
                updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS login_sessions (
                token TEXT PRIMARY KEY,
                discord_id TEXT,
                expires_at DATETIME
            )
        """)
        await db.commit()


async def save_user(discord_id: str, puuid: str, region: str, shard: str,
                    access_token: str, entitlements_token: str, cookies: str):
    """유저 인증 정보 저장 (암호화)"""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            INSERT OR REPLACE INTO users 
            (discord_id, puuid, region, shard, access_token, entitlements_token, cookies, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
        """, (
            discord_id, puuid, region, shard,
            encrypt(access_token),
            encrypt(entitlements_token),
            encrypt(cookies)
        ))
        await db.commit()


async def get_user(discord_id: str) -> dict | None:
    """유저 인증 정보 조회 (복호화)"""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM users WHERE discord_id = ?", (discord_id,)
        ) as cursor:
            row = await cursor.fetchone()
            if not row:
                return None
            return {
                "discord_id": row["discord_id"],
                "puuid": row["puuid"],
                "region": row["region"],
                "shard": row["shard"],
                "access_token": decrypt(row["access_token"]),
                "entitlements_token": decrypt(row["entitlements_token"]),
                "cookies": decrypt(row["cookies"]),
                "updated_at": row["updated_at"]
            }


async def delete_user(discord_id: str):
    """유저 인증 정보 삭제"""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("DELETE FROM users WHERE discord_id = ?", (discord_id,))
        await db.commit()


async def save_login_session(token: str, discord_id: str, expires_at: str):
    """로그인 세션 저장"""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            INSERT OR REPLACE INTO login_sessions (token, discord_id, expires_at)
            VALUES (?, ?, ?)
        """, (token, discord_id, expires_at))
        await db.commit()


async def get_login_session(token: str) -> dict | None:
    """로그인 세션 조회"""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM login_sessions WHERE token = ?", (token,)
        ) as cursor:
            row = await cursor.fetchone()
            if not row:
                return None
            return {
                "token": row["token"],
                "discord_id": row["discord_id"],
                "expires_at": row["expires_at"]
            }


async def delete_login_session(token: str):
    """로그인 세션 삭제"""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("DELETE FROM login_sessions WHERE token = ?", (token,))
        await db.commit()
