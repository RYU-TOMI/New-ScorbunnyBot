import asyncio
import yt_dlp as youtube_dl

YTDL_FORMAT_OPTIONS = {
    'format': 'bestaudio/best',
    'restrictfilenames': True,
    'noplaylist': True,
    'nocheckcertificate': True,
    'ignoreerrors': False,
    'logtostderr': False,
    'quiet': True,
    'no_warnings': True,
    'default_search': 'auto',
    'source_address': '0.0.0.0',
}

FFMPEG_OPTIONS = {
    'before_options': '-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5 -nostdin',
    'options': '-vn -ar 48000 -ac 2 -b:a 192k -filter:a "volume=0.15"',
}

YTDL_SEARCH_OPTIONS = {
    'format': 'bestaudio/best',
    'quiet': True,
    'no_warnings': True,
    'default_search': 'ytsearch5',
    'extract_flat': True,
    'skip_download': True,
}

ytdl = youtube_dl.YoutubeDL(YTDL_FORMAT_OPTIONS)

import discord

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
        return cls(discord.FFmpegPCMAudio(data['url'], **FFMPEG_OPTIONS), data=data)

    @classmethod
    async def search(cls, query: str, *, loop=None) -> list[dict] | None:
        """유튜브 검색 결과 반환 (최대 5개)"""
        loop = loop or asyncio.get_event_loop()
        try:
            with youtube_dl.YoutubeDL(YTDL_SEARCH_OPTIONS) as ytdl_search:
                result = await loop.run_in_executor(
                    None, lambda: ytdl_search.extract_info(f"ytsearch5:{query}", download=False)
                )
            if 'entries' not in result:
                return None
            return [
                {
                    'url': f"https://www.youtube.com/watch?v={entry['id']}",
                    'title': entry.get('title', 'N/A'),
                    'duration': (
                        f"{int(entry.get('duration', 0)) // 60}:{int(entry.get('duration', 0)) % 60:02d}"
                        if entry.get('duration') else "N/A"
                    )
                }
                for entry in result['entries']
            ]
        except Exception as e:
            print(f"검색 오류: {e}")
            return None