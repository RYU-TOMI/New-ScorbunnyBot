from collections import deque

class MusicQueue:
    def __init__(self):
        self._queue = deque()
        self.max_size = 10
        self.loop = False
        self.loop_current = False
        self.current = None

    def add(self, url: str, title: str, requester: str = None) -> bool:
        """큐에 곡 추가. 성공 여부 반환"""
        if len(self._queue) >= self.max_size:
            return False
        self._queue.append((url, title, requester))
        return True

    def next(self) -> tuple | None:
        """다음 곡 반환. 없으면 None"""
        if self.loop_current and self.current:
            return self.current
        if self.loop and self.current:
            self._queue.append(self.current)
        if self._queue:
            self.current = self._queue.popleft()
            return self.current
        self.current = None
        return None

    def skip(self):
        """현재 곡 스킵"""
        if self._queue:
            self.current = self._queue.popleft()
            return self.current
        self.current = None
        return None

    def remove(self, index: int) -> tuple | None:
        """특정 인덱스 곡 삭제 (1-based)"""
        if not 1 <= index <= len(self._queue):
            return None
        queue_list = list(self._queue)
        removed = queue_list.pop(index - 1)
        self._queue = deque(queue_list)
        return removed

    def clear(self):
        """큐 초기화"""
        self._queue.clear()
        self.current = None
        self.loop = False
        self.loop_current = False

    def items(self) -> list:
        """큐 목록 반환"""
        return list(self._queue)

    def __len__(self):
        return len(self._queue)

    def is_empty(self) -> bool:
        return len(self._queue) == 0


class QueueManager:
    """Guild별 큐 관리"""
    def __init__(self):
        self._queues: dict[int, MusicQueue] = {}

    def get(self, guild_id: int) -> MusicQueue:
        if guild_id not in self._queues:
            self._queues[guild_id] = MusicQueue()
        return self._queues[guild_id]

    def remove(self, guild_id: int):
        if guild_id in self._queues:
            del self._queues[guild_id]