#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Puter 手机验证 —— SMSBower 接码
流程: 买号 → /send-confirm-phone → 轮询验证码 → /confirm-phone → 测 Claude
"""
import json
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

# ---------- 配置 ----------
SB_KEY = "YOUR_SMSBOWER_KEY"
SB_API = "https://smsbower.app/stubs/handler_api.php"

PUTER_API = "https://api.puter.com"

# 用哪个账号的 token（从命令行给）
TOKEN = sys.argv[1] if len(sys.argv) > 1 else ""

SERVICE = "ot"      # Any Other
COUNTRY = "12"      # United States (virtual)
FP = "7c93e5a50e0871e42cb2896cbb5bdd50"


def log(m):
    print("[%s] %s" % (time.strftime("%H:%M:%S"), m), flush=True)


def sb(action, **kw):
    q = {"api_key": SB_KEY, "action": action}
    q.update(kw)
    url = SB_API + "?" + urllib.parse.urlencode(q)
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    try:
        with urllib.request.urlopen(req, timeout=40) as r:
            return r.read().decode("utf-8", "ignore").strip()
    except Exception as e:
        return "ERR: %s" % str(e)[:150]


def puter(path, body, token, timeout=60):
    req = urllib.request.Request(PUTER_API + path, data=json.dumps(body).encode(), method="POST")
    req.add_header("Content-Type", "application/json")
    req.add_header("User-Agent", "puter-js/1.0")
    req.add_header("Origin", "https://puter.com")
    req.add_header("Referer", "https://puter.com/")
    req.add_header("Authorization", "Bearer " + token)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, r.read().decode("utf-8", "ignore")
    except urllib.error.HTTPError as e:
        try:
            return e.code, e.read().decode("utf-8", "ignore")
        except Exception:
            return e.code, ""
    except Exception as e:
        return 0, str(e)[:200]


print("=" * 70)
print("Puter 手机验证 —— SMSBower")
print("=" * 70)

# 1. 余额
log("[1] 查余额")
b = sb("getBalance")
log("    %s" % b)

# 2. 查价格
log("[2] 查 %s / %s 价格" % (COUNTRY, SERVICE))
p = sb("getPrices", service=SERVICE, country=COUNTRY)
log("    %s" % p[:300])

# 3. 买号
log("[3] 买号")
r = sb("getNumber", service=SERVICE, country=COUNTRY)
log("    %s" % r)

if not r.startswith("ACCESS_NUMBER"):
    log("    [X] 买号失败")
    # 试别的国家
    for c in ["7", "48", "1", "16", "31", "22"]:
        log("    试国家 %s..." % c)
        r = sb("getNumber", service=SERVICE, country=c)
        log("      %s" % r)
        if r.startswith("ACCESS_NUMBER"):
            break

if not r.startswith("ACCESS_NUMBER"):
    log("[X] 所有国家都买不到号")
    sys.exit(1)

parts = r.split(":")
act_id = parts[1]
phone = parts[2]
log("    [OK] 号码: +%s  (id=%s)" % (phone, act_id))

# 4. 调 Puter 发短信
if TOKEN:
    log("[4] 调 Puter /send-confirm-phone")
    st, body = puter("/send-confirm-phone",
                     {"phone": "+" + phone, "fingerprint": FP}, TOKEN)
    log("    HTTP %s" % st)
    log("    %s" % body[:300])

    if st != 200:
        log("    [X] 发短信失败，释放号码")
        sb("setStatus", id=act_id, status=8)
        sys.exit(1)

    # 5. 轮询验证码
    log("[5] 轮询验证码...")
    code = None
    t0 = time.time()
    while time.time() - t0 < 180:
        time.sleep(5)
        s = sb("getStatus", id=act_id)
        if s.startswith("STATUS_OK"):
            code = s.split(":")[1]
            log("    [OK] 验证码: %s" % code)
            break
        elif s == "STATUS_WAIT_CODE":
            if int(time.time() - t0) % 30 < 5:
                log("    [%ds] 等待中..." % int(time.time() - t0))
        elif s.startswith("STATUS_WAIT_RETRY"):
            log("    重试中: %s" % s)
        else:
            log("    状态: %s" % s)

    if code:
        # 6. 提交验证码
        log("[6] 调 Puter /confirm-phone")
        st, body = puter("/confirm-phone", {"code": code}, TOKEN)
        log("    HTTP %s" % st)
        log("    %s" % body[:400])

        if st == 200:
            log("    [OK] 手机验证成功！")
            sb("setStatus", id=act_id, status=6)   # 完成
        else:
            sb("setStatus", id=act_id, status=8)   # 释放
    else:
        log("    [X] 没收到验证码")
        sb("setStatus", id=act_id, status=8)

    # 7. 测 Claude
    log("[7] 测 Claude")
    st, body = puter("/drivers/call", {
        "interface": "puter-chat-completion", "driver": "ai-chat", "method": "complete",
        "args": {"messages": [{"role": "user", "content": "只回OK"}], "model": "claude-sonnet-5-5"}
    }, TOKEN, timeout=120)
    log("    HTTP %s" % st)
    log("    %s" % body[:400])
else:
    log("[!] 没给 token，只测了买号")
    log("    号码: +%s" % phone)
    log("    用法: python %s <puter_token>" % sys.argv[0])
    sb("setStatus", id=act_id, status=8)
