# Telegram listener-ийг Windows-д нэвтрэх бүрт ДАЛД (цонхгүй) автоматаар асаах Task Scheduler-ийн ажил.
# Ажиллуулах: PowerShell-ийг нээгээд:
#   powershell -ExecutionPolicy Bypass -File C:\Projects\forex-bot\setup_listener_task.ps1
#
# - Нэвтрэх үед (At log on) асна. pythonw.exe тул хар цонх гарахгүй.
# - Хугацааны хязгааргүй ажиллана. Унтарвал 1 минутын дараа дахин асна (3 удаа хүртэл).
# - Лог: logs\telegram.log
# Зогсоох:   Stop-ScheduledTask -TaskName "ForexBot Telegram"
# Устгах:    Unregister-ScheduledTask -TaskName "ForexBot Telegram" -Confirm:$false

$root = "C:\Projects\forex-bot"
$pyw = Join-Path $root ".venv\Scripts\pythonw.exe"
if (-not (Test-Path $pyw)) {
    Write-Host "Олдсонгүй: $pyw  (.venv үүссэн эсэхийг шалгана уу)" -ForegroundColor Red
    exit 1
}
$action = New-ScheduledTaskAction -Execute $pyw -Argument "scripts\telegram_listener.py --service" -WorkingDirectory $root
$trigger = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME
$trigger.Delay = "PT1M"     # нэвтэрсний дараа 1 минут хүлээнэ (интернэт, MT5 бэлэн болох хугацаа)
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
    -StartWhenAvailable -ExecutionTimeLimit ([TimeSpan]::Zero) -MultipleInstances IgnoreNew `
    -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 1)
Register-ScheduledTask -TaskName "ForexBot Telegram" -Action $action -Trigger $trigger -Settings $settings -Force | Out-Null
Write-Host "Бэлэн: 'ForexBot Telegram' ажил үүслээ. Одоо шууд асаая..." -ForegroundColor Green
Start-ScheduledTask -TaskName "ForexBot Telegram"
Start-Sleep -Seconds 15
Get-ScheduledTask -TaskName "ForexBot Telegram" | Select-Object TaskName, State | Format-Table
Write-Host "Утсанд '🟢 Telegram listener асав' мессеж ирэх ёстой." -ForegroundColor Green
