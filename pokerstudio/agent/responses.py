"""Official OpenAI Responses HTTP/SSE provider; API key stays in memory."""
from __future__ import annotations

import http.client
import json
import threading


class ResponsesProvider:
    def __init__(self):
        self.api_key = None
        self.model = None
        self.allow_paid = False
        self.connections = {}
        self.lock = threading.RLock()

    def configure(self, api_key, model, allow_paid=False):
        if not isinstance(api_key, str) or not api_key.strip():
            raise ValueError("API key 不能为空。")
        if not isinstance(model, str) or not model.strip():
            raise ValueError("请选择 API 模型。")
        self.api_key = api_key.strip()
        self.model = model.strip()
        self.allow_paid = allow_paid is True
        return self.status()

    def status(self):
        return {"provider": "api", "configured": bool(self.api_key), "model": self.model,
                "allow_paid": self.allow_paid, "billing": "OpenAI API 独立计费", "credential_storage": "backend_memory"}

    def models(self):
        if not self.api_key:
            raise RuntimeError("请先配置 OpenAI API key。")
        conn = http.client.HTTPSConnection("api.openai.com", timeout=30)
        try:
            conn.request("GET", "/v1/models", headers={"Authorization": "Bearer " + self.api_key})
            response = conn.getresponse()
            data = json.loads(response.read())
            if response.status >= 400:
                raise RuntimeError(f"OpenAI API HTTP {response.status}: " + str(data.get("error", {}).get("message", "请求失败")))
            return [{"id": item["id"], "model": item["id"], "verified": False} for item in data.get("data", [])]
        finally:
            conn.close()

    def stream(self, task_id, payload, cancelled):
        if not self.api_key or not self.allow_paid:
            raise RuntimeError("API 请求尚未获准：请配置 key，并明确启用 API 付费调用。")
        conn = http.client.HTTPSConnection("api.openai.com", timeout=30)
        with self.lock:
            self.connections[task_id] = {"connection": conn, "socket": None}
        try:
            if cancelled.is_set():
                return
            conn.request("POST", "/v1/responses", body=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
                         headers={"Authorization": "Bearer " + self.api_key,
                                  "Content-Type": "application/json", "Accept": "text/event-stream"})
            response = conn.getresponse()
            with self.lock:
                self.connections[task_id]["socket"] = conn.sock or getattr(getattr(response, "fp", None), "raw", None)
            if response.status >= 400:
                try:
                    error = json.loads(response.read()).get("error", {})
                    message = error.get("message", "请求失败")
                    code = error.get("code", "http_error")
                except Exception:
                    message, code = "请求失败", "http_error"
                raise RuntimeError(f"OpenAI API HTTP {response.status} / {code}: {message}")
            data_lines = []
            while not cancelled.is_set():
                line = response.readline()
                if not line:
                    break
                text = line.decode("utf-8").rstrip("\r\n")
                if text.startswith("data:"):
                    data_lines.append(text[5:].lstrip())
                elif not text and data_lines:
                    data = "\n".join(data_lines)
                    data_lines.clear()
                    if data == "[DONE]":
                        continue
                    yield json.loads(data)
        finally:
            with self.lock:
                self.connections.pop(task_id, None)
            conn.close()

    def cancel(self, task_id):
        with self.lock:
            active = self.connections.get(task_id)
        if active:
            connection = active["connection"]
            sock = connection.sock or active.get("socket")
            sock = getattr(sock, "_sock", sock)
            if sock:
                try:
                    sock.shutdown(2)
                except (OSError, AttributeError):
                    pass
            connection.close()
