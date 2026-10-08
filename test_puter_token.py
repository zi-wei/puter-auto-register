#!/usr/bin/env python3
# 用 Puter auth token 直连 api.puter.com 测 Claude
import json
import time
import urllib.request

TOKEN = "REDACTED_TOKEN"

BASE = "https://api.puter.com/drivers/call"
HDRS = {
    "Content-Type": "application/json",
    "User-Agent": "puter-js/1.0",
    "Origin": "http://localhost:18999",
    "Referer": "http://localhost:18999/",
    "Authorization": "Bearer " + TOKEN,
}


def call(iface, driver, method, args, timeout=120):
    body = json.dumps({"interface": iface, "driver": driver, "method": method, "args": args}).encode()
    req = urllib.request.Request(BASE, data=body, method="POST")
    for k, v in HDRS.items():
        req.add_header(k, v)
    t0 = time.time()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            d = json.loads(r.read().decode("utf-8", "ignore"))
        return True, d, time.time() - t0
    except urllib.error.HTTPError as e:
        try:
            b = json.loads(e.read().decode("utf-8", "ignore"))
        except Exception:
            b = {"raw": str(e)}
        return False, b, time.time() - t0
    except Exception as e:
        return False, {"err": str(e)[:200]}, time.time() - t0


print("=" * 80)
print("Puter Token 测试")
print("=" * 80)

# 1. 用户信息
print("\n### 1. 用户信息 (whoami)")
ok, d, dt = call("puter-driver-whoami", "whoami", "get", {})
print("  ok=%s  %.1fs" % (ok, dt))
print("  ", json.dumps(d, ensure_ascii=False)[:500])

# 2. 模型列表
print("\n### 2. 模型列表 (puter-chat-completion / models)")
ok, d, dt = call("puter-chat-completion", "ai-chat", "models", {})
print("  ok=%s  %.1fs" % (ok, dt))
if ok:
    res = d.get("result") or d
    if isinstance(res, list):
        cl = [m for m in res if "claude" in str(m.get("id", m)).lower()]
        print("  模型总数:", len(res), "| Claude:", len(cl))
        for m in cl[:25]:
            mid = m.get("id") if isinstance(m, dict) else m
            print("   ", mid)
    else:
        print("  ", json.dumps(res, ensure_ascii=False)[:600])
else:
    print("  ", json.dumps(d, ensure_ascii=False)[:400])

# 3. 实测 Claude
print("\n### 3. 实测 Claude 调用")
for model in ["claude-sonnet-5-5", "claude-opus-4-7", "claude-haiku-4-5", "claude-opus-5-5"]:
    ok, d, dt = call("puter-chat-completion", "ai-chat", "complete",
                     {"messages": [{"role": "user", "content": "只回OK两个字"}], "model": model},
                     timeout=150)
    if ok:
        r = d.get("result") or d
        txt = ""
        if isinstance(r, dict):
            msg = r.get("message") or {}
            c = msg.get("content")
            if isinstance(c, str):
                txt = c
            elif isinstance(c, list):
                txt = "".join(x.get("text", "") for x in c if isinstance(x, dict))
            else:
                txt = json.dumps(r, ensure_ascii=False)[:200]
        print("  [OK] %-22s %.1fs  -> %s" % (model, dt, str(txt)[:120].replace("\n", " ")))
        usage = (r or {}).get("usage") if isinstance(r, dict) else None
        if usage:
            print("         usage:", json.dumps(usage, ensure_ascii=False)[:200])
    else:
        print("  [X]  %-22s %.1fs  -> %s" % (model, dt, json.dumps(d, ensure_ascii=False)[:200]))

# 4. 查用量/额度
print("\n### 4. 用量 / 额度")
for iface, drv, m in [
    ("puter-subscription", "subscription", "get"),
    ("puter-usage", "usage", "get"),
    ("puter-auth", "auth", "get-user"),
]:
    ok, d, dt = call(iface, drv, m, {})
    print("  [%s] %s/%s -> %s" % ("OK" if ok else "X", iface, m, json.dumps(d, ensure_ascii=False)[:250]))
