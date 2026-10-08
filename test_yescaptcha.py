#!/usr/bin/env python3
# YesCaptcha 测试：余额 + Turnstile 求解
import json
import time
import urllib.request
import urllib.error

KEY = "YOUR_YESCAPTCHA_KEY"
API = "https://api.yescaptcha.com"

# Puter 的 Turnstile
SITEKEY = "0x4AAAAAABvMyOLo9EwjFVzC"
PAGE_URL = "https://puter.com/action/signup"


def post(path, body, timeout=60):
    req = urllib.request.Request(API + path, data=json.dumps(body).encode(), method="POST")
    req.add_header("Content-Type", "application/json")
    req.add_header("User-Agent", "Mozilla/5.0")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode("utf-8", "ignore"))
    except urllib.error.HTTPError as e:
        try:
            return json.loads(e.read().decode("utf-8", "ignore"))
        except Exception:
            return {"errorCode": e.code, "errorDescription": "HTTP %d" % e.code}
    except Exception as e:
        return {"errorCode": -1, "errorDescription": str(e)[:150]}


print("=" * 76)
print("YesCaptcha 测试")
print("=" * 76)

# 1. 余额
print("\n### 1. 余额")
d = post("/getBalance", {"clientKey": KEY})
print("  ", json.dumps(d, ensure_ascii=False))

# 2. 创建 Turnstile 任务
print("\n### 2. 创建 Turnstile 任务")
task = {
    "clientKey": KEY,
    "task": {
        "type": "TurnstileTaskProxyless",
        "websiteURL": PAGE_URL,
        "websiteKey": SITEKEY,
    },
}
d = post("/createTask", task)
print("  ", json.dumps(d, ensure_ascii=False))

task_id = d.get("taskId")
if not task_id:
    print("\n  [X] 创建失败，试其它任务类型")
    for t in ["TurnstileTask", "TurnstileTaskProxylessM1", "AntiTurnstileTaskProxyLess"]:
        task["task"]["type"] = t
        d2 = post("/createTask", task)
        print("  %-30s -> %s" % (t, json.dumps(d2, ensure_ascii=False)[:150]))
        if d2.get("taskId"):
            task_id = d2["taskId"]
            break

if task_id:
    print("\n### 3. 轮询结果 (taskId=%s)" % task_id)
    for i in range(40):
        time.sleep(3)
        r = post("/getTaskResult", {"clientKey": KEY, "taskId": task_id})
        st = r.get("status")
        ec = r.get("errorCode")
        if st == "ready":
            sol = r.get("solution") or {}
            tok = sol.get("token") or sol.get("gRecaptchaResponse") or ""
            print("  [OK] 拿到 token！长度 %d" % len(tok))
            print("  token: %s..." % tok[:80])
            with open("/tmp/yes_token.txt", "w") as f:
                f.write(tok)
            print("  已存 /tmp/yes_token.txt")
            break
        elif ec and ec != 0:
            print("  [X] 错误: %s" % json.dumps(r, ensure_ascii=False)[:200])
            break
        else:
            print("  [%2ds] status=%s" % ((i + 1) * 3, st))
else:
    print("\n  [X] 所有任务类型都失败")
