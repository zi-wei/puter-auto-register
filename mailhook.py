#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
CF Email Routing 收信服务 + cloudflare_temp_email 契约适配
给 grok-register 的 email_provider=cloudflare 用

架构:
  xAI -> 邮件到 *@yourdomain.xyz
      -> Cloudflare Email Routing
      -> Email Worker (POST /mailhook)
      -> 本服务 (存内存+落盘)
      -> grok-register 通过 /api/mails 拉验证码

对外接口:
  POST /mailhook                      Worker 投递入口
  GET  /api/domains                   {"results":[{"domain":"yourdomain.xyz"}]}
  POST /api/new_address               {"address":"x@yourdomain.xyz","jwt":"<b64>"}
  GET  /api/mails?limit=N             {"messages":[...]}   (Bearer jwt)
  GET  /api/mail/<id>                 单封详情              (Bearer jwt)
  GET  /health
  GET  /inbox?addr=xxx                调试用：看某地址收信
"""
import base64
import email
import email.policy
import json
import os
import re
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

DOMAIN = os.environ.get("MAIL_DOMAIN", "yourdomain.xyz")
LISTEN = os.environ.get("MAIL_LISTEN", "127.0.0.1:8899")
STORE = os.environ.get("MAIL_STORE", "/var/lib/mailhook/inbox.jsonl")
HOOK_SECRET = os.environ.get("MAIL_HOOK_SECRET", "")

_lock = threading.Lock()
_msgs = []          # 全部邮件（内存）
_rr = {"idx": 0}


def log(m):
    print(f"[{time.strftime('%H:%M:%S')}] {m}", flush=True)


def b64e(s):
    return base64.urlsafe_b64encode(s.encode()).decode().rstrip("=")


def b64d(s):
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4)).decode()


def load_store():
    global _msgs
    try:
        with open(STORE, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        _msgs.append(json.loads(line))
                    except Exception:
                        pass
        log(f"已加载历史邮件 {len(_msgs)} 封")
    except FileNotFoundError:
        pass


def save_one(m):
    try:
        os.makedirs(os.path.dirname(STORE), exist_ok=True)
        with open(STORE, "a", encoding="utf-8") as f:
            f.write(json.dumps(m, ensure_ascii=False) + "\n")
    except Exception as e:
        log(f"落盘失败: {str(e)[:80]}")


CODE_RE = [
    r"验证码[：:\s]*([0-9]{4,8})",          # 中文：验证码9987
    r"校验码[：:\s]*([0-9]{4,8})",
    r"确认码[：:\s]*([0-9]{4,8})",
    r"\b([0-9]{3}-[0-9]{3})\b",            # xAI / NVIDIA 主格式 735-864
    r"confirmation\s+code[:\s]+([A-Z0-9]{3}-[A-Z0-9]{3})",
    r"verification\s+code[:\s]+([0-9]{4,8})",
    r"your\s+code[:\s]+([0-9]{4,8})",
]


def extract_code(text):
    for p in CODE_RE:
        m = re.search(p, text, re.IGNORECASE)
        if m:
            return m.group(1)
    return ""


def to_cf_msg(m):
    return {
        "id": m["id"],
        "msgid": m["id"],
        "address": m["to"],
        "to": [{"address": m["to"]}],
        "from": {"address": m.get("from", "")},
        "subject": m.get("subject", ""),
        "text": m.get("text", ""),
        "raw": m.get("text", ""),
        "content": m.get("text", ""),
        "snippet": (m.get("text", "") or "")[:200],
        "html": m.get("html", ""),
        "createdAt": m.get("ts", ""),
        "created_at": m.get("ts", ""),
    }


def parse_raw(raw):
    """解析原始 MIME，返回 (subject, text, html)"""
    try:
        msg = email.message_from_string(raw, policy=email.policy.default)
    except Exception:
        return "", raw, ""
    subj = str(msg.get("Subject") or "")
    text_parts, html_parts = [], []
    if msg.is_multipart():
        for part in msg.walk():
            ct = part.get_content_type()
            if part.get_content_maintype() == "multipart":
                continue
            try:
                payload = part.get_content()
            except Exception:
                continue
            if not isinstance(payload, str):
                continue
            if ct == "text/plain":
                text_parts.append(payload)
            elif ct == "text/html":
                html_parts.append(payload)
    else:
        try:
            payload = msg.get_content()
            if isinstance(payload, str):
                if msg.get_content_type() == "text/html":
                    html_parts.append(payload)
                else:
                    text_parts.append(payload)
        except Exception:
            pass
    if not text_parts and not html_parts:
        text_parts.append(raw)
    return subj, "\n".join(text_parts), "\n".join(html_parts)


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

    def _addr(self):
        auth = self.headers.get("Authorization", "")
        if not auth.startswith("Bearer "):
            return None
        t = auth[7:].strip()
        try:
            a = b64d(t)
            if "@" in a:
                return a
        except Exception:
            pass
        return t if "@" in t else None

    def do_GET(self):
        import urllib.parse
        u = urllib.parse.urlparse(self.path)
        p = u.path.rstrip("/") or "/"
        q = urllib.parse.parse_qs(u.query)

        if p in ("/health", "/api/health"):
            return self._send({"ok": True, "count": len(_msgs), "domain": DOMAIN})

        if p == "/api/domains":
            return self._send({"results": [{"domain": DOMAIN, "isVerified": True}]})

        if p == "/api/mails":
            addr = self._addr()
            if not addr:
                return self._send({"error": "unauthorized"}, 401)
            try:
                limit = int((q.get("limit") or ["20"])[0])
            except Exception:
                limit = 20
            with _lock:
                mine = [m for m in _msgs if m["to"].lower() == addr.lower()]
            mine = mine[-limit:]
            log(f"拉信 {addr} -> {len(mine)} 封")
            return self._send({"messages": [to_cf_msg(m) for m in mine]})

        m = re.match(r"^/api/mail/(.+)$", p)
        if m:
            mid = urllib.parse.unquote(m.group(1))
            with _lock:
                for x in _msgs:
                    if x["id"] == mid:
                        return self._send(to_cf_msg(x))
            return self._send({"error": "not found"}, 404)

        if p == "/inbox":
            a = (q.get("addr") or [""])[0]
            with _lock:
                mine = [m for m in _msgs if (not a or m["to"].lower() == a.lower())]
            return self._send({"count": len(mine), "messages": mine[-30:]})

        return self._send({"error": "not found"}, 404)

    def do_POST(self):
        import urllib.parse
        u = urllib.parse.urlparse(self.path)
        p = u.path.rstrip("/") or "/"
        n = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(n).decode("utf-8", "ignore") if n else "{}"
        try:
            body = json.loads(raw or "{}")
        except Exception:
            body = {}

        if p == "/mailhook":
            if HOOK_SECRET and self.headers.get("X-Hook-Secret", "") != HOOK_SECRET:
                return self._send({"error": "forbidden"}, 403)
            to = str(body.get("to") or "").strip().lower()
            raw = str(body.get("raw") or "")
            if raw:
                subj, text, html = parse_raw(raw)
            else:
                subj = str(body.get("subject") or "")
                text = str(body.get("text") or "")
                html = str(body.get("html") or "")
            blob = text + " " + re.sub(r"<[^>]+>", " ", html)
            code = extract_code(blob + " " + subj)
            rec = {
                "id": str(body.get("id") or f"m{int(time.time()*1000)}"),
                "to": to,
                "from": str(body.get("from") or ""),
                "subject": subj,
                "text": text or blob,
                "html": html,
                "code": code,
                "ts": str(body.get("ts") or time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())),
            }
            with _lock:
                _msgs.append(rec)
            save_one(rec)
            log(f"★ 收到邮件 to={to} code={code or '(未提取到)'} subj={subj[:50]}")
            return self._send({"ok": True, "code": code})

        if p in ("/api/new_address", "/api/accounts", "/api/address"):
            with _lock:
                _rr["idx"] += 1
                n2 = _rr["idx"]
            addr = f"gr{int(time.time())%1000000}{n2}@{DOMAIN}"
            log(f"分配地址 {addr}")
            return self._send({"address": addr, "jwt": b64e(addr)}, 201)

        if p == "/api/token":
            addr = str(body.get("address") or "")
            if addr:
                return self._send({"token": b64e(addr)}, 200)
            return self._send({"error": "bad request"}, 400)

        return self._send({"error": "not found"}, 404)


if __name__ == "__main__":
    host, port = LISTEN.split(":")
    load_store()
    log(f"收信服务启动 {host}:{port} domain={DOMAIN} store={STORE}")
    ThreadingHTTPServer((host, int(port)), H).serve_forever()
