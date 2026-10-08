#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Puter 注册 —— 直接调 API（绕过前端）
端点: POST https://puter.com/signup
"""
import json
import random
import re
import string
import sys
import time
import urllib.error
import urllib.request
import http.cookiejar

YES_KEY = "YOUR_YESCAPTCHA_KEY"
YES_API = "https://api.yescaptcha.com"
SITEKEY = "0x4AAAAAABvMyOLo9EwjFVzC"
SIGNUP_PAGE = "https://puter.com/action/signup"
SIGNUP_API = "https://puter.com/signup"
DOMAIN = "yourdomain.xyz"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/138.0.0.0 Safari/537.36"


def log(m):
    print("[%s] %s" % (time.strftime("%H:%M:%S"), m), flush=True)


def hreq(method, url, data=None, headers=None, cookies=None, timeout=45):
    h = {"User-Agent": UA, "Accept": "application/json, text/plain, */*",
         "Origin": "https://puter.com", "Referer": SIGNUP_PAGE}
    if headers:
        h.update(headers)
    body = None
    if data is not None:
        if isinstance(data, dict):
            body = json.dumps(data).encode()
            h.setdefault("Content-Type", "application/json")
        else:
            body = data.encode() if isinstance(data, str) else data
            h.setdefault("Content-Type", "application/x-www-form-urlencoded")
    req = urllib.request.Request(url, data=body, method=method)
    for k, v in h.items():
        req.add_header(k, v)
    op = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cookies)) if cookies else urllib.request.build_opener()
    try:
        with op.open(req, timeout=timeout) as r:
            return r.status, r.read().decode("utf-8", "ignore"), dict(r.headers)
    except urllib.error.HTTPError as e:
        try:
            return e.code, e.read().decode("utf-8", "ignore"), dict(e.headers)
        except Exception:
            return e.code, "", {}
    except Exception as e:
        return 0, str(e)[:200], {}


def yc(path, body, timeout=60):
    req = urllib.request.Request(YES_API + path, data=json.dumps(body).encode(), method="POST")
    req.add_header("Content-Type", "application/json")
    req.add_header("User-Agent", "Mozilla/5.0")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode("utf-8", "ignore"))
    except Exception as e:
        return {"err": str(e)[:150]}


def solve_turnstile(page_url=SIGNUP_PAGE, timeout=180):
    d = yc("/createTask", {"clientKey": YES_KEY, "task": {
        "type": "TurnstileTaskProxyless", "websiteURL": page_url, "websiteKey": SITEKEY}})
    tid = d.get("taskId")
    if not tid:
        log("  YesCaptcha 失败: %s" % json.dumps(d, ensure_ascii=False)[:150])
        return None
    t0 = time.time()
    while time.time() - t0 < timeout:
        time.sleep(3)
        r = yc("/getTaskResult", {"clientKey": YES_KEY, "taskId": tid})
        if r.get("status") == "ready":
            tok = (r.get("solution") or {}).get("token") or ""
            if tok:
                log("  Turnstile token 到手 (%.0fs, %d 字符)" % (time.time() - t0, len(tok)))
                return tok
        if r.get("errorCode"):
            log("  YesCaptcha 错误: %s" % json.dumps(r, ensure_ascii=False)[:150])
            return None
    return None


def register(idx):
    u = "zw" + "".join(random.choices(string.ascii_lowercase + string.digits, k=8))
    email = "%s@%s" % (u, DOMAIN)
    pwd = "Ziwei" + "".join(random.choices(string.digits, k=6)) + "!aB"
    log("[%d] %s" % (idx, email))

    cj = http.cookiejar.CookieJar()

    # 1. 先访问注册页拿 cookie
    st, body, hdrs = hreq("GET", SIGNUP_PAGE, cookies=cj)
    log("  注册页: %s" % st)

    # 2. 拿 csrf / gui token（如果有）
    for p in ["/get-gui-token", "/api/auth/csrf"]:
        st2, b2, _ = hreq("GET", "https://puter.com" + p, cookies=cj)
        log("  %s -> %s %s" % (p, st2, b2[:80].replace("\n", " ")))

    # 3. 解 Turnstile
    log("  求解 Turnstile...")
    tok = solve_turnstile()
    if not tok:
        return None

    # 4. 提交
    payload = {
        "username": u,
        "email": email,
        "password": pwd,
        "referrer": "",
        "send_confirmation_code": False,
        "p102xyzname": "",              # 蜜罐，必须空
        "cf-turnstile-response": tok,
        "bonusCode": "",
    }
    log("  提交 POST /signup ...")
    st, body, hdrs = hreq("POST", SIGNUP_API, data=payload, cookies=cj,
                          headers={"Content-Type": "application/json"})
    log("  响应: %s" % st)
    log("  body: %s" % body[:400].replace("\n", " "))

    if st in (200, 201):
        try:
            d = json.loads(body)
        except Exception:
            d = {}
        log("  [OK] 注册成功！")
        log("  %s" % json.dumps(d, ensure_ascii=False)[:400])
        with open("/opt/mailhook/puter_accounts.txt", "a") as f:
            f.write("%s----%s----%s\n" % (email, pwd, json.dumps(d, ensure_ascii=False)[:200]))
        return {"email": email, "password": pwd, "resp": d}

    # 也试试表单格式
    log("  试表单格式...")
    form = urllib.parse.urlencode(payload)
    st, body, hdrs = hreq("POST", SIGNUP_API, data=form, cookies=cj,
                          headers={"Content-Type": "application/x-www-form-urlencoded"})
    log("  响应: %s" % st)
    log("  body: %s" % body[:400].replace("\n", " "))
    if st in (200, 201):
        log("  [OK] 表单格式成功！")
        with open("/opt/mailhook/puter_accounts.txt", "a") as f:
            f.write("%s----%s----FORM\n" % (email, pwd))
        return {"email": email, "password": pwd, "resp": body[:300]}

    return None


def main():
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 1
    log("=" * 60)
    log("Puter 注册（直连 API）—— 目标 %d" % n)
    b = yc("/getBalance", {"clientKey": YES_KEY})
    log("YesCaptcha 余额: %s" % b.get("balance"))
    log("=" * 60)
    ok = 0
    for i in range(1, n + 1):
        try:
            r = register(i)
            if r:
                ok += 1
        except Exception as e:
            log("  异常: %s" % str(e)[:200])
        if i < n:
            time.sleep(10)
    log("=" * 60)
    log("完成: %d / %d" % (ok, n))


if __name__ == "__main__":
    import urllib.parse
    main()
