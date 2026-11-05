# -*- coding: utf-8 -*-
"""会话状态接收器（本地回环 HTTP）。

配合 DSH 的 client 插件 ``dsh-session-bridge-pet`` 使用：插件运行在 DSH 页面里，
把渲染层的会话快照（running / completionUnread / pendingInteraction.kind）POST 到
``http://127.0.0.1:<port>/event``；本模块只负责收、校验、转成 Qt 信号。

设计要点：
- 只监听 127.0.0.1，不对外网开放；
- 用 ``ThreadingHTTPServer``，处理函数在子线程，信号由 Qt 排队回主线程；
- POST 体按 JSON 解析（客户端用 text/plain 发，避免 CORS 预检）；
- 任何解析失败都当空快照处理，绝不抛出到服务器线程。
"""

from __future__ import annotations

import json
import logging
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from PySide6.QtCore import QObject, Signal

log = logging.getLogger(__name__)

DEFAULT_PORT = 8765
_MAX_BODY = 512 * 1024


def _salary_config() -> dict:
    """打工人小部件的参数（读独立 JSON；失败给空 dict，由插件侧退默认）。"""
    try:
        from .. import salary_widget

        return salary_widget.load_runtime_config()
    except Exception:
        return {}


class SessionApiReceiver(QObject):
    """本地 HTTP 接收器：收到一条会话快照就发一次 ``snapshot_received``。"""

    snapshot_received = Signal(object)

    def __init__(self, parent=None, port: int = DEFAULT_PORT):
        super().__init__(parent)
        self._port = int(port)
        self._server = None
        self._thread = None

    @property
    def port(self) -> int:
        return self._port

    @property
    def running(self) -> bool:
        return self._server is not None

    def start(self) -> bool:
        if self._server is not None:
            return True
        receiver = self

        class _Handler(BaseHTTPRequestHandler):
            server_version = "dsh-pet-session-api/1"

            def _cors(self) -> None:
                self.send_header("Access-Control-Allow-Origin", "*")
                self.send_header("Access-Control-Allow-Methods", "POST, GET, OPTIONS")
                self.send_header("Access-Control-Allow-Headers", "Content-Type")

            def do_OPTIONS(self):  # noqa: N802 - http.server 约定
                self.send_response(204)
                self._cors()
                self.end_headers()

            def do_GET(self):  # noqa: N802
                if self.path.startswith("/salary-config"):
                    # DSH 侧插件据此计算工资播报（配置单一来源 = 桌宠的 JSON）
                    body = json.dumps(_salary_config(), ensure_ascii=False).encode("utf-8")
                    self.send_response(200)
                    self._cors()
                    self.send_header("Content-Type", "application/json; charset=utf-8")
                    self.send_header("Content-Length", str(len(body)))
                    self.end_headers()
                    self.wfile.write(body)
                    return
                if self.path.startswith("/health"):
                    body = b'{"ok":true}'
                    self.send_response(200)
                    self._cors()
                    self.send_header("Content-Type", "application/json")
                    self.send_header("Content-Length", str(len(body)))
                    self.end_headers()
                    self.wfile.write(body)
                    return
                self.send_response(404)
                self.end_headers()

            def do_POST(self):  # noqa: N802
                if not self.path.startswith("/event"):
                    self.send_response(404)
                    self.end_headers()
                    return
                payload = {}
                try:
                    length = int(self.headers.get("Content-Length") or 0)
                    raw = self.rfile.read(min(length, _MAX_BODY)) if length > 0 else b""
                    if raw:
                        data = json.loads(raw.decode("utf-8", "replace"))
                        if isinstance(data, dict):
                            payload = data
                except Exception:
                    payload = {}
                self.send_response(204)
                self._cors()
                self.end_headers()
                try:
                    receiver.snapshot_received.emit(payload)
                except Exception:
                    pass

            def log_message(self, *_args):  # 静默：不要每个快照刷一行日志
                pass

        try:
            self._server = ThreadingHTTPServer(("127.0.0.1", self._port), _Handler)
            self._server.daemon_threads = True
        except OSError as exc:
            log.warning("会话接收器监听 127.0.0.1:%d 失败：%s", self._port, exc)
            self._server = None
            return False
        self._thread = threading.Thread(
            target=self._server.serve_forever,
            daemon=True,
            name="dsh-session-api",
        )
        self._thread.start()
        log.info("会话接收器已监听 http://127.0.0.1:%d/event", self._port)
        return True

    def stop(self) -> None:
        server = self._server
        self._server = None
        if server is not None:
            try:
                server.shutdown()
                server.server_close()
            except Exception:
                log.debug("关闭会话接收器失败", exc_info=True)
        self._thread = None
        log.info("会话接收器已停止")
