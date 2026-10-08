# ============================================================
#  Puter 注册助手 + Auth Token 提取器  (v2)
#  用法：右键 -> 使用 PowerShell 运行
# ============================================================

$ErrorActionPreference = "Continue"
$Host.UI.RawUI.WindowTitle = "Puter 注册助手"

$workDir = Join-Path $env:TEMP "puter-helper"
New-Item -ItemType Directory -Force -Path $workDir | Out-Null
$htmlPath = Join-Path $workDir "index.html"
$port = 18999

Write-Host ""
Write-Host "============================================" -ForegroundColor Cyan
Write-Host "  Puter 注册助手 + Token 提取" -ForegroundColor Cyan
Write-Host "============================================" -ForegroundColor Cyan
Write-Host ""

# ---------- 1. 生成 HTML ----------
$html = @'
<!DOCTYPE html>
<html lang="zh">
<head>
<meta charset="utf-8">
<title>Puter Helper</title>
<style>
  body { font-family: "Segoe UI", sans-serif; max-width: 900px; margin: 24px auto; padding: 0 20px;
         background: #0d1117; color: #e6edf3; }
  h1 { color: #58a6ff; margin-bottom: 4px; }
  .sub { color: #8b949e; font-size: 13px; margin-bottom: 18px; }
  .box { background: #161b22; border: 1px solid #30363d; border-radius: 8px; padding: 14px 16px; margin: 12px 0; }
  .row { margin: 6px 0; }
  .ok { color: #3fb950; font-weight: 600; }
  .bad { color: #f85149; font-weight: 600; }
  .warn { color: #d29922; font-weight: 600; }
  textarea { width: 100%; box-sizing: border-box; height: 160px; background: #0d1117; color: #7ee787;
             border: 1px solid #30363d; border-radius: 6px; padding: 10px;
             font-family: Consolas, monospace; font-size: 12px; resize: vertical; }
  button { background: #238636; color: #fff; border: 0; padding: 9px 18px; border-radius: 6px;
           font-size: 14px; cursor: pointer; margin: 4px 8px 4px 0; }
  button:hover { background: #2ea043; }
  button.blue { background: #1f6feb; }
  button.blue:hover { background: #388bfd; }
  #log { font-family: Consolas, monospace; font-size: 12px; color: #8b949e; white-space: pre-wrap;
         background: #0d1117; border: 1px solid #30363d; border-radius: 6px; padding: 10px;
         height: 180px; overflow-y: auto; }
  .step { color: #58a6ff; font-weight: 600; }
</style>
</head>
<body>

<h1>🦊 Puter Helper</h1>
<div class="sub">注册 Puter 账号 -> 提取 Auth Token -> 测试 Claude</div>

<div class="box">
  <div class="row">SDK 状态：<span id="sdk" class="warn">检测中...</span></div>
  <div class="row">登录状态：<span id="login" class="warn">检测中...</span></div>
  <div class="row">用户名：<span id="user">-</span></div>
</div>

<div class="box">
  <div class="step">第 1 步 —— 注册</div>
  <div style="margin:8px 0;color:#8b949e;font-size:13px;">
    <b style="color:#d29922">重要</b>：Puter 的登录是<b>按 origin 绑定</b>的。<br>
    你在 puter.com 登录<b>不算</b> —— 必须点下面按钮<b>从本页发起登录</b>，<br>
    SDK 会弹窗，登录完自动把 token 传回本页。
  </div>
  <button class="blue" onclick="doSignIn()">登录 / 注册 Puter（弹窗）</button>
  <button onclick="refresh()">刷新登录状态</button>
</div>

<div class="box">
  <div class="step">第 2 步 —— 提取 Token</div>
  <div style="margin:8px 0;color:#8b949e;font-size:13px;">
    注册完回到这个页面，点下面按钮
  </div>
  <button onclick="grabToken()">提取 Auth Token</button>
  <button onclick="testClaude()">测试 Claude 调用</button>
  <button onclick="copyToken()">复制 Token</button>
  <button onclick="saveToken()">下载 Token</button>
</div>

<div class="box">
  <div class="step">Token（复制这段发给我）</div>
  <textarea id="token" readonly placeholder="点上面「提取 Auth Token」..."></textarea>
</div>

<div class="box">
  <div class="step">日志</div>
  <div id="log">就绪</div>
</div>

<script src="https://js.puter.com/v2/"></script>
<script>
function log(m) {
  var el = document.getElementById('log');
  var t = new Date().toLocaleTimeString();
  el.textContent += '\n[' + t + '] ' + m;
  el.scrollTop = el.scrollHeight;
}
function set(id, txt, cls) {
  var el = document.getElementById(id);
  el.textContent = txt;
  el.className = cls || '';
}

window.addEventListener('load', function () {
  setTimeout(function () {
    if (typeof puter === 'undefined') {
      set('sdk', '未加载 [X]', 'bad');
      log('SDK 未加载。换 Chrome/Edge，或检查网络');
    } else {
      set('sdk', '已加载 [OK]', 'ok');
      log('SDK 加载成功');
      refresh();
    }
  }, 3500);
});

function doSignIn() {
  if (typeof puter === 'undefined') { log('SDK 未加载'); return; }
  log('发起登录（会弹窗，请在弹窗里注册/登录）...');
  set('login', '弹窗登录中...', 'warn');

  // 新版 SDK: puter.auth.signIn()
  if (puter.auth && typeof puter.auth.signIn === 'function') {
    puter.auth.signIn().then(function (user) {
      log('[OK] 登录成功: ' + ((user && (user.username || user.email)) || JSON.stringify(user).slice(0,60)));
      set('login', '已登录 [OK]', 'ok');
      setTimeout(grabToken, 800);
    }).catch(function (e) {
      log('[X] 登录失败: ' + ((e && e.message) || e));
      set('login', '登录失败', 'bad');
    });
    return;
  }

  // 兜底：直接调一次 ai.chat 触发登录流程
  log('SDK 无 auth.signIn，改用 ai.chat 触发登录...');
  puter.ai.chat("只回OK", { model: "claude-sonnet-5-5" }).then(function (r) {
    log('[OK] 调用成功，说明已登录');
    set('login', '已登录 [OK]', 'ok');
    setTimeout(grabToken, 500);
  }).catch(function (e) {
    log('[X] 失败: ' + ((e && e.message) || e));
  });
}

function refresh() {
  try {
    if (typeof puter === 'undefined') { log('SDK 未加载'); return; }
    var signed = null;
    try { if (puter.auth && typeof puter.auth.isSignedIn === 'function') signed = puter.auth.isSignedIn(); } catch (e) {}
    if (signed === true) {
      set('login', '已登录 [OK]', 'ok');
      try {
        puter.auth.getUser().then(function (u) {
          set('user', (u && (u.username || u.email)) || JSON.stringify(u).slice(0, 60), 'ok');
        }).catch(function () { set('user', '(读取失败)', 'warn'); });
      } catch (e) { set('user', '(读取失败)', 'warn'); }
    } else if (signed === false) {
      set('login', '未登录', 'warn');
      log('还没登录 —— 先去注册页完成注册');
    } else {
      set('login', '未知（新版 SDK）', 'warn');
      log('SDK 未暴露 isSignedIn，直接试提取 Token');
    }
  } catch (e) { log('refresh 出错: ' + e); }
}

function grabToken() {
  try {
    if (typeof puter === 'undefined') { log('SDK 未加载'); return; }
    var tok = null, src = '';

    if (puter.authToken) { tok = puter.authToken; src = 'puter.authToken'; }
    else if (puter.auth && puter.auth.authToken) { tok = puter.auth.authToken; src = 'puter.auth.authToken'; }
    else if (puter.env && puter.env.authToken) { tok = puter.env.authToken; src = 'puter.env.authToken'; }

    if (!tok) {
      var stores = [localStorage, sessionStorage];
      for (var s = 0; s < stores.length && !tok; s++) {
        var st = stores[s];
        for (var i = 0; i < st.length; i++) {
          var k = st.key(i), v = st.getItem(k);
          if (!v || v.length < 60) continue;
          if (v.indexOf('eyJ') === 0 || k.toLowerCase().indexOf('token') >= 0 || k.toLowerCase().indexOf('auth') >= 0) {
            tok = v; src = (s === 0 ? 'localStorage:' : 'sessionStorage:') + k; break;
          }
        }
      }
    }

    if (tok) {
      document.getElementById('token').value = tok;
      log('[OK] 提取成功 [' + src + ']  长度 ' + tok.length);
      set('login', '已登录 [OK]', 'ok');
    } else {
      log('[X] 没找到 token —— 先完成注册/登录，再点刷新，然后重试');
    }
  } catch (e) { log('提取出错: ' + e); }
}

function copyToken() {
  var t = document.getElementById('token').value;
  if (!t) { log('token 为空'); return; }
  if (navigator.clipboard) {
    navigator.clipboard.writeText(t).then(function () { log('[OK] 已复制到剪贴板'); },
                                          function () { fallbackCopy(); });
  } else { fallbackCopy(); }
}
function fallbackCopy() {
  var el = document.getElementById('token');
  el.removeAttribute('readonly'); el.select();
  try { document.execCommand('copy'); log('[OK] 已复制（兼容模式）'); } catch (e) { log('复制失败，手动选中复制'); }
  el.setAttribute('readonly', 'readonly');
}

function saveToken() {
  var t = document.getElementById('token').value;
  if (!t) { log('token 为空'); return; }
  var blob = new Blob([t], { type: 'text/plain' });
  var a = document.createElement('a');
  a.href = URL.createObjectURL(blob);
  a.download = 'puter_token.txt';
  document.body.appendChild(a); a.click(); document.body.removeChild(a);
  log('[OK] 已下载 puter_token.txt');
}

function testClaude() {
  if (typeof puter === 'undefined') { log('SDK 未加载'); return; }
  log('测试 claude-sonnet-5-5 ...');
  puter.ai.chat("只回OK两个字", { model: "claude-sonnet-5-5" }).then(function (r) {
    var txt = '';
    if (r && r.message && r.message.content) {
      var c = r.message.content;
      txt = (typeof c === 'string') ? c
          : (Array.isArray(c) ? c.map(function (x) { return x.text || ''; }).join('') : JSON.stringify(c));
    } else { txt = JSON.stringify(r); }
    log('[OK] Claude 回复: ' + String(txt).slice(0, 200));
    set('login', '已登录 + Claude 可用 [OK]', 'ok');
  }).catch(function (e) {
    log('[X] Claude 调用失败: ' + ((e && e.message) || e));
  });
}
</script>
</body>
</html>
'@

Set-Content -Path $htmlPath -Value $html -Encoding UTF8
Write-Host "[1/3] 助手页面已生成" -ForegroundColor Green

# ---------- 2. 后台 HTTP 服务 ----------
Write-Host "[2/3] 启动本地服务 (http://localhost:$port/) ..." -ForegroundColor Green

$job = Start-Job -ArgumentList $workDir, $port -ScriptBlock {
    param($dir, $p)
    $l = New-Object System.Net.HttpListener
    $l.Prefixes.Add("http://localhost:$p/")
    try { $l.Start() } catch { return }
    while ($l.IsListening) {
        try {
            $ctx = $l.GetContext()
            $rel = $ctx.Request.Url.LocalPath.TrimStart('/')
            if ([string]::IsNullOrWhiteSpace($rel)) { $rel = 'index.html' }
            $file = Join-Path $dir $rel
            if (Test-Path $file -PathType Leaf) {
                $bytes = [System.IO.File]::ReadAllBytes($file)
                $ctx.Response.ContentType = "text/html; charset=utf-8"
                $ctx.Response.ContentLength64 = $bytes.Length
                $ctx.Response.OutputStream.Write($bytes, 0, $bytes.Length)
            } else {
                $ctx.Response.StatusCode = 404
            }
            $ctx.Response.Close()
        } catch { break }
    }
}

Start-Sleep -Seconds 2

# 验证服务
$ok = $false
try {
    $r = Invoke-WebRequest -Uri "http://localhost:$port/" -UseBasicParsing -TimeoutSec 5
    if ($r.StatusCode -eq 200) { $ok = $true }
} catch {}
if ($ok) { Write-Host "      服务就绪 [OK]" -ForegroundColor Green }
else     { Write-Host "      服务启动失败，但可直接打开文件" -ForegroundColor Yellow }

# ---------- 3. 打开浏览器 ----------
Write-Host "[3/3] 打开浏览器..." -ForegroundColor Green
if ($ok) { Start-Process "http://localhost:$port/" }
else     { Start-Process $htmlPath }

Write-Host ""
Write-Host "============================================" -ForegroundColor Cyan
Write-Host "  操作步骤" -ForegroundColor Yellow
Write-Host "============================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "  1. 点「打开 Puter 注册页」" -ForegroundColor White
Write-Host "  2. 用邮箱注册（Cloudflare 验证你点一下）" -ForegroundColor White
Write-Host "  3. 回到助手页点「刷新登录状态」" -ForegroundColor White
Write-Host "  4. 点「提取 Auth Token」" -ForegroundColor White
Write-Host "  5. 点「测试 Claude 调用」确认能用" -ForegroundColor White
Write-Host "  6. 点「复制 Token」，把它发给我" -ForegroundColor White
Write-Host ""
Write-Host "  按回车结束并关闭服务..." -ForegroundColor Gray
Read-Host | Out-Null

Stop-Job $job -ErrorAction SilentlyContinue
Remove-Job $job -Force -ErrorAction SilentlyContinue
Write-Host ""
Write-Host "服务已停止。再见。" -ForegroundColor Green
