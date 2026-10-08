#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
补齐已有账号：邮箱确认 → 手机验证 → 测 Claude
把已有的 3 个账号跑完并写入数据库
"""
import base64
import json
import os
import re
import time
import urllib.error
import urllib.request

API = "https://api.puter.com"
MAIL_API = "https://your-mail-api.example.com/mailapi"
SB_KEY = "YOUR_SMSBOWER_KEY"
SB_API = "https://smsbower.app/stubs/handler_api.php"
SB_SERVICE = "dr"
SB_COUNTRY = "12"
FP = "7c93e5a50e0871e42cb2896cbb5bdd50"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/138.0.0.0 Safari/537.36"
UA2 = "puter-js/1.0"
DB = "/opt/mailhook/puter_accounts.jsonl"

# 已有的 3 个账号（email, password, token）
EXISTING = [
    ("zwti4o6ec0@yourdomain.xyz", "Ziwei123456!aB",
     "REDACTED_TOKEN"),
    ("zwzdlbfofx@yourdomain.xyz", "Ziwei123456!aB", None),   # token 丢失，需重查
    ("zwenfszvvk@yourdomain.xyz", "Ziwei123456!aB",
     "REDACTED_TOKEN"),
]


def log(m):
    print("[%s] %s" % (time.strftime("%H:%M:%S"), m), flush=True)


def ok(m):
    print("[%s] \033[92m%s\033[0m" % (time.strftime("%H:%M:%S"), m), flush=True)


def bad(m):
    print("[%s] \033[91m%s\033[0m" % (time.strftime("%H:%M:%S"), m), flush=True)


def puter_post(path, body, token=None, timeout=60):
    req = urllib.request.Request(API + path, data=json.dumps(body).encode(), method="POST")
    req.add_header("Content-Type", "application/json")
    req.add_header("User-Agent", UA2)
    req.add_header("Origin", "https://puter.com")
    req.add_header("Referer", "https://puter.com/")
    if token:
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
        return 0, str(e)[:150]


def get_mails(email):
    auth = base64.b64encode(email.encode()).decode()
    req = urllib.request.Request("%s/api/mails?mailbox=%s" % (MAIL_API, email),
                                 headers={"User-Agent": UA, "Authorization": "Bearer " + auth})
    try:
        with urllib.request.urlopen(req, timeout=25) as r:
            return json.loads(r.read().decode("utf-8", "ignore"))
    except Exception:
        return {}


def sb(action, extra=""):
    try:
        req = urllib.request.Request("%s?api_key=%s&action=%s%s" % (SB_API, SB_KEY, action, extra),
                                     headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=40) as r:
            return r.read().decode().strip()
    except Exception as e:
        return "ERR: %s" % str(e)[:80]


def find_confirm_link(email):
    """从邮件里找确认链接"""
    mails = get_mails(email)
    for m in (mails.get("messages") or []):
        blob = json.dumps(m, ensure_ascii=False)
        blob = blob.replace("&#x3D;", "=").replace("&amp;", "&")
        mm = re.search(r'https://puter\.com/confirm-email-by-token\?token=[a-f0-9-]+&user_uuid=[a-f0-9-]+', blob)
        if mm:
            return mm.group(0)
    return None


def finish(email, pwd, token):
    log("")
    log("═══ 处理 %s ═══" % email)
    if not token:
        bad("  没有 token，跳过")
        return None

    # 1. 先看当前状态
    st, b = puter_post("/drivers/call", {
        "interface": "puter-chat-completion", "driver": "ai-chat", "method": "complete",
        "args": {"messages": [{"role": "user", "content": "只回OK"}], "model": "claude-sonnet-5-5"}
    }, token, timeout=120)
    if st == 200 and '"success":true' in b:
        ok("  已经可用！")
        return {"email": email, "password": pwd, "token": token, "phone": True, "claude": True,
                "ts": int(time.time()), "note": "already-ok"}
    log("  当前状态: %s" % b[:120])

    # 2. 邮箱确认
    st, b = puter_post("/send-confirm-email", {}, token)
    log("  发确认邮件: %s" % st)
    time.sleep(8)
    link = find_confirm_link(email)
    if link:
        try:
            req = urllib.request.Request(link, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=30) as r:
                if "Success" in r.read().decode("utf-8", "ignore"):
                    ok("  邮箱确认成功")
        except Exception as e:
            log("  确认: %s" % str(e)[:60])
    else:
        log("  没找到确认链接（可能已确认）")

    # 3. 手机验证
    nr = sb("getNumber", "&service=%s&country=%s" % (SB_SERVICE, SB_COUNTRY))
    if not nr.startswith("ACCESS_NUMBER"):
        nr = sb("getNumber", "&service=ot&country=6")
    phone_ok = False
    if nr.startswith("ACCESS_NUMBER"):
        parts = nr.split(":")
        aid, phone = parts[1], parts[2]
        log("  号码 +%s" % phone)
        st, b = puter_post("/send-confirm-phone", {"phone": "+" + phone, "fingerprint": FP}, token)
        log("  发短信: %s %s" % (st, b[:70]))
        code = None
        t0 = time.time()
        while time.time() - t0 < 180:
            time.sleep(5)
            s = sb("getStatus", "&id=%s" % aid)
            if s.startswith("STATUS_OK"):
                code = s.split(":")[1]
                break
        if code:
            st, b = puter_post("/confirm-phone", {"code": code}, token)
            log("  手机验证: %s %s" % (st, b[:100]))
            phone_ok = (st == 200 and "phone_verified" in b)
            sb("setStatus", "&id=%s&status=%s" % (aid, "6" if phone_ok else "8"))
        else:
            bad("  没收到验证码")
            sb("setStatus", "&id=%s&status=8" % aid)
    else:
        bad("  买号失败: %s" % nr[:60])

    # 4. 测 Claude
    st, b = puter_post("/drivers/call", {
        "interface": "puter-chat-completion", "driver": "ai-chat", "method": "complete",
        "args": {"messages": [{"role": "user", "content": "只回OK"}], "model": "claude-sonnet-5-5"}
    }, token, timeout=120)
    claude_ok = (st == 200 and '"success":true' in b)
    if claude_ok:
        ok("  Claude 可用 ✓")
    else:
        bad("  Claude: %s" % b[:150])

    return {"email": email, "password": pwd, "token": token, "phone": phone_ok,
            "claude": claude_ok, "ts": int(time.time())}


if __name__ == "__main__":
    log("=" * 70)
    log("补齐已有账号")
    log("=" * 70)

    # 已有数据库
    have = set()
    if os.path.exists(DB):
        with open(DB) as f:
            for line in f:
                try:
                    have.add(json.loads(line)["email"])
                except Exception:
                    pass
    log("数据库已有 %d 条" % len(have))

    for email, pwd, token in EXISTING:
        if email in have:
            log("")
            log("═══ %s 已在库，跳过 ═══" % email)
            continue
        r = finish(email, pwd, token)
        if r:
            with open(DB, "a") as f:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")
            log("  已写入数据库")

    log("")
    log("=" * 70)
    n = 0
    if os.path.exists(DB):
        with open(DB) as f:
            for line in f:
                try:
                    r = json.loads(line)
                    if r.get("claude"):
                        n += 1
                        log("  ✓ %s" % r["email"])
                except Exception:
                    pass
    log("Claude 可用: %d 个" % n)
    log("=" * 70)
