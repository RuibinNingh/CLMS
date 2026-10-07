"""当前 Web 实例的状态和重启；只有 CLI 启动的服务能重启自身。"""
import http.server
import os
import threading
import uuid

from .http_registry import AfterResponse


class RestartConflict(ValueError):
    code = "restart_conflict"


class ServiceServer(http.server.ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, address, handler, vault, restart_enabled=False):
        super().__init__(address, handler)
        self.vault = os.path.abspath(vault)
        self.instance_id = uuid.uuid4().hex
        self.restart_enabled = restart_enabled
        self.restart_requested = False
        self._restart_started = False
        self._restart_lock = threading.Lock()

    def status(self):
        return {"host": self.server_address[0], "port": self.server_address[1],
                "pid": os.getpid(), "instance_id": self.instance_id,
                "restart_supported": self.restart_enabled, "restarting": self.restart_requested}

    def request_restart(self, instance_id):
        if not self.restart_enabled:
            raise ValueError("当前服务由嵌入式调用启动，请使用命令行 serve 启动后重启")
        if instance_id != self.instance_id:
            raise RestartConflict("服务实例已变化，请刷新页面后再操作")
        with self._restart_lock:
            self.restart_requested = True
        return AfterResponse({"restarting": True, "instance_id": self.instance_id}, self._begin_restart)

    def _begin_restart(self):
        with self._restart_lock:
            if self._restart_started:
                return
            self._restart_started = True
        # shutdown 必须在 serve_forever 所在线程之外执行；CLI 主线程负责清理和 exec。
        threading.Thread(target=self.shutdown, name="clms-restart", daemon=True).start()
