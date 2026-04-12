import aiosqlite
import os
from cryptography.fernet import Fernet

DB_PATH = os.path.join(os.path.dirname(__file__), "bot.db")

_fernet: Fernet | None = None

def get_fernet() -> Fernet:
    global _fernet
    if _fernet is not None:
        return _fernet
    key = os.getenv("ENCRYPTION_KEY")
    if not key:
        key = Fernet.generate_key().decode()
        print(f"⚠️ ENCRYPTION_KEY가 없어요. .env에 아래 키를 추가해주세요:\nENCRYPTION_KEY={key}")
    _fernet = Fernet(key.encode() if isinstance(key, str) else key)
    return _fernet


def encrypt(text: str) -> str:
    return get_fernet().encrypt(text.encode()).decode()


def decrypt(text: str) -> str:
    return get_fernet().decrypt(text.encode()).decode()


async def init_db():
    async with aiosqlite.connect(DB_PATH) as db:
        await db.executescript("""
            CREATE TABLE IF NOT EXISTS users (
                discord_id TEXT PRIMARY KEY,
                puuid TEXT,
                region TEXT,
                shard TEXT,
                access_token TEXT,
                entitlements_token TEXT,
                cookies TEXT,
                expires_at DATETIME,
                updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS login_sessions (
                token TEXT PRIMARY KEY,
                discord_id TEXT,
                expires_at DATETIME
            );
            CREATE TABLE IF NOT EXISTS play_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                guild_id TEXT NOT NULL,
                video_id TEXT NOT NULL,
                title TEXT NOT NULL,
                url TEXT NOT NULL,
                play_count INTEGER DEFAULT 1,
                last_played_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(guild_id, video_id)
            );
            CREATE TABLE IF NOT EXISTS recap_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                guild_id TEXT NOT NULL,
                video_id TEXT NOT NULL,
                title TEXT NOT NULL,
                url TEXT NOT NULL,
                played_at DATETIME DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS guild_settings (
                guild_id TEXT PRIMARY KEY,
                recap_channel_id TEXT
            );
        """)
        try:
            await db.execute("ALTER TABLE users ADD COLUMN expires_at DATETIME")
        except Exception:
            pass
        await db.commit()


# ── 음악 히스토리 ──────────────────────────────────────────

async def add_play_history(guild_id: str, video_id: str, title: str, url: str):
    """재생 기록 추가 - 중복이면 횟수 증가"""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            INSERT INTO play_history (guild_id, video_id, title, url)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(guild_id, video_id) DO UPDATE SET
                play_count = play_count + 1,
                title = excluded.title,
                url = excluded.url,
                last_played_at = CURRENT_TIMESTAMP
        """, (guild_id, video_id, title, url))
        await db.commit()


async def get_random_from_history(guild_id: str, limit: int = 1, exclude_recent: int = 10) -> list[dict]:
    """재생 기록에서 랜덤으로 곡 가져오기 - 최근 N개 제외"""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("""
            SELECT video_id, title, url
            FROM play_history
            WHERE guild_id = ?
            AND video_id NOT IN (
                SELECT video_id FROM play_history
                WHERE guild_id = ?
                ORDER BY last_played_at DESC
                LIMIT ?
            )
            ORDER BY RANDOM()
            LIMIT ?
        """, (guild_id, guild_id, exclude_recent, limit)) as cursor:
            rows = await cursor.fetchall()
            return [{"video_id": row["video_id"], "title": row["title"], "url": row["url"]} for row in rows]


async def get_history(guild_id: str, limit: int = 10) -> list[dict]:
    """최근 재생 기록 가져오기"""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("""
            SELECT video_id, title, url, play_count, last_played_at
            FROM play_history
            WHERE guild_id = ?
            ORDER BY last_played_at DESC
            LIMIT ?
        """, (guild_id, limit)) as cursor:
            rows = await cursor.fetchall()
            return [dict(row) for row in rows]


async def get_history_count(guild_id: str) -> int:
    """서버의 재생 기록 곡 수 조회"""
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT COUNT(DISTINCT video_id) FROM play_history WHERE guild_id = ?",
            (guild_id,)
        ) as cursor:
            row = await cursor.fetchone()
            return row[0] if row else 0


# ── 발로란트 유저 ──────────────────────────────────────────

async def save_user(discord_id: str, puuid: str, region: str, shard: str,
                    access_token: str, entitlements_token: str, cookies: str,
                    expires_at: str = None):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            INSERT OR REPLACE INTO users
            (discord_id, puuid, region, shard, access_token, entitlements_token, cookies, expires_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
        """, (discord_id, puuid, region, shard,
              encrypt(access_token), encrypt(entitlements_token), encrypt(cookies), expires_at))
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
            try:
                return {
                    "discord_id": row["discord_id"],
                    "puuid": row["puuid"],
                    "region": row["region"],
                    "shard": row["shard"],
                    "access_token": decrypt(row["access_token"]),
                    "entitlements_token": decrypt(row["entitlements_token"]),
                    "cookies": decrypt(row["cookies"]),
                    "expires_at": row["expires_at"],
                    "updated_at": row["updated_at"]
                }
            except Exception:
                # 복호화 실패 시 (키 불일치) 데이터 삭제 후 None 반환
                await delete_user(discord_id)
                return None


async def delete_user(discord_id: str):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("DELETE FROM users WHERE discord_id = ?", (discord_id,))
        await db.commit()


# ── 로그인 세션 ──────────────────────────────────────────

async def save_login_session(token: str, discord_id: str, expires_at: str):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            INSERT OR REPLACE INTO login_sessions (token, discord_id, expires_at)
            VALUES (?, ?, ?)
        """, (token, discord_id, expires_at))
        await db.commit()


async def get_login_session(token: str) -> dict | None:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM login_sessions WHERE token = ?", (token,)
        ) as cursor:
            row = await cursor.fetchone()
            if not row:
                return None
            return dict(row)


async def delete_login_session(token: str):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("DELETE FROM login_sessions WHERE token = ?", (token,))
        await db.commit()

# ── RECAP ──────────────────────────────────────────

async def add_recap_history(guild_id: str, video_id: str, title: str, url: str):
    """RECAP용 재생 기록 추가 (매 재생마다 기록)"""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            INSERT INTO recap_history (guild_id, video_id, title, url)
            VALUES (?, ?, ?, ?)
        """, (guild_id, video_id, title, url))
        await db.commit()


async def get_recap_stats(guild_id: str, start_date: str, end_date: str) -> dict:
    """분기별 통계 조회"""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row

        # 총 재생 횟수
        async with db.execute("""
            SELECT COUNT(*) as total FROM recap_history
            WHERE guild_id = ? AND played_at BETWEEN ? AND ?
        """, (guild_id, start_date, end_date)) as cursor:
            total = (await cursor.fetchone())["total"]

        # 총 곡 수 (중복 제외)
        async with db.execute("""
            SELECT COUNT(DISTINCT video_id) as unique_count FROM recap_history
            WHERE guild_id = ? AND played_at BETWEEN ? AND ?
        """, (guild_id, start_date, end_date)) as cursor:
            unique_count = (await cursor.fetchone())["unique_count"]

        # TOP 5 곡
        async with db.execute("""
            SELECT video_id, title, url, COUNT(*) as play_count
            FROM recap_history
            WHERE guild_id = ? AND played_at BETWEEN ? AND ?
            GROUP BY video_id
            ORDER BY play_count DESC
            LIMIT 5
        """, (guild_id, start_date, end_date)) as cursor:
            top_tracks = [dict(row) for row in await cursor.fetchall()]

        # TOP 30 곡 (플레이리스트용)
        async with db.execute("""
            SELECT video_id, title, url, COUNT(*) as play_count
            FROM recap_history
            WHERE guild_id = ? AND played_at BETWEEN ? AND ?
            GROUP BY video_id
            ORDER BY play_count DESC
            LIMIT 30
        """, (guild_id, start_date, end_date)) as cursor:
            top_playlist = [dict(row) for row in await cursor.fetchall()]

        return {
            "total": total,
            "unique_count": unique_count,
            "top_tracks": top_tracks,
            "top_playlist": top_playlist,
        }


async def get_recap_history_count(guild_id: str) -> int:
    """서버의 recap 기록 수 조회"""
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT COUNT(DISTINCT video_id) FROM recap_history WHERE guild_id = ?",
            (guild_id,)
        ) as cursor:
            row = await cursor.fetchone()
            return row[0] if row else 0


# ── 서버 설정 ──────────────────────────────────────────

async def set_guild_setting(guild_id: str, recap_channel_id: str):
    """서버 설정 저장"""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            INSERT OR REPLACE INTO guild_settings (guild_id, recap_channel_id)
            VALUES (?, ?)
        """, (guild_id, recap_channel_id))
        await db.commit()


async def get_guild_setting(guild_id: str) -> dict | None:
    """서버 설정 조회"""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM guild_settings WHERE guild_id = ?", (guild_id,)
        ) as cursor:
            row = await cursor.fetchone()
            return dict(row) if row else None
        

# ── 메이플스토리 ────────────────────────────────────────

async def init_sunday_channels():
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS sunday_channels (
                guild_id INTEGER PRIMARY KEY,
                channel_id INTEGER NOT NULL,
                role_id INTEGER
            )
        """)
        # 기존 테이블에 role_id 컬럼 없으면 추가 (migration)
        try:
            await db.execute("ALTER TABLE sunday_channels ADD COLUMN role_id INTEGER")
        except Exception:
            pass  # 이미 있으면 무시
        await db.commit()

async def set_sunday_channel(guild_id: int, channel_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            INSERT INTO sunday_channels (guild_id, channel_id)
            VALUES (?, ?)
            ON CONFLICT(guild_id) DO UPDATE SET channel_id = excluded.channel_id
        """, (guild_id, channel_id))
        await db.commit()

async def get_all_sunday_channels() -> list[tuple[int, int]]:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT guild_id, channel_id FROM sunday_channels") as cursor:
            return await cursor.fetchall()

async def delete_sunday_channel(guild_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("DELETE FROM sunday_channels WHERE guild_id = ?", (guild_id,))
        await db.commit()

async def get_last_sunday_url() -> str | None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS sunday_state (
                key TEXT PRIMARY KEY,
                value TEXT
            )
        """)
        async with db.execute(
            "SELECT value FROM sunday_state WHERE key = 'last_url'"
        ) as cursor:
            row = await cursor.fetchone()
            return row[0] if row else None

async def set_last_sunday_url(url: str):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS sunday_state (
                key TEXT PRIMARY KEY,
                value TEXT
            )
        """)
        await db.execute("""
            INSERT INTO sunday_state (key, value) VALUES ('last_url', ?)
            ON CONFLICT(key) DO UPDATE SET value = excluded.value
        """, (url,))
        await db.commit()

async def set_sunday_role(guild_id: int, role_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            UPDATE sunday_channels SET role_id = ? WHERE guild_id = ?
        """, (role_id, guild_id))
        await db.commit()

async def get_sunday_role(guild_id: int) -> int | None:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT role_id FROM sunday_channels WHERE guild_id = ?", (guild_id,)
        ) as cursor:
            row = await cursor.fetchone()
            return row[0] if row and row[0] else None