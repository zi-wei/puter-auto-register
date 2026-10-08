# ============================================================
#  Puter 批量注册机（本机全自动版）
#  流程: 注册 → 邮箱确认 → 手机验证 → 测 Claude → 落盘
#  用法：右键 -> 使用 PowerShell 运行
# ============================================================

$ErrorActionPreference = "Continue"
$Host.UI.RawUI.WindowTitle = "Puter 批量注册机"

# ---------- 配置 ----------
$YES_KEY  = "YOUR_YESCAPTCHA_KEY"   # YesCaptcha
$SB_KEY   = "YOUR_SMSBOWER_KEY"                 # SMSBower
$SB_API   = "https://smsbower.app/stubs/handler_api.php"
$SITEKEY  = "0x4AAAAAABvMyOLo9EwjFVzC"
$SIGNUP   = "https://puter.com/signup"
$PAGE_URL = "https://puter.com/action/signup"
$API      = "https://api.puter.com"
$DOMAIN   = "yourdomain.xyz"
$MAIL_API = "https://your-mail-api.example.com/mailapi"
$OUT_FILE = Join-Path $PSScriptRoot "puter_accounts.txt"

$UA  = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/138.0.0.0 Safari/537.36"
$UA2 = "puter-js/1.0"

# 接码配置（最便宜）
$SB_SERVICE = "dr"     # OpenAI 标签（号码是真 SIM，任何短信都能收）
$SB_COUNTRY = "12"     # United States (virtual)  $0.004

function Log($m)  { Write-Host ("[{0}] {1}" -f (Get-Date -Format "HH:mm:ss"), $m) }
function Ok($m)   { Write-Host ("[{0}] {1}" -f (Get-Date -Format "HH:mm:ss"), $m) -ForegroundColor Green }
function Bad($m)  { Write-Host ("[{0}] {1}" -f (Get-Date -Format "HH:mm:ss"), $m) -ForegroundColor Red }
function Warn($m) { Write-Host ("[{0}] {1}" -f (Get-Date -Format "HH:mm:ss"), $m) -ForegroundColor Yellow }

function RandStr([int]$n) { $c="abcdefghijklmnopqrstuvwxyz0123456789"; -join (1..$n|%{$c[(Get-Random -Maximum $c.Length)]}) }
function RandHex([int]$n) { -join (1..$n|%{"0123456789abcdef"[(Get-Random -Maximum 16)]}) }

function ApiPost($url, $json, $token, $timeoutSec = 60) {
    $h = @{ "User-Agent"=$UA2; "Content-Type"="application/json"
            "Origin"="https://puter.com"; "Referer"="https://puter.com/" }
    if ($token) { $h["Authorization"] = "Bearer $token" }
    try {
        $r = Invoke-WebRequest -Uri $url -Method Post -Body $json -Headers $h -TimeoutSec $timeoutSec -UseBasicParsing -ErrorAction Stop
        return @{ code=[int]$r.StatusCode; body=$r.Content }
    } catch {
        $c = 0; $b = ""
        if ($_.Exception.Response) {
            try { $c = [int]$_.Exception.Response.StatusCode } catch {}
            try { $b = $_.ErrorDetails.Message } catch {}
            if (-not $b) { try { $b = $_.Exception.Response.Content.ReadAsStringAsync().GetAwaiter().GetResult() } catch {} }
        }
        if (-not $b) { $b = "EX: $($_.Exception.Message)" }
        return @{ code=$c; body=$b }
    }
}

function Decode-Html($s) {
    if (-not $s) { return "" }
    $s = $s -replace '&#x3D;', '=' -replace '&amp;', '&' -replace '&#61;', '='
    $s = $s -replace '&quot;', '"' -replace '&#39;', "'" -replace '&lt;', '<' -replace '&gt;', '>'
    return $s
}

function Curl-Post($url, $jsonBody, $extraHeaders = $null) {
    $tmp = Join-Path $env:TEMP ("pc_" + [guid]::NewGuid().ToString("N") + ".json")
    [System.IO.File]::WriteAllText($tmp, $jsonBody, (New-Object System.Text.UTF8Encoding($false)))
    $args = @("-s", "-m", "60", "-X", "POST", $url,
              "-H", "Content-Type: application/json",
              "-H", "User-Agent: Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/138.0.0.0 Safari/537.36",
              "-H", "Origin: https://puter.com",
              "-H", "Referer: https://puter.com/action/signup",
              "--data-binary", "@$tmp")
    if ($extraHeaders) { foreach ($k in $extraHeaders.Keys) { $args += @("-H", "$k`: $($extraHeaders[$k])") } }
    $out = & curl.exe @args 2>&1
    Remove-Item $tmp -Force -ErrorAction SilentlyContinue
    return ($out -join "`n")
}

function Curl-Get($url, $extraHeaders = $null, $maxTime = 30) {
    $args = @("-s", "-m", "$maxTime", "-L", $url,
              "-H", "User-Agent: Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/138.0.0.0 Safari/537.36")
    if ($extraHeaders) { foreach ($k in $extraHeaders.Keys) { $args += @("-H", "$k`: $($extraHeaders[$k])") } }
    $out = & curl.exe @args 2>&1
    return ($out -join "`n")
}

function Get-Web($url, $timeoutSec = 30, $headers = $null) {
    try {
        if ($headers) {
            $r = Invoke-WebRequest -Uri $url -TimeoutSec $timeoutSec -UseBasicParsing -MaximumRedirection 5 -Headers $headers -ErrorAction Stop
        } else {
            $r = Invoke-WebRequest -Uri $url -TimeoutSec $timeoutSec -UseBasicParsing -MaximumRedirection 5 -ErrorAction Stop
        }
        return @{ code=[int]$r.StatusCode; body=$r.Content }
    } catch { return @{ code=0; body="$($_.Exception.Message)" } }
}

# ---------- SMSBower ----------
function SB($action, $extra = "") {
    $u = "$SB_API`?api_key=$SB_KEY&action=$action$extra"
    try { return (Invoke-WebRequest -Uri $u -TimeoutSec 40 -UseBasicParsing -ErrorAction Stop).Content.Trim() }
    catch { return "ERR: $($_.Exception.Message)" }
}

# ---------- YesCaptcha ----------
function Solve-Turnstile {
    $t = @{clientKey=$YES_KEY; task=@{type="TurnstileTaskProxyless"; websiteURL=$PAGE_URL; websiteKey=$SITEKEY}} | ConvertTo-Json -Depth 5
    try { $r = Invoke-RestMethod -Uri "https://api.yescaptcha.com/createTask" -Method Post -Body $t -ContentType "application/json" -TimeoutSec 60 }
    catch { return $null }
    if (-not $r.taskId) { return $null }
    for ($i=0; $i -lt 50; $i++) {
        Start-Sleep -Seconds 3
        try { $r2 = Invoke-RestMethod -Uri "https://api.yescaptcha.com/getTaskResult" -Method Post -Body (@{clientKey=$YES_KEY;taskId=$r.taskId}|ConvertTo-Json) -ContentType "application/json" -TimeoutSec 60 }
        catch { continue }
        if ($r2.status -eq "ready" -and $r2.solution.token) { return $r2.solution.token }
        if ($r2.errorCode -and $r2.errorCode -ne 0) { return $null }
    }
    return $null
}

# ---------- 单账号流程 ----------
function Register-One([int]$idx, [int]$total) {
    Write-Host ""
    Write-Host "═══════════ 第 $idx / $total 个 ═══════════" -ForegroundColor DarkCyan

    $u = "zw" + (RandStr 8)
    $email = "$u@$DOMAIN"
    $pwd = "Ziwei" + (Get-Random -Minimum 100000 -Maximum 999999) + "!aB"
    Log "邮箱: $email"

    # ---- 1. 注册 ----
    Log "[1/6] 注册"
    $tok = $null
    for ($t=1; $t -le 3; $t++) {
        $tok = Solve-Turnstile
        if ($tok) { break }
        Warn "  Turnstile 重试 $t"
        Start-Sleep -Seconds 4
    }
    if (-not $tok) { Bad "  Turnstile 失败"; return $null }
    Ok "  Turnstile OK ($($tok.Length))"

    $payload = @{
        username=$u; email=$email; password=$pwd
        referrer=""; send_confirmation_code=$false
        p102xyzname=""; "cf-turnstile-response"=$tok
        fingerprint=(RandHex 32)
    } | ConvertTo-Json -Compress
    $body = Curl-Post $SIGNUP $payload
    if (-not $body -or $body -notmatch '"token"') {
        Bad "  注册失败: $($body.Substring(0,[Math]::Min(200,$body.Length)))"
        return $null
    }
    try { $j = $body | ConvertFrom-Json } catch { Bad "  解析失败"; return $null }
    if (-not $j.token) { Bad "  无 token"; return $null }
    $authTok = $j.token
    Ok "  注册成功 uuid=$($j.user.uuid)"

    # ---- 2. 发确认邮件 ----
    Log "[2/6] 请求发送确认邮件"
    $r = ApiPost "$API/send-confirm-email" "{}" $authTok
    Log "  HTTP $($r.code) $($r.body.Substring(0,[Math]::Min(120,$r.body.Length)))"

    # ---- 3. 收确认链接 ----
    Log "[3/6] 轮询邮件..."
    $confirmLink = $null
    $b64Mail = [Convert]::ToBase64String([System.Text.Encoding]::UTF8.GetBytes($email))
    $t0 = Get-Date
    while (((Get-Date) - $t0).TotalSeconds -lt 150) {
        Start-Sleep -Seconds 5
        $mrBody = Curl-Get "$MAIL_API/api/mails?mailbox=$email" @{"Authorization"="Bearer $b64Mail"} 20
        $mr = @{ code = 200; body = $mrBody }
        if ($mr.code -eq 200) {
            $decoded = Decode-Html $mr.body
            $m = [regex]::Match($decoded, 'https://puter\.com/confirm-email-by-token\?token=[a-f0-9-]+&user_uuid=[a-f0-9-]+')
            if ($m.Success) {
                $confirmLink = $m.Value
                Ok "  拿到确认链接"
                break
            }
        }
    }
    if (-not $confirmLink) {
        # 退路：直接调 send-confirm-email 再试，或者跳过
        Warn "  没收到邮件，跳过邮箱确认（可能不影响）"
    } else {
        Log "[4/6] 点确认链接"
        $crBody = Curl-Get $confirmLink $null 30
        $cr = @{ code = 200; body = $crBody }
        if ($cr.body -match 'Success') { Ok "  邮箱确认成功" } else { Warn "  确认响应: $($cr.code)" }
    }

    # ---- 4. 手机验证 ----
    Log "[5/6] 手机验证"
    $numResp = SB "getNumber" "&service=$SB_SERVICE&country=$SB_COUNTRY"
    if ($numResp -notlike "ACCESS_NUMBER*") {
        Warn "  买号失败: $numResp，试国家 6"
        $numResp = SB "getNumber" "&service=ot&country=6"
    }
    if ($numResp -notlike "ACCESS_NUMBER*") { Bad "  买号失败: $numResp"; return @{email=$email;password=$pwd;token=$authTok;phone=$false} }

    $parts = $numResp -split ":"
    $actId = $parts[1]; $phone = $parts[2]
    Log "  号码 +$phone (id=$actId)"

    $sr = ApiPost "$API/send-confirm-phone" (@{phone="+$phone";fingerprint="7c93e5a50e0871e42cb2896cbb5bdd50"}|ConvertTo-Json -Compress) $authTok
    Log "  发短信: $($sr.code) $($sr.body.Substring(0,[Math]::Min(100,$sr.body.Length)))"

    $code = $null
    $t0 = Get-Date
    while (((Get-Date) - $t0).TotalSeconds -lt 180) {
        Start-Sleep -Seconds 5
        $s = SB "getStatus" "&id=$actId"
        if ($s -like "STATUS_OK*") { $code = ($s -split ":")[1]; break }
        if ($s -notlike "STATUS_WAIT*") { Warn "  状态: $s" }
    }

    if ($code) {
        Ok "  验证码: $code"
        $cr = ApiPost "$API/confirm-phone" (@{code=$code}|ConvertTo-Json -Compress) $authTok
        Log "  提交: $($cr.code) $($cr.body.Substring(0,[Math]::Min(150,$cr.body.Length)))"
        SB "setStatus" "&id=$actId&status=6" | Out-Null
        $phoneOk = ($cr.body -match 'phone_verified') -or ($cr.code -eq 200)
    } else {
        Bad "  没收到验证码"
        SB "setStatus" "&id=$actId&status=8" | Out-Null
        $phoneOk = $false
    }

    # ---- 5. 测 Claude ----
    Log "[6/6] 测 Claude"
    $cbody = @{
        interface="puter-chat-completion"; driver="ai-chat"; method="complete"
        args=@{ messages=@(@{role="user";content="只回OK"}); model="claude-sonnet-5-5" }
    } | ConvertTo-Json -Depth 8 -Compress
    $cr = ApiPost "$API/drivers/call" $cbody $authTok 120
    $claudeOk = $false
    if ($cr.code -eq 200 -and $cr.body -match '"success":true') {
        Ok "  [OK][OK] Claude 可用！"
        $claudeOk = $true
    } else {
        Bad "  Claude: $($cr.body.Substring(0,[Math]::Min(200,$cr.body.Length)))"
    }

    return @{ email=$email; password=$pwd; token=$authTok; phone=$phoneOk; claude=$claudeOk }
}

# ---------- 主流程 ----------
Write-Host ""
Write-Host "╔══════════════════════════════════════════╗" -ForegroundColor Cyan
Write-Host "║   Puter 批量注册机（本机全自动）        ║" -ForegroundColor Cyan
Write-Host "║   注册 → 邮箱确认 → 手机验证 → Claude   ║" -ForegroundColor Cyan
Write-Host "╚══════════════════════════════════════════╝" -ForegroundColor Cyan
Write-Host ""

try { $ip = (Invoke-RestMethod -Uri "https://api.ipify.org" -TimeoutSec 15); Write-Host "  本机 IP: $ip" -ForegroundColor Green } catch {}
try {
    $yb = Invoke-RestMethod -Uri "https://api.yescaptcha.com/getBalance" -Method Post -Body (@{clientKey=$YES_KEY}|ConvertTo-Json) -ContentType "application/json" -TimeoutSec 30
    Write-Host "  YesCaptcha: $($yb.balance)" -ForegroundColor Green
} catch {}
$sbb = SB "getBalance"
Write-Host "  SMSBower: $sbb" -ForegroundColor Green
Write-Host ""

$n = Read-Host "  要注册几个？(回车=10)"
if ([string]::IsNullOrWhiteSpace($n)) { $n = 10 }
$n = [int]$n
Write-Host ""

$results = @()
for ($i = 1; $i -le $n; $i++) {
    try {
        $r = Register-One $i $n
        if ($r) {
            $results += $r
            "$($r.email)----$($r.password)----$($r.token)----phone=$($r.phone)----claude=$($r.claude)" |
                Add-Content -Path $OUT_FILE -Encoding UTF8
            Log "  已存: $OUT_FILE"
        }
    } catch { Bad "  异常: $_" }
    if ($i -lt $n) { Log "  休息 12 秒..."; Start-Sleep -Seconds 12 }
}

Write-Host ""
Write-Host "╔══════════════════════════════════════════╗" -ForegroundColor Cyan
$okC = ($results | Where-Object { $_.claude }).Count
$okP = ($results | Where-Object { $_.phone }).Count
Write-Host "║  完成                                  ║" -ForegroundColor Cyan
Write-Host "╚══════════════════════════════════════════╝" -ForegroundColor Cyan
Write-Host "  注册成功:   $($results.Count) / $n"
Write-Host "  手机验证:   $okP / $n" -ForegroundColor $(if($okP -gt 0){"Green"}else{"Red"})
Write-Host "  Claude 可用: $okC / $n" -ForegroundColor $(if($okC -gt 0){"Green"}else{"Red"})
Write-Host "  账号文件:   $OUT_FILE" -ForegroundColor Gray
Write-Host ""
Write-Host "  按回车退出..." -ForegroundColor Gray
Read-Host | Out-Null
