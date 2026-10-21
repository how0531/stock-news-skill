# 登記或移除 Windows 工作排程 stock-news-bullish。
# 週一到週五每天 -At (預設 07:50) 執行: python -X utf8 scripts\news.py --bullish
# 產出 out\bullish\latest.json, 說明見 references\bullish_watchlist.md。
#
#   預覽(不登記):  powershell -ExecutionPolicy Bypass -File scripts\register_bullish_task.ps1 -DryRun
#   登記:           powershell -ExecutionPolicy Bypass -File scripts\register_bullish_task.ps1
#   改時間:         powershell -ExecutionPolicy Bypass -File scripts\register_bullish_task.ps1 -At 08:10
#   移除:           powershell -ExecutionPolicy Bypass -File scripts\register_bullish_task.ps1 -Remove
#
# 重跑登記會覆蓋同名工作。以目前使用者登記, 只在登入時執行, 不存密碼。
# 路徑全由本檔位置與 PATH 上的 python 推算。換了 Python 之後要重跑一次登記。
# 此檔必須存成 UTF-8 with BOM, Windows PowerShell 5.1 才讀得懂中文。

[CmdletBinding()]
param(
    [switch]$Remove,
    [switch]$DryRun,
    [string]$At = '07:50'
)

$ErrorActionPreference = 'Stop'
$TaskName = 'stock-news-bullish'
$SkillRoot = Split-Path $PSScriptRoot

if ($Remove) {
    $existing = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
    if (-not $existing) {
        Write-Host "沒有名為 $TaskName 的工作, 不需要移除"
        exit 0
    }
    if ($DryRun) {
        Write-Host "[DryRun] 會移除工作 $TaskName, 這次沒有動"
        exit 0
    }
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
    Write-Host "已移除工作 $TaskName"
    exit 0
}

try {
    $time = [datetime]::ParseExact($At, 'HH:mm', [Globalization.CultureInfo]::InvariantCulture)
} catch {
    throw "-At 要寫成 HH:mm (24 小時制), 例如 07:50, 收到: $At"
}

$python = Get-Command python -ErrorAction SilentlyContinue
if (-not $python) {
    throw '找不到 python, 請先安裝 Python 並確認 python 在 PATH 上'
}
$newsPy = Join-Path $PSScriptRoot 'news.py'
if (-not (Test-Path -LiteralPath $newsPy)) {
    throw "找不到 $newsPy"
}

$arguments = "-X utf8 `"$newsPy`" --bullish"
$days = 'Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday'
$user = [Security.Principal.WindowsIdentity]::GetCurrent().Name

if ($DryRun) {
    Write-Host '[DryRun] 只列出設定, 不登記'
    Write-Host "TaskName   : $TaskName"
    Write-Host "Execute    : $($python.Source)"
    Write-Host "Arguments  : $arguments"
    Write-Host "WorkingDir : $SkillRoot"
    Write-Host "Trigger    : Weekly $($days -join ', ') at $At"
    Write-Host "User       : $user (只在登入時執行, 不存密碼)"
    Write-Host 'Settings   : StartWhenAvailable, 執行上限 15 分鐘, 電池供電也執行'
    exit 0
}

$action = New-ScheduledTaskAction -Execute $python.Source -Argument $arguments -WorkingDirectory $SkillRoot
$trigger = New-ScheduledTaskTrigger -Weekly -DaysOfWeek $days -At $time
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 15) `
    -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries
$principal = New-ScheduledTaskPrincipal -UserId $user -LogonType Interactive

Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger `
    -Settings $settings -Principal $principal `
    -Description 'stock-news-skill 新聞利多清單 (news.py --bullish)' -Force | Out-Null
Write-Host "已登記工作 $TaskName (週一到週五 $At)"
