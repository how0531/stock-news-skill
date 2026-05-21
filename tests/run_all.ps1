# run_all.ps1 — 一鍵跑 stock-news-skill 所有測試
# 設好 UTF-8 環境,逐一跑三個 test 檔,匯總 pass/fail。

$ErrorActionPreference = "Continue"
$env:PYTHONIOENCODING = "utf-8"
chcp 65001 | Out-Null

$Bar = "=" * 58

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$Python = "python"

$Tests = @(
    @{ Name = "test_health";                File = "test_health.py" },
    @{ Name = "test_query_news_api";        File = "test_query_news_api.py" },
    @{ Name = "test_cli_smoke";             File = "test_cli_smoke.py" },
    @{ Name = "test_sentiment";             File = "test_sentiment.py" },
    @{ Name = "test_formatters";            File = "test_formatters.py" },
    @{ Name = "test_query_news_internals";  File = "test_query_news_internals.py" }
)

$Results = @()
$TotalT0 = Get-Date

Write-Host ""
Write-Host $Bar -ForegroundColor Cyan
Write-Host " stock-news-skill 測試套件" -ForegroundColor Cyan
Write-Host " 時間: $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')" -ForegroundColor Cyan
Write-Host $Bar -ForegroundColor Cyan

foreach ($t in $Tests) {
    $path = Join-Path $ScriptDir $t.File
    Write-Host ""
    Write-Host ">>> 跑 $($t.Name) ($($t.File))" -ForegroundColor Yellow
    Write-Host ("-" * 58)
    $t0 = Get-Date
    & $Python -X utf8 $path
    $code = $LASTEXITCODE
    $elapsed = ((Get-Date) - $t0).TotalSeconds
    $passed = ($code -eq 0)
    $Results += [PSCustomObject]@{
        Name    = $t.Name
        Passed  = $passed
        ExitCode = $code
        Seconds = [math]::Round($elapsed, 1)
    }
    if ($passed) {
        Write-Host ">>> $($t.Name): PASS (${elapsed}s)" -ForegroundColor Green
    } else {
        Write-Host ">>> $($t.Name): FAIL (exit=$code, ${elapsed}s)" -ForegroundColor Red
    }
}

$TotalElapsed = ((Get-Date) - $TotalT0).TotalSeconds
$PassCount = ($Results | Where-Object { $_.Passed }).Count
$FailCount = ($Results | Where-Object { -not $_.Passed }).Count

Write-Host ""
Write-Host $Bar -ForegroundColor Cyan
Write-Host " 總計" -ForegroundColor Cyan
Write-Host $Bar -ForegroundColor Cyan
$Results | Format-Table -AutoSize | Out-String | Write-Host
Write-Host " Pass: $PassCount / $($Results.Count)" -ForegroundColor $(if ($FailCount -eq 0) { "Green" } else { "Yellow" })
Write-Host " Fail: $FailCount" -ForegroundColor $(if ($FailCount -eq 0) { "Green" } else { "Red" })
Write-Host (" 總耗時: " + [math]::Round($TotalElapsed, 1) + " 秒")
Write-Host $Bar -ForegroundColor Cyan

if ($FailCount -eq 0) { exit 0 } else { exit 1 }
