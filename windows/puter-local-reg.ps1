# ============================================================
#  Puter 注册机（本机版）—— 纯 API，不需要浏览器
#  用你的家宽 IP，绕过服务器 IP 风控
#  用法：右键 -> 使用 PowerShell 运行
# ============================================================

$ErrorActionPreference = "Continue"
$Host.UI.RawUI.WindowTitle = "Puter 注册机"

# ---------- 配置 ----------
$YES_KEY   = "YOUR_YESCAPTCHA_KEY"
$SITEKEY   = "0x4AAAAAABvMyOLo9EwjFVzC"
$SIGNUP    = "https://puter.com/signup"
$PAGE_URL  = "https://puter.com/action/signup"
$DOMAIN    = "yourdomain.xyz"
$OUT_FILE  = Join-Path $PSScriptRoot "puter_accounts.txt"

$UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/138.0.0.0 Safari/537.36"

function Log($m) {
    $t = Get-Date -Format "HH:mm:ss"
    Write-Host "[$t] $m"
}

function New-RandomString([int]$len) {
    $chars = "abcdefghijklmnopqrstuvwxyz0123456789"
    -join (1..$len | ForEach-Object { $chars[(Get-Random -Maximum $chars.Length)] })
}

function New-Fingerprint {
    # 32 位 hex（模拟 getDeviceFingerprint 的输出）
    -join (1..32 | ForEach-Object { "0123456789abcdef"[(Get-Random -Maximum 16)] })
}

# ---------- YesCaptcha ----------
function Solve-Turnstile {
    $body = @{
        clientKey = $YES_KEY
        task = @{
            type = "TurnstileTaskProxyless"
            websiteURL = $PAGE_URL
            websiteKey = $SITEKEY
        }
    } | ConvertTo-Json -Depth 5

    try {
        $r = Invoke-RestMethod -Uri "https://api.yescaptcha.com/createTask" -Method Post `
             -Body $body -ContentType "application/json" -TimeoutSec 60
    } catch {
        Log "  YesCaptcha 请求失败: $_"
        return $null
    }

    $tid = $r.taskId
    if (-not $tid) {
        Log "  创建任务失败: $($r | ConvertTo-Json -Compress)"
        return $null
    }

    $t0 = Get-Date
    while (((Get-Date) - $t0).TotalSeconds -lt 180) {
        Start-Sleep -Seconds 3
        $b2 = @{ clientKey = $YES_KEY; taskId = $tid } | ConvertTo-Json
        try {
            $r2 = Invoke-RestMethod -Uri "https://api.yescaptcha.com/getTaskResult" -Method Post `
                  -Body $b2 -ContentType "application/json" -TimeoutSec 60
        } catch { continue }

        if ($r2.status -eq "ready") {
            $tok = $r2.solution.token
            if ($tok) {
                $sec = [int]((Get-Date) - $t0).TotalSeconds
                Log "  Turnstile token 到手 (${sec}s, $($tok.Length) 字符)"
                return $tok
            }
        }
        if ($r2.errorCode -and $r2.errorCode -ne 0) {
            Log "  YesCaptcha 错误: $($r2 | ConvertTo-Json -Compress)"
            return $null
        }
    }
    Log "  YesCaptcha 超时"
    return $null
}

# ---------- 注册一个 ----------
function Register-One([int]$idx) {
    $u = "zw" + (New-RandomString 8)
    $email = "$u@$DOMAIN"
    $pwd = "Ziwei" + (Get-Random -Minimum 100000 -Maximum 999999) + "!aB"
    $fp = New-Fingerprint

    Log "[$idx] $email"

    $tok = Solve-Turnstile
    if (-not $tok) { return $null }

    $payload = @{
        username = $u
        email = $email
        password = $pwd
        referrer = ""
        send_confirmation_code = $false
        p102xyzname = ""
        "cf-turnstile-response" = $tok
        fingerprint = $fp
    } | ConvertTo-Json

    $headers = @{
        "User-Agent" = $UA
        "Accept" = "application/json, text/plain, */*"
        "Origin" = "https://puter.com"
        "Referer" = $PAGE_URL
        "Content-Type" = "application/json"
    }

    $code = 0
    $text = ""
    try {
        $resp = Invoke-WebRequest -Uri $SIGNUP -Method Post -Body $payload `
                -Headers $headers -TimeoutSec 60 -UseBasicParsing -ErrorAction Stop
        $code = [int]$resp.StatusCode
        $text = $resp.Content
    } catch {
        $ex = $_.Exception
        # PS7: HttpResponseMessage
        if ($ex.Response -and $ex.Response.Content) {
            try {
                $code = [int]$ex.Response.StatusCode
                $text = $ex.Response.Content.ReadAsStringAsync().GetAwaiter().GetResult()
            } catch { $text = "read-fail: $_" }
        }
        # PS5: WebResponse
        if (-not $text -and $ex.Response) {
            try {
                $code = [int]$ex.Response.StatusCode
                $stream = $ex.Response.GetResponseStream()
                $sr = New-Object System.IO.StreamReader($stream)
                $text = $sr.ReadToEnd()
                $sr.Close()
            } catch { $text = "stream-fail: $_" }
        }
        if (-not $text) { $text = "EX: $($ex.Message)" }
        if ($code -eq 0) { $code = -1 }
    }
    # 双保险：再单独发一次拿 body
    if ($code -eq 403 -and ($text -eq "" -or $text -like "EX:*")) {
        Log "  (重试读取响应体)"
        try {
            $r2 = Invoke-RestMethod -Uri $SIGNUP -Method Post -Body $payload `
                  -Headers $headers -TimeoutSec 60 -ErrorAction Stop
            $text = ($r2 | ConvertTo-Json -Compress)
        } catch {
            $e2 = $_.ErrorDetails.Message
            if ($e2) { $text = $e2 }
        }
    }

    Log "  响应: $code"
    Log "  body: $($text.Substring(0, [Math]::Min(300, $text.Length)))"

    if ($code -eq 200) {
        try {
            $j = $text | ConvertFrom-Json
            if ($j.token) {
                Log "  [OK] 注册成功！"
                Log "  token: $($j.token.Substring(0, [Math]::Min(50, $j.token.Length)))..."
                $user = $j.user | ConvertTo-Json -Compress
                Log "  user: $($user.Substring(0, [Math]::Min(200, $user.Length)))"
                "$email----$pwd----$($j.token)" | Add-Content -Path $OUT_FILE -Encoding UTF8
                Log "  已存: $OUT_FILE"
                return $j.token
            }
        } catch {
            Log "  解析失败: $_"
        }
    }
    return $null
}

# ---------- 主流程 ----------
Write-Host ""
Write-Host "============================================" -ForegroundColor Cyan
Write-Host "  Puter 注册机（本机版）" -ForegroundColor Cyan
Write-Host "============================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "  本机公网 IP:"
try {
    $ip = (Invoke-RestMethod -Uri "https://api.ipify.org" -TimeoutSec 15)
    Write-Host "    $ip" -ForegroundColor Green
} catch {
    Write-Host "    获取失败" -ForegroundColor Yellow
}
Write-Host ""
Write-Host "  YesCaptcha 余额:"
try {
    $bal = Invoke-RestMethod -Uri "https://api.yescaptcha.com/getBalance" -Method Post `
           -Body (@{clientKey=$YES_KEY} | ConvertTo-Json) -ContentType "application/json" -TimeoutSec 30
    Write-Host "    $($bal.balance)" -ForegroundColor Green
} catch {
    Write-Host "    获取失败" -ForegroundColor Yellow
}
Write-Host ""

$n = Read-Host "  要注册几个？(回车=1)"
if ([string]::IsNullOrWhiteSpace($n)) { $n = 1 }
$n = [int]$n

Write-Host ""
$ok = 0
for ($i = 1; $i -le $n; $i++) {
    try {
        $t = Register-One $i
        if ($t) { $ok++ }
    } catch {
        Log "  异常: $_"
    }
    if ($i -lt $n) {
        Log "  休息 10 秒..."
        Start-Sleep -Seconds 10
    }
}

Write-Host ""
Write-Host "============================================" -ForegroundColor Cyan
Write-Host "  完成: 成功 $ok / $n" -ForegroundColor $(if ($ok -gt 0) { "Green" } else { "Red" })
Write-Host "  账号文件: $OUT_FILE" -ForegroundColor Gray
Write-Host "============================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "  按回车退出..." -ForegroundColor Gray
Read-Host | Out-Null
