"""进程内固定窗口限流，用于登录、注册等敏感接口。"""
import threading
import time

_lock = threading.Lock()
_hits = {}


def _prune(now):
    for key in [k for k, (_, expires) in _hits.items() if expires <= now]:
        _hits.pop(key, None)


def hit(key, limit, window):
    """记录一次访问，返回 (是否放行, 建议重试秒数)。

    limit <= 0 表示不限流。
    """
    if limit <= 0:
        return True, 0
    now = time.monotonic()
    with _lock:
        _prune(now)
        count, expires = _hits.get(key, (0, now + window))
        if count >= limit:
            return False, max(1, int(expires - now))
        _hits[key] = (count + 1, expires)
        return True, 0


def reset(key=None):
    """清空计数，测试或人工解除封禁时使用。"""
    with _lock:
        if key is None:
            _hits.clear()
        else:
            _hits.pop(key, None)
