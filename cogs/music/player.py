import asyncio
import sys
import discord
import yt_dlp as youtube_dl

YTDL_FORMAT_OPTIONS = {
    'format': 'bestaudio[ext=webm]/bestaudio/best',
    'restrictfilenames': True,
    'noplaylist': True,
    'nocheckcertificate': True,
    'ignoreerrors': False,
    'logtostderr': False,
    'quiet': True,
    'no_warnings': True,
    'default_search': 'auto',
    'source_address': '0.0.0.0',
    'cookiefile': 'cookies.txt',
}

# FFmpeg 기본 옵션. before_options에는 재생 직전 http_headers를 동적으로 덧붙인다.
FFMPEG_BEFORE_OPTIONS = '-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5 -nostdin'
FFMPEG_OPTIONS = {
    'before_options': FFMPEG_BEFORE_OPTIONS,
    'options': '-vn -ar 48000 -ac 2 -b:a 192k -filter:a "volume=0.15"',
}


def _build_ffmpeg_options(data: dict) -> dict:
    """yt-dlp가 추출한 http_headers(User-Agent 등)를 FFmpeg에 전달하는 옵션 생성.

    EC2 같은 데이터센터 IP에서는 yt-dlp와 동일한 헤더 없이 스트림 URL을 요청하면
    YouTube가 403을 돌려주고, FFmpeg 스트림이 0초 만에 끊겨 곡이 휙휙 넘어간다.
    추출 시점의 헤더를 그대로 붙여 이 문제를 방지한다.
    """
    before = FFMPEG_BEFORE_OPTIONS
    http_headers = data.get('http_headers') or {}
    header_lines = ''.join(f"{k}: {v}\r\n" for k, v in http_headers.items())
    if header_lines:
        before += f' -headers "{header_lines}"'
    return {
        'before_options': before,
        'options': '-vn -ar 48000 -ac 2 -b:a 192k -filter:a "volume=0.15"',
    }

YTDL_SEARCH_OPTIONS = {
    'format': 'bestaudio/best',
    'quiet': True,
    'no_warnings': True,
    'default_search': 'ytsearch5',
    'extract_flat': True,
    'skip_download': True,
    'cookiefile': 'cookies.txt',
}

ytdl = youtube_dl.YoutubeDL(YTDL_FORMAT_OPTIONS)


class YTDLSource(discord.PCMVolumeTransformer):
    def __init__(self, source, *, data, volume=0.5):
        super().__init__(source, volume)
        self.data = data
        self.id = data.get('id')
        self.title = data.get('title')
        self.url = data.get('webpage_url') or data.get('url')
        self.stream_url = data.get('url')
        self.duration = data.get('duration')

    @classmethod
    async def from_url(cls, url: str, *, loop=None) -> 'YTDLSource':
        loop = loop or asyncio.get_event_loop()
        data = await loop.run_in_executor(
            None, lambda: ytdl.extract_info(url, download=False)
        )
        if 'entries' in data:
            data = data['entries'][0]
        source = discord.FFmpegPCMAudio(
            data['url'],
            stderr=sys.stderr,  # FFmpeg 오류(403 등)를 봇 로그에 노출
            **_build_ffmpeg_options(data),
        )
        return cls(source, data=data)

    @classmethod
    async def search(cls, query: str, *, loop=None) -> list[dict] | None:
        """유튜브 검색 결과 반환 (최대 5개)"""
        loop = loop or asyncio.get_event_loop()
        try:
            with youtube_dl.YoutubeDL(YTDL_SEARCH_OPTIONS) as ytdl_search:
                result = await loop.run_in_executor(
                    None, lambda: ytdl_search.extract_info(f"ytsearch5:{query}", download=False)
                )
            entries = result.get('entries')
            if not entries:
                return None
            return [
                {
                    'url': f"https://www.youtube.com/watch?v={entry['id']}",
                    'title': entry.get('title', 'N/A'),
                    'duration': (
                        f"{int(entry['duration']) // 60}:{int(entry['duration']) % 60:02d}"
                        if entry.get('duration') else "N/A"
                    )
                }
                for entry in entries
            ]
        except Exception as e:
            print(f"검색 오류: {e}")
            return None