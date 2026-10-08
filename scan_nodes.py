#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
多节点扫描器 —— 用 xray 逐个测 Puter 注册
目标：找到没被 Puter 拉黑的家宽 IP
"""
import json
import os
import random
import re
import string
import subprocess
import time
import urllib.error
import urllib.request

SUB_URL = "https://puser.sg.rse.re/api/subscribe?token=YOUR_SUB_TOKEN&type=vmess"
SUB2 = "https://ziwei-33d.pages.dev/sub?token=YOUR_SUB_TOKEN"
SIGNUP = "https://puter.com/signup"
YES_KEY = "YOUR_YESCAPTCHA_KEY"
SITEKEY = "0x4AAAAAABvMyOLo9EwjFVzC"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/138.0.0.0 Safari/537.36"
XRAY = "/usr/local/bin/xray"
OUT = "/opt/mailhook/puter_ok.txt"


def log(m):
    print("[%s] %s" % (time.strftime("%H:%M:%S"), m), flush=True)


def fetch(url, ua="clash-verge/1.5", timeout=40):
    req = urllib.request.Request(url, headers={"User-Agent": ua, "Accept": "*/*"})
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


# ---------- 解析两种订阅 ----------
def parse_yaml_nodes(txt):
    """解析 clash yaml（多行 + 内联两种格式），返回 vmess/vless 节点"""
    nodes = []
    # 多行格式
    blocks = re.split(r'\n(?=- name:|\n  - name:)', txt)
    for blk in blocks:
        if 'type: vmess' not in blk and 'type: vless' not in blk:
            continue
        is_vm = 'type: vmess' in blk

        def g(k, default=None):
            m = re.search(r'^\s+%s:\s*"?([^"\n]+?)"?\s*$' % re.escape(k), blk, re.M)
            return m.group(1).strip().strip('"') if m else default

        name = g("name", "")
        server = g("server")
        port = g("port")
        uuid = g("uuid")
        net = g("network", "ws")
        tls = bool(re.search(r'^\s+tls:\s*true', blk, re.M))
        sni = g("servername")
        path = g("path", "/")
        host = sni or server
        mh = re.search(r'Host:\s*([^\n}]+)', blk)
        if mh:
            host = mh.group(1).strip().strip('"')
        if server and port and uuid:
            nodes.append({"name": name or server, "server": server, "port": int(port),
                          "uuid": uuid, "type": "vmess" if is_vm else "vless",
                          "net": net, "tls": tls, "sni": sni or host,
                          "path": path, "host": host})

    # 内联格式
    for line in txt.split("\n"):
        s = line.strip()
        if not s.startswith("- {") or ("type: vmess" not in s and "type: vless" not in s):
            continue
        is_vm = "type: vmess" in s

        def gi(k, default=None):
            m = re.search(r'(?:^|[,{\s])%s:\s*"?([^,"}\s]+)"?' % re.escape(k), s)
            return m.group(1).strip().strip('"') if m else default
        server = gi("server")
        port = gi("port")
        uuid = gi("uuid")
        sni = gi("servername")
        path = "/"
        mp = re.search(r'path:\s*"([^"]+)"', s)
        if mp:
            path = mp.group(1)
        host = sni or server
        mh = re.search(r'Host:\s*([^},]+)', s)
        if mh:
            host = mh.group(1).strip().strip('"')
        if server and port and uuid:
            nodes.append({"name": gi("name", server), "server": server, "port": int(port),
                          "uuid": uuid, "type": "vmess" if is_vm else "vless",
                          "net": gi("network", "ws"), "tls": "tls: true" in s,
                          "sni": sni or host, "path": path, "host": host})
    return nodes


def build_xray(node, port):
    if node["type"] == "vmess":
        out = {
            "protocol": "vmess",
            "settings": {"vnext": [{
                "address": node["server"], "port": node["port"],
                "users": [{"id": node["uuid"], "alterId": 0, "security": "auto"}]
            }]},
        }
    else:
        out = {
            "protocol": "vless",
            "settings": {"vnext": [{
                "address": node["server"], "port": node["port"],
                "users": [{"id": node["uuid"], "encryption": "none", "flow": ""}]
            }]},
        }
    ss = {"network": node["net"]}
    if node["tls"]:
        ss["security"] = "tls"
        ss["tlsSettings"] = {"serverName": node["sni"], "allowInsecure": True,
                             "fingerprint": "chrome", "alpn": ["http/1.1"]}
    else:
        ss["security"] = "none"
    if node["net"] == "ws":
        ss["wsSettings"] = {"path": node["path"], "headers": {"Host": node["host"]}}
    out["streamSettings"] = ss
    return {
        "log": {"loglevel": "error"},
        "inbounds": [{"port": port, "listen": "127.0.0.1", "protocol": "http"}],
        "outbounds": [out],
    }


def test_node(node, port, do_signup=True):
    cfg = "/tmp/xn_%d.json" % port
    with open(cfg, "w") as f:
        json.dump(build_xray(node, port), f)
    subprocess.run(["pkill", "-9", "-f", "xn_%d.json" % port],
                   stderr=subprocess.DEVNULL, stdout=subprocess.DEVNULL)
    time.sleep(0.4)
    with open("/tmp/xn_%d.log" % port, "w") as lf:
        subprocess.Popen([XRAY, "run", "-c", cfg], stdout=lf, stderr=lf)
    time.sleep(4)

    op = urllib.request.build_opener(
        urllib.request.ProxyHandler({"http": "http://127.0.0.1:%d" % port,
                                     "https": "http://127.0.0.1:%d" % port}))
    try:
        with op.open("https://api.ipify.org", timeout=18) as r:
            egress = r.read().decode().strip()
    except Exception as e:
        subprocess.run(["pkill", "-9", "-f", "xn_%d.json" % port], stderr=subprocess.DEVNULL)
        return False, "不通", None

    if not do_signup:
        subprocess.run(["pkill", "-9", "-f", "xn_%d.json" % port], stderr=subprocess.DEVNULL)
        return True, "出口 %s" % egress, egress

    tok = solve_turnstile()
    if not tok:
        subprocess.run(["pkill", "-9", "-f", "xn_%d.json" % port], stderr=subprocess.DEVNULL)
        return False, "Turnstile 失败", egress

    u = "zw" + "".join(random.choices(string.ascii_lowercase + string.digits, k=8))
    payload = {"username": u, "email": u + "@yourdomain.xyz", "password": "Ziwei123456!aB",
               "referrer": "", "send_confirmation_code": False, "p102xyzname": "",
               "cf-turnstile-response": tok,
               "fingerprint": "".join(random.choices("0123456789abcdef", k=32))}
    req = urllib.request.Request(SIGNUP, data=json.dumps(payload).encode(), method="POST")
    req.add_header("Content-Type", "application/json")
    req.add_header("User-Agent", UA)
    req.add_header("Origin", "https://puter.com")
    req.add_header("Referer", "https://puter.com/action/signup")
    try:
        with op.open(req, timeout=60) as r:
            body = r.read().decode("utf-8", "ignore")
            code = r.status
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", "ignore")
        code = e.code
    except Exception as e:
        body = str(e)[:100]
        code = 0
    subprocess.run(["pkill", "-9", "-f", "xn_%d.json" % port], stderr=subprocess.DEVNULL)

    if code == 200 and '"token"' in body:
        try:
            j = json.loads(body)
            open(OUT, "a").write("%s@yourdomain.xyz----Ziwei123456!aB----%s\n" % (u, j["token"]))
        except Exception:
            pass
        return True, "*** 注册成功！出口 %s ***" % egress, egress
    if "Signup blocked" in body:
        return False, "IP 被拦 (%s)" % egress, egress
    return False, "HTTP %s: %s" % (code, body[:80]), egress


if __name__ == "__main__":
    limit = int(os.environ.get("LIMIT", "20"))
    log("拉两个订阅...")
    n1 = parse_yaml_nodes(fetch(SUB_URL))
    log("  rse.re: %d 节点" % len(n1))
    try:
        n2 = parse_yaml_nodes(fetch(SUB2))
        log("  ziwei-33d: %d 节点" % len(n2))
    except Exception as e:
        n2 = []
        log("  ziwei-33d 失败: %s" % str(e)[:60])

    # 优先 rse.re 家宽，然后 ziwei 里非 CF 的
    CF = ("104.", "172.6", "162.15", "198.41", "188.114", "190.93", "197.234", "141.101")
    pri = [n for n in n1]
    others = [n for n in n2 if not n["server"].startswith(CF)]
    all_nodes = pri + others
    # 去重
    seen = set()
    uniq = []
    for n in all_nodes:
        k = "%s:%s:%s" % (n["server"], n["port"], n["uuid"])
        if k in seen:
            continue
        seen.add(k)
        uniq.append(n)
    log("  合计去重 %d 个" % len(uniq))

    log("")
    log("=== 阶段1：测连通性（找能用的）===")
    alive = []
    for i, n in enumerate(uniq[:limit * 2]):
        ok, msg, eg = test_node(n, 20000 + i, do_signup=False)
        if ok:
            alive.append((n, 20000 + i, eg))
            log("  [OK] %-28s %s" % (n["name"][:28], msg))
        if len(alive) >= limit:
            break
    log("  可用: %d" % len(alive))

    if not alive:
        log("没有可用节点")
        raise SystemExit(1)

    log("")
    log("=== 阶段2：逐个测注册 ===")
    for n, port, eg in alive:
        ok, msg, eg2 = test_node(n, port, do_signup=True)
        log("  %-28s %s %s" % (n["name"][:28], "[OK]" if ok else "[X]", msg))
        if ok:
            log("")
            log("*** 找到可用节点！***")
            log("  %s (%s)" % (n["name"], n["server"]))
            log("  出口: %s" % eg2)
            break
        time.sleep(2)
