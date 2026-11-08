# Cài / gỡ tự khởi động cùng Windows bằng Scheduled Task.
#
#   powershell -ExecutionPolicy Bypass -File install_autostart.ps1
#   powershell -ExecutionPolicy Bypass -File install_autostart.ps1 -Remove
#
# Task chạy dashboard; dashboard tự khởi động bot theo (DASHBOARD_AUTOSTART=1).

param(
    [switch]$Remove,
    [string]$TaskName = "SoHo AI Monitor"
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $MyInvocation.MyCommand.Definition
$bat  = Join-Path $root "run_server.bat"

function Test-Admin {
    $id = [Security.Principal.WindowsIdentity]::GetCurrent()
    (New-Object Security.Principal.WindowsPrincipal $id).IsInRole(
        [Security.Principal.WindowsBuiltInRole]::Administrator)
}

if ($Remove) {
    $existing = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
    if ($existing) {
        Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
        Write-Host "Da go task '$TaskName'." -ForegroundColor Green
    } else {
        Write-Host "Khong co task '$TaskName'." -ForegroundColor Yellow
    }
    exit 0
}

if (-not (Test-Path $bat)) {
    Write-Host "Khong tim thay run_server.bat trong $root" -ForegroundColor Red
    exit 1
}

if (-not (Test-Admin)) {
    Write-Host "Can quyen Administrator de tao Scheduled Task." -ForegroundColor Yellow
    Write-Host "Chuot phai PowerShell > Run as administrator, roi chay lai:" -ForegroundColor Yellow
    Write-Host "  powershell -ExecutionPolicy Bypass -File `"$($MyInvocation.MyCommand.Definition)`"" -ForegroundColor Cyan
    exit 1
}

$action = New-ScheduledTaskAction -Execute $bat -WorkingDirectory $root
# ONLOGON: chay khi user dang nhap. Tre 30s de mang/disk san sang.
$trigger = New-ScheduledTaskTrigger -AtLogOn
$trigger.Delay = "PT30S"

$settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -StartWhenAvailable `
    -ExecutionTimeLimit ([TimeSpan]::Zero) `
    -RestartCount 3 `
    -RestartInterval (New-TimeSpan -Minutes 1)

# Chay duoi quyen user hien tai (can quyen ghi vao thu muc repo)
$principal = New-ScheduledTaskPrincipal -UserId "$env:USERDOMAIN\$env:USERNAME" `
    -LogonType Interactive -RunLevel Highest

$existing = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
if ($existing) {
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
    Write-Host "Da xoa task cu de tao lai." -ForegroundColor Yellow
}

Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger `
    -Settings $settings -Principal $principal `
    -Description "SoHo AI bot + dashboard, tu khoi dong khi dang nhap Windows." | Out-Null

Write-Host ""
Write-Host "Da cai task '$TaskName'." -ForegroundColor Green
Write-Host "  Chay khi  : dang nhap Windows (tre 30s)" -ForegroundColor Gray
Write-Host "  Chay file : $bat" -ForegroundColor Gray
Write-Host "  Dashboard : http://127.0.0.1:8787" -ForegroundColor Gray
Write-Host ""
Write-Host "Thu nghiem ngay (khong can reboot):" -ForegroundColor Cyan
Write-Host "  Start-ScheduledTask -TaskName '$TaskName'" -ForegroundColor White
Write-Host ""
Write-Host "Kiem tra:" -ForegroundColor Cyan
Write-Host "  Get-ScheduledTask -TaskName '$TaskName' | Select TaskName,State" -ForegroundColor White
Write-Host ""
Write-Host "Go bo:" -ForegroundColor Cyan
Write-Host "  powershell -ExecutionPolicy Bypass -File `"$($MyInvocation.MyCommand.Definition)`" -Remove" -ForegroundColor White
