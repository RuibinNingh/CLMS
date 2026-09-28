"""草稿的实时事件通道（内存里，不落盘）：Agent 执行时逐字推送思考 / 正文 / 工具参数，前端经 SSE 订阅。

- publish(draft_id, event)：追加一条事件（自动编号 seq），唤醒等待者。
- append(draft_id, block_id, field, text)：给一个进行中的块追加文字（只存在内存里），同时推一条 delta 事件；
  块结束时由调用方把完整文字写进草稿文件，再 settle() 掉内存里的这份。
- overlay(draft_id, messages)：读草稿时把进行中块的实时文字盖上去，这样「刷新页面」也能接着看到流。
- wait(draft_id, since, timeout)：取 seq > since 的事件；缓冲区已经丢了要的那段时返回一条 reload。
每个草稿最多缓存 4000 条事件；服务重启后通道清空（草稿文件里的块仍在）。
"""

import collections
import threading

_channels = {}
_lock = threading.Lock()


class _Channel:
    def __init__(self):
        self.seq = 0
        self.events = collections.deque(maxlen=4000)
        self.cond = threading.Condition()
        self.text = {}


def _channel(draft_id) -> _Channel:
    with _lock:
        ch = _channels.get(draft_id)
        if ch is None:
            ch = _channels[draft_id] = _Channel()
        return ch


def publish(draft_id: str, event: dict) -> int:
    ch = _channel(draft_id)
    with ch.cond:
        ch.seq += 1
        ch.events.append(dict(event, seq=ch.seq))
        ch.cond.notify_all()
        return ch.seq


def append(draft_id: str, block_id: str, field: str, text: str):
    if not text or not block_id:
        return
    ch = _channel(draft_id)
    with ch.cond:
        slot = ch.text.setdefault(block_id, {})
        slot[field] = slot.get(field, "") + text
    publish(draft_id, {"type": "delta", "id": block_id, "field": field, "text": text})


def live_text(draft_id: str, block_id: str, field: str) -> str:
    ch = _channel(draft_id)
    with ch.cond:
        return ch.text.get(block_id, {}).get(field, "")


def settle(draft_id: str, block_id: str):
    ch = _channel(draft_id)
    with ch.cond:
        ch.text.pop(block_id, None)


def overlay(draft_id: str, messages: list) -> list:
    ch = _channel(draft_id)
    with ch.cond:
        if not ch.text:
            return messages
        live = {k: dict(v) for k, v in ch.text.items()}
    return [dict(m, **live[m["id"]]) if m.get("id") in live else m for m in messages]


def current(draft_id: str) -> int:
    ch = _channel(draft_id)
    with ch.cond:
        return ch.seq


def wait(draft_id: str, since: int, timeout: float = 15.0) -> list:
    ch = _channel(draft_id)
    with ch.cond:
        if ch.seq <= since:
            ch.cond.wait(timeout)
        if ch.seq <= since:
            return []
        if ch.events and ch.events[0]["seq"] > since + 1:
            return [{"type": "reload", "seq": ch.seq}]
        return [e for e in ch.events if e["seq"] > since]
