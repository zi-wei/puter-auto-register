#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
测试 rse.re 公益家宽 vmess 节点 + Puter 注册
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
SIGNUP = "https://puter.com/signup"
YES_KEY = "YOUR_YESCAPTCHA_KEY"
SITEKEY = "0x4AAAAAABvMyOLo9EwjFVzC"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/138.0.0.0 Safari/537.36"


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


def parse_vmess(yaml_text):
    """解析 clash yaml 的 vmess 节点"""
    nodes = []
    for line in yaml_text.split("\n"):
        s = line.strip()
        if not s.startswith("- {") or "type: vmess" not in s:
            continue

        def g(k, default=None):
            m = re.search(r'(?:^|[,{\s])%s:\s*"?([^,"}\s]+)"?' % re.escape(k), s)
            return m.group(1).strip().strip('"') if m else default

        name = None
        m = re.search(r'name:\s*"?([^,"]+)"?', s)
        if m:
            name = m.group(1).strip().strip('"')

        server = g("server")
        port = g("port")
        uuid = g("uuid")
        alter = g("alterId", "0")
        cipher = g("cipher", "auto")
        network = g("network", "ws")
        tls = "tls: true" in s
        sni = g("servername")

        # ws-opts 里的 path / Host
        path = "/"
        mp = re.search(r'path:\s*"([^"]+)"', s)
        if mp:
            path = mp.group(1)
        host = sni or server
        mh = re.search(r'headers:\s*\{Host:\s*([^}]+)\}', s)
        if mh:
            host = mh.group(1).strip().strip('"')

        if server and port and uuid:
            nodes.append({
                "name": name or server, "server": server, "port": int(port),
                "uuid": uuid, "alter_id": int(alter) if alter.isdigit() else 0,
                "cipher": cipher, "network": network, "tls": tls,
                "sni": sni or host, "path": path, "host": host,
            })
    return nodes


def build_cfg(node, listen_port):
    ob = {
        "type": "vmess", "tag": "proxy",
        "server": node["server"], "server_port": node["port"],
        "uuid": node["uuid"], "security": node["cipher"],
    }
    if node["alter_id"]:
        ob["alter_id"] = node["alter_id"]
    if node["network"] == "ws":
        ob["transport"] = {"type": "ws", "path": node["path"],
                           "headers": {"Host": node["host"]}}
    if node["tls"]:
        ob["tls"] = {"enabled": True, "server_name": node["sni"], "insecure": True,
                     "utls": {"enabled": True, "fingerprint": "chrome"}}
    return {
        "log": {"level": "warn"},
        "inbounds": [{"type": "http", "tag": "in", "listen": "127.0.0.1", "listen_port": listen_port}],
        "outbounds": [ob],
        "route": {"final": "proxy"},
    }


def test_node(node, port, do_signup=True):
    cfg_path = "/tmp/rc_%d.json" % port
    log_path = "/tmp/rc_%d.log" % port
    with open(cfg_path, "w") as f:
        json.dump(build_cfg(node, port), f)

    subprocess.run(["pkill", "-9", "-f", "rc_%d.json" % port], stderr=subprocess.DEVNULL, stdout=subprocess.DEVNULL)
    time.sleep(0.5)
    with open(log_path, "w") as lf:
        subprocess.Popen(["sing-box", "run", "-c", cfg_path], stdout=lf, stderr=lf)
    time.sleep(7)

    op = urllib.request.build_opener(
        urllib.request.ProxyHandler({"http": "http://127.0.0.1:%d" % port, "https": "http://127.0.0.1:%d" % port})
    )
    try:
        with op.open("https://api.ipify.org", timeout=25) as resp:
            egress = resp.read().decode().strip()
    except Exception as e:
        subprocess.run(["pkill", "-9", "-f", "rc_%d.json" % port], stderr=subprocess.DEVNULL)
        return False, "代理不通: %s" % str(e)[:70], None

    if not do_signup:
        subprocess.run(["pkill", "-9", "-f", "rc_%d.json" % port], stderr=subprocess.DEVNULL)
        return True, "出口 %s" % egress, egress

    tok = solve_turnstile()
    if not tok:
        subprocess.run(["pkill", "-9", "-f", "rc_%d.json" % port], stderr=subprocess.DEVNULL)
        return False, "Turnstile 失败 (出口 %s)" % egress, egress

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
        with op.open(req, timeout=60) as resp:
            body = resp.read().decode("utf-8", "ignore")
            code = resp.status
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", "ignore")
        code = e.code
    except Exception as e:
        body = str(e)[:120]
        code = 0

    subprocess.run(["pkill", "-9", "-f", "rc_%d.json" % port], stderr=subprocess.DEVNULL)

    if code == 200 and '"token"' in body:
        return True, "*** 注册成功！出口 %s ***" % egress, egress
    if "Signup blocked" in body:
        return False, "IP 被拦 (出口 %s)" % egress, egress
    return False, "HTTP %s: %s" % (code, body[:100]), egress


if __name__ == "__main__":
    log("拉订阅...")
    yml = fetch(SUB_URL)
    nodes = parse_vmess(yml)
    log("解析到 %d 个 vmess 节点" % len(nodes))
    for n in nodes:
        log("  %s  %s:%s  path=%s  host=%s" % (n["name"][:30], n["server"], n["port"], n["path"], n["host"]))

    if not nodes:
        log("没解析到节点")
        raise SystemExit(1)

    log("")
    log("=== 先测连通性（不注册）===")
    alive = []
    for i, n in enumerate(nodes):
        ok, msg, eg = test_node(n, 19100 + i, do_signup=False)
        log("  [%d] %-30s -> %s %s" % (i + 1, n["name"][:30], "[OK]" if ok else "[X]", msg))
        if ok:
            alive.append((n, i, eg))
        time.sleep(1)

    log("")
    log("=== 可用节点: %d / %d ===" % (len(alive), len(nodes)))

    if alive:
        log("")
        log("=== 测注册（前 3 个可用节点）===")
        for n, i, eg in alive[:3]:
            ok, msg, eg2 = test_node(n, 19100 + i, do_signup=True)
            log("  %-30s -> %s %s" % (n["name"][:30], "[OK]" if ok else "[X]", msg))
            if ok:
                log("  *** 找到可用节点！***")
                break
            time.sleep(3)
