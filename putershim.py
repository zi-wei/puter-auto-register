#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Puter -> OpenAI 兼容适配层
把 api.puter.com/drivers/call 包装成 /v1/chat/completions

环境变量:
  PUTER_TOKEN     Puter auth token（必需）
  PUTER_LISTEN    监听地址，默认 127.0.0.1:8893
  PUTER_ORIGIN    伪装 origin，默认 http://localhost:18999
"""
import json
import os
import sys
import time
import urllib.error
import urllib.request
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

TOKEN = os.environ.get("PUTER_TOKEN", "").strip()
LISTEN = os.environ.get("PUTER_LISTEN", "127.0.0.1:8893")
ORIGIN = os.environ.get("PUTER_ORIGIN", "http://localhost:18999")
API = "https://api.puter.com/drivers/call"

# 只暴露 Claude 系（可选：改成 True 暴露全部 974 个）
CLAUDE_ONLY = os.environ.get("PUTER_CLAUDE_ONLY", "1") not in ("0", "false", "False")

_models_cache = {"ts": 0, "data": []}


def log(msg):
    print("[%s] %s" % (time.strftime("%H:%M:%S"), msg), flush=True)


def puter_call(iface, driver, method, args, timeout=300):
    body = json.dumps({"interface": iface, "driver": driver, "method": method, "args": args}).encode()
    req = urllib.request.Request(API, data=body, method="POST")
    req.add_header("Content-Type", "application/json")
    req.add_header("User-Agent", "puter-js/1.0")
    req.add_header("Origin", ORIGIN)
    req.add_header("Referer", ORIGIN + "/")
    req.add_header("Authorization", "Bearer " + TOKEN)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode("utf-8", "ignore"))
    except urllib.error.HTTPError as e:
        try:
            return json.loads(e.read().decode("utf-8", "ignore"))
        except Exception:
            return {"error": {"message": "HTTP %d" % e.code, "code": "http_error"}}
    except Exception as e:
        return {"error": {"message": str(e)[:200], "code": "transport_error"}}


def list_models():
    now = time.time()
    if _models_cache["data"] and now - _models_cache["ts"] < 600:
        return _models_cache["data"]
    d = puter_call("puter-chat-completion", "ai-chat", "models", {}, timeout=60)
    res = d.get("result") or d.get("data") or []
    ids = []
    if isinstance(res, list):
        for m in res:
            mid = m.get("id") if isinstance(m, dict) else m
            if mid:
                ids.append(str(mid))
    if CLAUDE_ONLY:
        ids = [i for i in ids if "claude" in i.lower()]
    ids = sorted(set(ids))
    if ids:
        _models_cache["data"] = ids
        _models_cache["ts"] = now
    return ids


def extract_text(result):
    """从 Puter 返回里抽文本"""
    if not isinstance(result, dict):
        return str(result)[:4000]
    msg = result.get("message") or {}
    c = msg.get("content")
    if isinstance(c, str):
        return c
    if isinstance(c, list):
        parts = []
        for x in c:
            if isinstance(x, dict):
                parts.append(x.get("text") or "")
            else:
                parts.append(str(x))
        return "".join(parts)
    if c is not None:
        return json.dumps(c, ensure_ascii=False)
    return json.dumps(result, ensure_ascii=False)[:4000]


class H(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *a):
        pass

    def _send(self, obj, code=200):
        body = json.dumps(obj, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        p = self.path.split("?")[0].rstrip("/") or "/"
        if p in ("/health", "/"):
            return self._send({"ok": True, "token_set": bool(TOKEN), "claude_only": CLAUDE_ONLY})
        if p == "/v1/models":
            ids = list_models()
            now = int(time.time())
            return self._send({"object": "list", "data": [
                {"id": m, "object": "model", "created": now, "owned_by": "puter"} for m in ids]})
        return self._send({"error": {"message": "not found"}}, 404)

    def do_POST(self):
        p = self.path.split("?")[0].rstrip("/") or "/"
        n = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(n).decode("utf-8", "ignore") if n else "{}"
        try:
            body = json.loads(raw or "{}")
        except Exception:
            return self._send({"error": {"message": "bad json"}}, 400)

        if p not in ("/v1/chat/completions", "/chat/completions"):
            return self._send({"error": {"message": "not found"}}, 404)

        model = str(body.get("model") or "claude-sonnet-5-5")
        messages = body.get("messages") or []
        stream = bool(body.get("stream"))
        max_tokens = body.get("max_tokens")

        # 提取 system
        sys_msg = None
        msgs = []
        for m in messages:
            if m.get("role") == "system":
                sys_msg = m.get("content")
            else:
                msgs.append({"role": m.get("role", "user"), "content": m.get("content", "")})

        # 有些 Claude 变体要小写/带前缀，做一次容错
        args = {"messages": msgs, "model": model}
        if sys_msg:
            args["messages"] = [{"role": "system", "content": sys_msg}] + msgs
        if max_tokens:
            args["max_tokens"] = int(max_tokens)

        t0 = time.time()
        d = puter_call("puter-chat-completion", "ai-chat", "complete", args)
        dt = time.time() - t0

        if "error" in d:
            err = d["error"]
            msg = err.get("message") if isinstance(err, dict) else str(err)
            log("ERR %s: %s" % (model, str(msg)[:150]))
            return self._send({"error": {"message": str(msg), "type": "upstream_error"}}, 502)

        result = d.get("result") or d
        text = extract_text(result)
        usage = result.get("usage") if isinstance(result, dict) else {}
        cid = "chatcmpl-" + uuid.uuid4().hex[:24]

        log("OK  %-24s %.1fs  in=%s out=%s  %s" % (
            model, dt,
            (usage or {}).get("input_tokens", "?"), (usage or {}).get("output_tokens", "?"),
            text[:50].replace("\n", " ")))

        if not stream:
            return self._send({
                "id": cid, "object": "chat.completion", "created": int(time.time()), "model": model,
                "choices": [{"index": 0, "message": {"role": "assistant", "content": text},
                             "finish_reason": "stop"}],
                "usage": {
                    "prompt_tokens": (usage or {}).get("input_tokens", 0),
                    "completion_tokens": (usage or {}).get("output_tokens", 0),
                    "total_tokens": (usage or {}).get("input_tokens", 0) + (usage or {}).get("output_tokens", 0),
                },
            })

        # SSE 流式
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "keep-alive")
        self.end_headers()

        def chunk(delta, finish=None):
            obj = {"id": cid, "object": "chat.completion.chunk", "created": int(time.time()),
                   "model": model,
                   "choices": [{"index": 0, "delta": delta, "finish_reason": finish}]}
            self.wfile.write(("data: " + json.dumps(obj, ensure_ascii=False) + "\n\n").encode())
            self.wfile.flush()

        chunk({"role": "assistant", "content": ""})
        for i in range(0, len(text), 60):
            chunk({"content": text[i:i + 60]})
        chunk({}, "stop")
        self.wfile.write(b"data: [DONE]\n\n")
        self.wfile.flush()


if __name__ == "__main__":
    if not TOKEN:
        print("错误: 未设置 PUTER_TOKEN", file=sys.stderr)
        sys.exit(1)
    host, port = LISTEN.split(":")
    log("Puter 适配层启动 %s:%s  claude_only=%s  token=%s..." % (host, port, CLAUDE_ONLY, TOKEN[:20]))
    ThreadingHTTPServer((host, int(port)), H).serve_forever()
