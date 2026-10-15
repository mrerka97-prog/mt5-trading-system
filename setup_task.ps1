# Forex ботыг өдөр бүр 06:30-д автоматаар ажиллуулах Windows Task Scheduler-ийн ажил үүсгэнэ.
# Ажиллуулах: PowerShell-ийг нээгээд:  powershell -ExecutionPolicy Bypass -File C:\Projects\forex-bot\setup_task.ps1
#
# - Компьютер унтаж (Sleep) байвал сэрээнэ (WakeToRun).
# - 06:30-д унтраалттай байсан бол дараагийн асах үед шууд ажиллана (StartWhenAvailable).
# - Мягмар–Бямба: Даваа–Баасан гарагийн лаа хаагдсаны дараах өглөө.

$action = New-ScheduledTaskAction -Execute "C:\Projects\forex-bot\run_once.bat" -WorkingDirectory "C:\Projects\forex-bot"
$trigger = New-ScheduledTaskTrigger -Weekly -DaysOfWeek Tuesday,Wednesday,Thursday,Friday,Saturday -At 06:30
$settings = New-ScheduledTaskSettingsSet -WakeToRun -StartWhenAvailable -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries -ExecutionTimeLimit (New-TimeSpan -Hours 1)
Register-ScheduledTask -TaskName "ForexBot E1b" -Action $action -Trigger $trigger -Settings $settings -Force
Write-Host "Бэлэн: 'ForexBot E1b' ажил үүслээ. Task Scheduler-ээс харж болно." -ForegroundColor Green
