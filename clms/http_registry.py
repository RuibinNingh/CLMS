"""唯一 HTTP 注册表和传输返回类型；领域模块不依赖服务器。"""
ROUTES = {}


class Raw:
    def __init__(self, body: bytes, content_type: str, headers=None):
        self.body, self.content_type, self.headers = body, content_type, headers or {}


class Stream:
    def __init__(self, chunks):
        self.chunks = chunks


class AfterResponse:
    """先完整发送 JSON，再执行回调（用于重启等服务生命周期操作）。"""
    def __init__(self, data, callback):
        self.data, self.callback = data, callback


def route(method, path, *, server=False):
    def register(fn):
        key = (method, path)
        if key in ROUTES:
            raise RuntimeError('重复 HTTP 路由：' + method + ' ' + path)
        fn.needs_server = server
        ROUTES[key] = fn
        return fn
    return register


def register_routes(routes):
    for (method, path), handler in routes.items():
        route(method, path)(handler)
