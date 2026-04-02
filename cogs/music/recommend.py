import asyncio
import os
import re
import random
import aiohttp
import yt_dlp
from dotenv import load_dotenv

load_dotenv()

LASTFM_API_KEY = os.getenv("LASTFM_API_KEY")

YTDL_OPTS = {
    'quiet': True,
    'no_warnings': True,
    'skip_download': True,
}

YTDL_SEARCH_OPTS = {
    'quiet': True,
    'no_warnings': True,
    'skip_download': True,
    'extract_flat': True,
}

# 추천 후보 풀 (guild_id별 관리)
recommendation_pool: dict[int, list[dict]] = {}

def clean_artist_name(artist: str) -> str:
    artist = re.sub(r'\s*\([^)]*\)', '', artist).strip()
    artist = re.sub(r'[^\w\s가-힣]', '', artist).strip()
    return artist

def extract_artist_from_title(title: str) -> str:
    clean = re.sub(r'\[.*?\]', '', title).strip()
    patterns = [
        r'^(.+?)\s*[-–]\s*.+',
        r'^(.+?)\s*[_]\s*.+',
        r"^(.+?)\s*['\"].*?['\"]",
        r'^(.+?)\s*의\s*.+',
        r'^(.+?)\s*\(.*?\)\s*의\s*.+',
        r'^(.+?)\s*\(.*?\)\s*[-–]?\s*.+',
    ]
    for pattern in patterns:
        match = re.match(pattern, clean)
        if match:
            artist = match.group(1).strip()
            artist = re.sub(r'\(.*?\)|\[.*?\]', '', artist).strip()
            if artist and len(artist) < 30:
                return artist
    return ''

def _search_sync(query: str) -> list[dict]:
    try:
        with yt_dlp.YoutubeDL(YTDL_SEARCH_OPTS) as ydl:
            result = ydl.extract_info(f"ytsearch5:{query}", download=False)
            entries = result.get('entries', [])

        official = []   # track/artist 있는 공식 영상
        fallback = []   # 그 외

        for e in entries:
            if not e:
                continue
            duration = e.get('duration') or 0
            if duration < 60 or duration > 600:
                continue
            vid_id = e.get('id', '')
            title = e.get('title', 'Unknown')
            if any(kw in title.lower() for kw in ["playlist", "플레이리스트", "모음", "full album", "mix", "플리"]):
                continue
            categories = e.get('categories') or []
            if categories and 'Music' not in categories:
                continue
            if not vid_id:
                continue

            item = {'id': vid_id, 'title': title}
            # track/artist 있으면 공식 영상으로 분류
            if e.get('track') and e.get('artist'):
                official.append(item)
            else:
                fallback.append(item)

        # 공식 영상 우선, 없으면 fallback
        return official if official else fallback

    except Exception as e:
        print(f"검색 오류: {e}")
        return []

async def get_track_info(video_id: str) -> dict:
    loop = asyncio.get_event_loop()
    url = f"https://www.youtube.com/watch?v={video_id}"
    try:
        def extract():
            with yt_dlp.YoutubeDL(YTDL_OPTS) as ydl:
                return ydl.extract_info(url, download=False)
        info = await loop.run_in_executor(None, extract)
        return {
            'title': info.get('title', ''),
            'track': info.get('track') or '',
            'artist': info.get('artist') or '',
            'channel': info.get('channel') or '',
            'duration': info.get('duration') or 0,
        }
    except Exception as e:
        print(f"yt-dlp 정보 추출 오류: {e}")
        return {}

async def get_top_tracks_lastfm(artist: str, session: aiohttp.ClientSession, limit: int = 5) -> list[dict]:
    try:
        async with session.get(
            "https://ws.audioscrobbler.com/2.0/",
            params={
                "method": "artist.getTopTracks",
                "artist": artist,
                "api_key": LASTFM_API_KEY,
                "format": "json",
                "limit": limit,
                "autocorrect": 1,
            }
        ) as resp:
            data = await resp.json()
        tracks = data.get("toptracks", {}).get("track", [])
        return [{'artist': artist, 'track': t.get('name', '')} for t in tracks]
    except Exception as e:
        print(f"Last.fm top tracks 오류: {e}")
        return []

async def get_similar_tracks_lastfm(artist: str, track: str, session: aiohttp.ClientSession, limit: int = 10) -> list[dict]:
    try:
        async with session.get(
            "https://ws.audioscrobbler.com/2.0/",
            params={
                "method": "track.getSimilar",
                "artist": artist,
                "track": track,
                "api_key": LASTFM_API_KEY,
                "format": "json",
                "limit": limit,
                "autocorrect": 1,
            }
        ) as resp:
            data = await resp.json()
        similar = data.get("similartracks", {}).get("track", [])
        results = []
        for t in similar:
            sim_artist = t.get('artist', {}).get('name', '')
            sim_track = t.get('name', '')
            if sim_artist.lower() == artist.lower():
                continue
            results.append({'artist': sim_artist, 'track': sim_track})
        return results
    except Exception as e:
        print(f"Last.fm 오류: {e}")
        return []

async def get_similar_artists_lastfm(artist: str, session: aiohttp.ClientSession, limit: int = 3) -> list[str]:
    try:
        async with session.get(
            "https://ws.audioscrobbler.com/2.0/",
            params={
                "method": "artist.getSimilar",
                "artist": artist,
                "api_key": LASTFM_API_KEY,
                "format": "json",
                "limit": limit,
                "autocorrect": 1,
            }
        ) as resp:
            data = await resp.json()
        similar = data.get("similarartists", {}).get("artist", [])
        return [a.get('name', '') for a in similar if a.get('name')]
    except Exception as e:
        print(f"Last.fm artist 오류: {e}")
        return []

async def build_pool(artist: str, track: str, excluded: set) -> list[dict]:
    """Last.fm + yt-dlp로 추천 후보 풀 생성"""
    async with aiohttp.ClientSession() as session:
        # track 없으면 top track으로 보완
        if artist and not track:
            top_tracks = await get_top_tracks_lastfm(artist, session, limit=5)
            if top_tracks:
                chosen = random.choice(top_tracks)
                track = chosen['track']
                print(f"top track 선택: {track}")

        # Last.fm 유사 곡 가져오기
        similar_tracks = []
        if artist and track:
            similar_tracks = await get_similar_tracks_lastfm(artist, track, session, limit=10)

        if not similar_tracks:
            print("track.getSimilar 없음 → artist.getSimilar fallback")
            similar_artists = await get_similar_artists_lastfm(artist, session, limit=3)
            top_track_tasks = [get_top_tracks_lastfm(a, session, limit=2) for a in similar_artists]
            top_track_results = await asyncio.gather(*top_track_tasks)
            for tracks in top_track_results:
                similar_tracks.extend(tracks)

        if not similar_tracks:
            return []

        # 아티스트별 1개씩
        seen_artists = set()
        diverse_tracks = []
        for t in similar_tracks:
            if t['artist'] not in seen_artists:
                diverse_tracks.append(t)
                seen_artists.add(t['artist'])

        print(f"유사 곡 목록: {[(t['artist'], t['track']) for t in diverse_tracks]}")

        # YouTube 병렬 검색
        queries = [f"{t['artist']} {t['track']}" for t in diverse_tracks[:6]]
        loop = asyncio.get_event_loop()
        search_results = await asyncio.gather(
            *[loop.run_in_executor(None, lambda q=q: _search_sync(q)) for q in queries]
        )

        pool = []
        seen_ids = set(excluded)
    
        for results in search_results:
            for item in results:
                vid_id = item.get('id')
                vid_title = item.get('title', '')

                if not vid_id or vid_id in seen_ids:
                    continue

                pool.append(item)
                seen_ids.add(vid_id)
                break  # 쿼리당 1개만
                
        random.shuffle(pool)
        print(f"풀 생성 완료: {len(pool)}개")
        return pool

async def get_recommendations(video_id: str, limit: int = 1, played_ids: list = None, guild_id: int = 0) -> list[dict]:
    if played_ids is None:
        played_ids = []

    excluded = set(played_ids + [video_id])

    try:
        # 풀이 비어있으면 현재 곡 기반으로 새로 생성
        pool = recommendation_pool.get(guild_id, [])
        pool = [item for item in pool if item['id'] not in excluded]

        if not pool:
            print(f"풀이 비어있음 → 현재 곡 기반으로 풀 생성")
            info = await get_track_info(video_id)
            track = info.get('track', '')
            artist = info.get('artist', '')
            title = info.get('title', '')
            channel = info.get('channel', '')

            print(f"현재 곡 - title: {title}, track: {track}, artist: {artist}")

            if not artist:
                artist = extract_artist_from_title(title)
            if not artist:
                broadcast_channels = ['mnet', 'kbs', 'mbc', 'sbs', 'its live', 'itslive',
                                      'studio choom', 'inkigayo', 'mcountdown', 'melon', 'naver']
                if not any(bc in channel.lower() for bc in broadcast_channels):
                    artist = re.sub(r'\s*(official|music|channel|vevo)\s*', '', channel, flags=re.IGNORECASE).strip()
                    artist = clean_artist_name(artist)

            artist = clean_artist_name(artist)
            print(f"아티스트: {artist}")

            if not artist:
                print("아티스트 추출 실패")
                return []

            pool = await build_pool(artist, track, excluded)
            recommendation_pool[guild_id] = pool

        if not pool:
            print("풀 생성 실패")
            return []

        # 풀에서 랜덤으로 1개 선택
        chosen = random.choice(pool)
        pool.remove(chosen)
        recommendation_pool[guild_id] = pool

        print(f"풀에서 선택: {chosen['title']} (남은 풀: {len(pool)}개)")

        # 선택된 곡의 아티스트 정보 확인
        vid_info = await get_track_info(chosen['id'])
        vid_artist = vid_info.get('artist', '')
        vid_track = vid_info.get('track', '')
        vid_title = vid_info.get('title', '')
        vid_channel = vid_info.get('channel', '')

        if not vid_artist:
            vid_artist = extract_artist_from_title(vid_title)
        if not vid_artist:
            broadcast_channels = ['mnet', 'kbs', 'mbc', 'sbs', 'its live', 'itslive',
                                  'studio choom', 'inkigayo', 'mcountdown', 'melon', 'naver']
            if not any(bc in vid_channel.lower() for bc in broadcast_channels):
                vid_artist = re.sub(r'\s*(official|music|channel|vevo)\s*', '', vid_channel, flags=re.IGNORECASE).strip()
                vid_artist = clean_artist_name(vid_artist)

        vid_artist = clean_artist_name(vid_artist)
        print(f"선택된 곡 아티스트: {vid_artist}")

        # 아티스트 정보 있으면 → 다음 풀 미리 생성 (백그라운드)
        if vid_artist and len(pool) < 3:
            print(f"풀 보충 시작 (백그라운드): {vid_artist}")
            asyncio.create_task(
                _replenish_pool(guild_id, vid_artist, vid_track, excluded | {chosen['id']})
            )

        return [{'url': f"https://www.youtube.com/watch?v={chosen['id']}", 'title': chosen['title']}]

    except Exception as e:
        print(f"추천 오류: {e}")
        return []

async def _replenish_pool(guild_id: int, artist: str, track: str, excluded: set):
    """백그라운드에서 풀 보충"""
    try:
        new_items = await build_pool(artist, track, excluded)
        existing = recommendation_pool.get(guild_id, [])
        existing_ids = {item['id'] for item in existing}
        for item in new_items:
            if item['id'] not in existing_ids:
                existing.append(item)
        recommendation_pool[guild_id] = existing
        print(f"풀 보충 완료: {len(existing)}개")
    except Exception as e:
        print(f"풀 보충 오류: {e}")

def clear_pool(guild_id: int):
    """풀 초기화 (나가 명령어 등에서 호출)"""
    if guild_id in recommendation_pool:
        del recommendation_pool[guild_id]