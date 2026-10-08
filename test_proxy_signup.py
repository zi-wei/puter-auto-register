#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
代理池轮换注册测试
流程: 拉订阅 → 解析节点 → 逐个起 sing-box → 测 Puter 注册
"""
import json
import os
import re
import subprocess
import time
import urllib.request
import urllib.parse

SUB_URL = "https://ziwei-33d.pages.dev/sub?token=YOUR_SUB_TOKEN"
SIGNUP = "https://puter.com/signup"
YES_KEY = "YOUR_YESCAPTCHA_KEY"
SITEKEY = "0x4AAAAAABvMyOLo9EwjFVzC"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/138.0.0.0 Safari/537.36"
SB_KEY = "YOUR_SMSBOWER_KEY"


def log(m):
    print("[%s] %s" % (time.strftime("%H:%M:%S"), m), flush=True)


def fetch(url, headers=None, timeout=40):
    h = {"User-Agent": UA}
    if headers:
        h.update(headers)
    req = urllib.request.Request(url, headers=h)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode("utf-8", "ignore")


def yc(path, body, timeout=60):
    req = urllib.request.Request("https://api.yescaptcha.com" + path,
                                 data=json.dumps(body).encode(), method="POST")
    req.add_header("Content-Type", "application/json")
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode())


def solve_turnstile():
    d = yc("/createTask", {"clientKey": YES_KEY, "task": {
        "type": "TurnstileTaskProxyless", "websiteURL": "https://puter.com/action/signup",
        "websiteKey": SITEKEY}})
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


# ---------- 解析 Clash YAML 节点 ----------
def parse_nodes(yaml_text):
    nodes = []
    for line in yaml_text.split("\n"):
        line = line.strip()
        if not line.startswith("- {") or "server:" not in line:
            continue
        if "type: vless" not in line:
            continue
        def g(k):
            m = re.search(r'%s:\s*"?([^,"}]+)"?' % k, line)
            return m.group(1).strip().strip('"') if m else None
        name = g("name")
        server = g("server")
        port = g("port")
        uuid = g("uuid")
        path = None
        m = re.search(r'path:\s*"([^"]+)"', line)
        if m:
            path = m.group(1)
        sni = g("servername")
        if server and port and uuid:
            nodes.append({"name": name or server, "server": server, "port": int(port),
                          "uuid": uuid, "path": path or "/?ed=2560", "sni": sni or "ziwei-33d.pages.dev"})
    return nodes


def build_cfg(node, listen_port):
    return {
        "log": {"level": "warn"},
        "inbounds": [{"type": "http", "tag": "in", "listen": "127.0.0.1", "listen_port": listen_port}],
        "outbounds": [{
            "type": "vless", "tag": "proxy",
            "server": node["server"], "server_port": node["port"],
            "uuid": node["uuid"], "flow": "",
            "transport": {"type": "ws", "path": node["path"],
                          "headers": {"Host": node["sni"]}},
            "tls": {"enabled": True, "server_name": node["sni"], "insecure": False,
                    "utls": {"enabled": True, "fingerprint": "chrome"}},
        }],
        "route": {"final": "proxy"},
    }


def test_node(node, port):
    """起代理 + 测注册，返回 (是否可用, 说明)"""
    cfg_path = "/tmp/pn_%d.json" % port
    log_path = "/tmp/pn_%d.log" % port
    with open(cfg_path, "w") as f:
        json.dump(build_cfg(node, port), f)

    subprocess.run(["pkill", "-9", "-f", "pn_%d.json" % port],
                   stderr=subprocess.DEVNULL, stdout=subprocess.DEVNULL)
    time.sleep(0.5)
    with open(log_path, "w") as lf:
        subprocess.Popen(["sing-box", "run", "-c", cfg_path], stdout=lf, stderr=lf)
    time.sleep(6)

    # 测出口
    try:
        r = urllib.request.build_opener(
            urllib.request.ProxyHandler({"http": "http://127.0.0.1:%d" % port, "https": "http://127.0.0.1:%d" % port})
        )
        with r.open("https://api.ipify.org", timeout=20) as resp:
            egress = resp.read().decode().strip()
    except Exception as e:
        subprocess.run(["pkill", "-9", "-f", "pn_%d.json" % port], stderr=subprocess.DEVNULL)
        return False, "代理不通: %s" % str(e)[:60]

    # 解 Turnstile
    tok = solve_turnstile()
    if not tok:
        subprocess.run(["pkill", "-9", "-f", "pn_%d.json" % port], stderr=subprocess.DEVNULL)
        return False, "Turnstile 失败 (出口 %s)" % egress

    # 注册（走代理）
    import random, string
    u = "zw" + "".join(random.choices(string.ascii_lowercase + string.digits, k=8))
    payload = {
        "username": u, "email": "%s@yourdomain.xyz" % u, "password": "Ziwei123456!aB",
        "referrer": "", "send_confirmation_code": False, "p102xyzname": "",
        "cf-turnstile-response": tok,
        "fingerprint": "".join(random.choices("0123456789abcdef", k=32)),
    }
    req = urllib.request.Request(SIGNUP, data=json.dumps(payload).encode(), method="POST")
    req.add_header("Content-Type", "application/json")
    req.add_header("User-Agent", UA)
    req.add_header("Origin", "https://puter.com")
    req.add_header("Referer", "https://puter.com/action/signup")
    try:
        with r.open(req, timeout=60) as resp:
            body = resp.read().decode("utf-8", "ignore")
            code = resp.status
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", "ignore")
        code = e.code
    except Exception as e:
        body = str(e)[:100]
        code = 0

    subprocess.run(["pkill", "-9", "-f", "pn_%d.json" % port], stderr=subprocess.DEVNULL)

    if code == 200 and '"token"' in body:
        return True, "OK! 出口 %s" % egress
    if "Signup blocked" in body:
        return False, "IP 被拦 (出口 %s)" % egress
    if "captcha" in body.lower():
        return False, "captcha 失败"
    return False, "HTTP %s: %s" % (code, body[:100])


if __name__ == "__main__":
    log("拉订阅...")
    yml = fetch(SUB_URL)
    nodes = parse_nodes(yml)
    log("解析到 %d 个 vless 节点" % len(nodes))

    # 去重（按 server）
    seen = set()
    uniq = []
    for n in nodes:
        key = n["server"]
        if key in seen:
            continue
        seen.add(key)
        uniq.append(n)
    log("去重后 %d 个" % len(uniq))

    # 测前 N 个
    limit = int(os.environ.get("LIMIT", "15"))
    ok = []
    for i, n in enumerate(uniq[:limit]):
        log("[%d/%d] %s (%s)" % (i + 1, limit, n["name"][:30], n["server"]))
        good, msg = test_node(n, 19000 + i)
        log("    -> %s %s" % ("[OK]" if good else "[X]", msg))
        if good:
            ok.append(n)
            log("    *** 可用节点！***")
            if len(ok) >= 3:
                break
        time.sleep(2)

    print()
    log("=" * 60)
    log("可用节点: %d / %d" % (len(ok), min(limit, len(uniq))))
    for n in ok:
        log("  %s (%s)" % (n["name"][:40], n["server"]))
