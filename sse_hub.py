import json
import threading

_sse_listeners = []
_sse_lock = threading.Lock()


def sse_add_listener(q):
    with _sse_lock:
        _sse_listeners.append(q)


def sse_remove_listener(q):
    with _sse_lock:
        try:
            _sse_listeners.remove(q)
        except ValueError:
            pass


def sse_notify(data_dict):
    data = json.dumps(data_dict, ensure_ascii=False)
    with _sse_lock:
        dead = []
        for i, q in enumerate(_sse_listeners):
            try:
                q.put_nowait(data)
            except Exception:
                dead.append(i)
        for i in reversed(dead):
            _sse_listeners.pop(i)
