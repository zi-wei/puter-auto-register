#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Puter 批量注册机（服务器版，全自动）
流程: 轮换家宽节点 → 注册 → 邮箱确认 → 手机验证 → 测 Claude → 落盘
目标: 凑够 N 个可用账号（含已注册的）
"""
import json
import os
import random
import re
import string
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

# ---------- 配置 ----------
RSE_SUB = "https://puser.sg.rse.re/api/subscribe?token=YOUR_SUB_TOKEN&type=vmess"
YES_KEY = "YOUR_YESCAPTCHA_KEY"
SITEKEY = "0x4AAAAAABvMyOLo9EwjFVzC"
SB_KEY = "YOUR_SMSBOWER_KEY"
SB_API = "https://smsbower.app/stubs/handler_api.php"
SB_SERVICE = "dr"
SB_COUNTRY = "12"
DOMAIN = "yourdomain.xyz"
MAIL_API = "https://your-mail-api.example.com/mailapi"
API = "https://api.puter.com"
SIGNUP = "https://puter.com/signup"
PAGE_URL = "https://puter.com/action/signup"
XRAY = "/usr/local/bin/xray"
DB = "/opt/mailhook/puter_accounts.jsonl"     # 主库
FP = "7c93e5a50e0871e42cb2896cbb5bdd50"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/138.0.0.0 Safari/537.36"
UA2 = "puter-js/1.0"

TARGET = int(os.environ.get("TARGET", "10"))
PORT_BASE = 21000


def log(m):
    print("[%s] %s" % (time.strftime("%H:%M:%S"), m), flush=True)


def ok(m):
    print("[%s] \033[92m%s\033[0m" % (time.strftime("%H:%M:%S"), m), flush=True)


def bad(m):
    print("[%s] \033[91m%s\033[0m" % (time.strftime("%H:%M:%S"), m), flush=True)


# ---------- 节点 ----------
def fetch(url, ua="clash-verge/1.5", timeout=40):
    req = urllib.request.Request(url, headers={"User-Agent": ua, "Accept": "*/*"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode("utf-8", "ignore")


def parse_nodes(txt):
    nodes = []
    blocks = re.split(r'\n(?=- name:|\n  - name:)', txt)
    for blk in blocks:
        if 'type: vmess' not in blk:
            continue

        def g(k, d=None):
            m = re.search(r'^\s+%s:\s*"?([^"\n]+?)"?\s*$' % re.escape(k), blk, re.M)
            return m.group(1).strip().strip('"') if m else d

        name = g("name", "")
        server, port, uuid = g("server"), g("port"), g("uuid")
        if not (server and port and uuid):
            continue
        sni = g("servername") or server
        path = g("path", "/")
        host = sni
        mh = re.search(r'Host:\s*([^\n}]+)', blk)
        if mh:
            host = mh.group(1).strip().strip('"')
        nodes.append({"name": name or server, "server": server, "port": int(port),
                      "uuid": uuid, "sni": sni, "path": path, "host": host})
    return nodes


def build_xray(node, port):
    return {
        "log": {"loglevel": "error"},
        "inbounds": [{"port": port, "listen": "127.0.0.1", "protocol": "http"}],
        "outbounds": [{
            "protocol": "vmess",
            "settings": {"vnext": [{"address": node["server"], "port": node["port"],
                                    "users": [{"id": node["uuid"], "alterId": 0, "security": "auto"}]}]},
            "streamSettings": {
                "network": "ws", "security": "tls",
                "tlsSettings": {"serverName": node["sni"], "allowInsecure": True,
                                "fingerprint": "chrome", "alpn": ["http/1.1"]},
                "wsSettings": {"path": node["path"], "headers": {"Host": node["host"]}},
            },
        }],
    }


class Proxy:
    def __init__(self, node, port):
        self.node = node
        self.port = port
        self.cfg = "/tmp/pb_%d.json" % port
        with open(self.cfg, "w") as f:
            json.dump(build_xray(node, port), f)
        subprocess.run(["pkill", "-9", "-f", "pb_%d.json" % port],
                       stderr=subprocess.DEVNULL, stdout=subprocess.DEVNULL)
        time.sleep(0.4)
        with open("/tmp/pb_%d.log" % port, "w") as lf:
            subprocess.Popen([XRAY, "run", "-c", self.cfg], stdout=lf, stderr=lf)
        time.sleep(3.5)
        self.opener = urllib.request.build_opener(urllib.request.ProxyHandler(
            {"http": "http://127.0.0.1:%d" % port, "https": "http://127.0.0.1:%d" % port}))

    def egress(self):
        try:
            with self.opener.open("https://api.ipify.org", timeout=18) as r:
                return r.read().decode().strip()
        except Exception:
            return None

    def stop(self):
        subprocess.run(["pkill", "-9", "-f", "pb_%d.json" % self.port],
                       stderr=subprocess.DEVNULL, stdout=subprocess.DEVNULL)


# ---------- YesCaptcha ----------
def yc(path, body, timeout=60):
    req = urllib.request.Request("https://api.yescaptcha.com" + path,
                                 data=json.dumps(body).encode(), method="POST")
    req.add_header("Content-Type", "application/json")
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode())


def solve_turnstile():
    d = yc("/createTask", {"clientKey": YES_KEY, "task": {
        "type": "TurnstileTaskProxyless", "websiteURL": PAGE_URL, "websiteKey": SITEKEY}})
    tid = d.get("taskId")
    if not tid:
        return None
    for _ in range(50):
        time.sleep(3)
        r = yc("/getTaskResult", {"clientKey": YES_KEY, "taskId": tid})
        if r.get("status") == "ready":
            return r["solution"]["token"]
        if r.get("errorCode"):
            return None
    return None


# ---------- SMSBower ----------
def sb(action, extra=""):
    u = "%s?api_key=%s&action=%s%s" % (SB_API, SB_KEY, action, extra)
    try:
        req = urllib.request.Request(u, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=40) as r:
            return r.read().decode().strip()
    except Exception as e:
        return "ERR: %s" % str(e)[:80]


# ---------- HTTP ----------
def puter_post(path, body, token=None, opener=None, timeout=60):
    req = urllib.request.Request(API + path, data=json.dumps(body).encode(), method="POST")
    req.add_header("Content-Type", "application/json")
    req.add_header("User-Agent", UA2)
    req.add_header("Origin", "https://puter.com")
    req.add_header("Referer", "https://puter.com/")
    if token:
        req.add_header("Authorization", "Bearer " + token)
    op = opener or urllib.request.build_opener()
    try:
        with op.open(req, timeout=timeout) as r:
            return r.status, r.read().decode("utf-8", "ignore")
    except urllib.error.HTTPError as e:
        try:
            return e.code, e.read().decode("utf-8", "ignore")
        except Exception:
            return e.code, ""
    except Exception as e:
        return 0, str(e)[:150]


def get_mails(email):
    b64 = urllib.parse.quote(email.encode().hex())  # placeholder
    import base64 as _b64
    auth = _b64.b64encode(email.encode()).decode()
    req = urllib.request.Request(
        "%s/api/mails?mailbox=%s" % (MAIL_API, email),
        headers={"User-Agent": UA, "Authorization": "Bearer " + auth})
    try:
        with urllib.request.urlopen(req, timeout=25) as r:
            return json.loads(r.read().decode("utf-8", "ignore"))
    except Exception:
        return {}


# ---------- 数据库 ----------
def load_db():
    if not os.path.exists(DB):
        return []
    out = []
    with open(DB) as f:
        for line in f:
            try:
                out.append(json.loads(line))
            except Exception:
                pass
    return out


def save_db(rec):
    with open(DB, "a") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")


def count_usable():
    return len([r for r in load_db() if r.get("claude")])


# ---------- 单账号流程 ----------
def do_one(idx, node, port):
    p = Proxy(node, port)
    eg = p.egress()
    if not eg:
        p.stop()
        return None, "节点不通"

    log("  [%d] 出口 %s" % (idx, eg))

    # 1. 注册
    tok = solve_turnstile()
    if not tok:
        p.stop()
        return None, "Turnstile 失败"

    u = "zw" + "".join(random.choices(string.ascii_lowercase + string.digits, k=8))
    email = "%s@%s" % (u, DOMAIN)
    pwd = "Ziwei" + "".join(random.choices(string.digits, k=6)) + "!aB"
    payload = {"username": u, "email": email, "password": pwd, "referrer": "",
               "send_confirmation_code": False, "p102xyzname": "",
               "cf-turnstile-response": tok,
               "fingerprint": "".join(random.choices("0123456789abcdef", k=32))}
    req = urllib.request.Request(SIGNUP, data=json.dumps(payload).encode(), method="POST")
    req.add_header("Content-Type", "application/json")
    req.add_header("User-Agent", UA)
    req.add_header("Origin", "https://puter.com")
    req.add_header("Referer", PAGE_URL)
    try:
        with p.opener.open(req, timeout=60) as r:
            body = r.read().decode("utf-8", "ignore")
            code = r.status
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", "ignore")
        code = e.code
    except Exception as e:
        body = str(e)[:120]
        code = 0
    p.stop()

    if code != 200 or '"token"' not in body:
        if "Signup blocked" in body:
            return None, "IP 被拦 (%s)" % eg
        return None, "HTTP %s: %s" % (code, body[:80])

    j = json.loads(body)
    auth = j["token"]
    ok("  注册成功 %s" % email)

    # 2. 发确认邮件
    st, b = puter_post("/send-confirm-email", {}, auth)
    log("  发确认邮件: %s" % st)

    # 3. 收确认链接
    link = None
    t0 = time.time()
    while time.time() - t0 < 150:
        time.sleep(6)
        mails = get_mails(email)
        for m in (mails.get("messages") or []):
            blob = json.dumps(m, ensure_ascii=False)
            blob = blob.replace("&#x3D;", "=").replace("&amp;", "&")
            mm = re.search(r'https://puter\.com/confirm-email-by-token\?token=[a-f0-9-]+&user_uuid=[a-f0-9-]+', blob)
            if mm:
                link = mm.group(0)
                break
        if link:
            break
    if link:
        try:
            req = urllib.request.Request(link, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=30) as r:
                if "Success" in r.read().decode("utf-8", "ignore"):
                    ok("  邮箱确认成功")
        except Exception as e:
            log("  确认请求: %s" % str(e)[:60])
    else:
        log("  没收到确认邮件")

    # 4. 手机验证
    nr = sb("getNumber", "&service=%s&country=%s" % (SB_SERVICE, SB_COUNTRY))
    if not nr.startswith("ACCESS_NUMBER"):
        nr = sb("getNumber", "&service=ot&country=6")
    phone_ok = False
    if nr.startswith("ACCESS_NUMBER"):
        parts = nr.split(":")
        aid, phone = parts[1], parts[2]
        st, b = puter_post("/send-confirm-phone",
                           {"phone": "+" + phone, "fingerprint": FP}, auth)
        log("  发短信: %s %s" % (st, b[:60]))
        code = None
        t0 = time.time()
        while time.time() - t0 < 180:
            time.sleep(5)
            s = sb("getStatus", "&id=%s" % aid)
            if s.startswith("STATUS_OK"):
                code = s.split(":")[1]
                break
        if code:
            st, b = puter_post("/confirm-phone", {"code": code}, auth)
            log("  手机验证: %s %s" % (st, b[:80]))
            phone_ok = (st == 200 and "phone_verified" in b)
            sb("setStatus", "&id=%s&status=%s" % (aid, "6" if phone_ok else "8"))
        else:
            bad("  没收到验证码")
            sb("setStatus", "&id=%s&status=8" % aid)
    else:
        bad("  买号失败: %s" % nr[:60])

    # 5. 测 Claude
    st, b = puter_post("/drivers/call", {
        "interface": "puter-chat-completion", "driver": "ai-chat", "method": "complete",
        "args": {"messages": [{"role": "user", "content": "只回OK"}], "model": "claude-sonnet-5-5"}
    }, auth, timeout=120)
    claude_ok = (st == 200 and '"success":true' in b)
    if claude_ok:
        ok("  Claude 可用 ✓")
    else:
        bad("  Claude: %s" % b[:120])

    rec = {"email": email, "password": pwd, "token": auth, "egress": eg,
           "phone": phone_ok, "claude": claude_ok, "ts": int(time.time())}
    save_db(rec)
    return rec, "OK" if claude_ok else "registered"


# ---------- 主流程 ----------
if __name__ == "__main__":
    log("=" * 70)
    log("Puter 批量注册机 —— 目标 %d 个可用账号" % TARGET)
    log("=" * 70)

    existing = load_db()
    have = count_usable()
    log("已有: %d 个记录，其中 %d 个 Claude 可用" % (len(existing), have))
    for r in existing:
        log("  %s  phone=%s claude=%s" % (r.get("email"), r.get("phone"), r.get("claude")))

    need = TARGET - have
    if need <= 0:
        ok("已达标，无需注册")
        sys.exit(0)
    log("还需 %d 个" % need)

    log("")
    log("拉家宽节点...")
    nodes = parse_nodes(fetch(RSE_SUB))
    log("  %d 个节点（每个不同出口 IP）" % len(nodes))

    # 轮换顺序：随机打乱，每个节点用一次，用完再来一轮
    random.shuffle(nodes)

    done = 0
    attempts = 0
    max_attempts = need * 25
    ni = 0

    while done < need and attempts < max_attempts:
        node = nodes[ni % len(nodes)]
        ni += 1
        attempts += 1
        port = PORT_BASE + (attempts % 50)
        log("")
        log("─── 尝试 %d (还需 %d 个) ───" % (attempts, need - done))
        try:
            rec, msg = do_one(attempts, node, port)
            if rec and rec.get("claude"):
                done += 1
                ok("进度: %d / %d" % (done, need))
            elif rec:
                log("  注册了但 Claude 不可用: %s" % msg)
            else:
                log("  跳过: %s" % msg)
        except Exception as e:
            bad("  异常: %s" % str(e)[:150])
            try:
                subprocess.run(["pkill", "-9", "-f", "pb_%d.json" % port],
                               stderr=subprocess.DEVNULL)
            except Exception:
                pass
        time.sleep(3)

    log("")
    log("=" * 70)
    final = count_usable()
    log("完成: %d 个 Claude 可用账号（目标 %d）" % (final, TARGET))
    for r in load_db():
        if r.get("claude"):
            log("  ✓ %s  (出口 %s)" % (r["email"], r.get("egress")))
    log("数据库: %s" % DB)
    log("=" * 70)
