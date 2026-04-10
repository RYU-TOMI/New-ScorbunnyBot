import discord

def now_playing_embed(player, requester: discord.User, autoplay: bool = False) -> discord.Embed:
    """현재 재생 중 embed"""
    embed = discord.Embed(
        title=player.title,
        url=player.url,
        color=discord.Color.green() if autoplay else discord.Color.red()
    )
    author_text = "▶️ 지금 재생중 | 🔄 자동재생 중" if autoplay else "▶️ 지금 재생중"
    embed.set_author(name=author_text)
    embed.add_field(name="🎧 요청자", value=str(requester), inline=True)
    embed.add_field(
        name="🕐 길이",
        value=f"{int(player.duration) // 60}:{int(player.duration) % 60:02d}",
        inline=True
    )
    embed.set_image(url=f"https://img.youtube.com/vi/{player.id}/0.jpg")
    return embed

def queue_embed(queue_items: list, max_size: int, title: str = None) -> discord.Embed:
    """대기열 embed"""
    embed = discord.Embed(
        title=title,
        description=f"대기열에 있는 곡 : {len(queue_items)}/{max_size}곡",
        color=discord.Color.red()
    )
    embed.set_author(name="📃 대기열")
    for i, (_, song_title, *_rest) in enumerate(queue_items, 1):
        embed.add_field(name=f"{i}.", value=song_title, inline=False)
    return embed

def search_embed(query: str, results: list) -> discord.Embed:
    """검색 결과 embed"""
    embed = discord.Embed(
        title="🔍 검색 결과",
        description=f"'{query}'(으)로 검색한 결과예요.\n원하는 곡의 번호를 눌러주세요.",
        color=discord.Color.red()
    )
    for i, result in enumerate(results, 1):
        embed.add_field(
            name=f"{i}.",
            value=f"{result['title']}\n길이: {result['duration']}",
            inline=False
        )
    embed.set_footer(text="30초 이내에 선택하지 않으면 검색이 취소됩니다.")
    return embed

def error_embed(message: str) -> discord.Embed:
    """에러 embed"""
    embed = discord.Embed(
        description=f"❌ {message}",
        color=discord.Color.red()
    )
    return embed