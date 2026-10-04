# ============================================================================
#  AUTOMATIC JOB SEARCH SCHEDULE   (right-click this file -> "Run with PowerShell", or setup_watcher.bat)
#
#  "Job Search Watcher" runs every 15 minutes, all day, and at every login. Each check runs the job
#  sites that are due (config/sources.yaml, every_minutes) and alerts you about new jobs. The first
#  check after 09:30 each day is a full search of every site (the morning run), so it still happens
#  when the laptop was off at that time. Runs hidden, no window. Log in output\watch.log
#
#  "Job Search" (optional) runs run_jobs.bat at fixed times. Off by default since 2026-09-26: with the
#  laptop off at 10:00 Windows skipped it, and the watcher's morning run replaces it. Add times to
#  $Times (24-hour clock) to bring it back.
#  To change the watcher interval, edit $WatchEveryMinutes. 0 turns the watcher off.
#  To see them in Windows: Start menu -> "Task Scheduler" -> Task Scheduler Library.
# ============================================================================

$Times = @()
$WatchEveryMinutes = 15

# ----------------------------------------------------------------------------
$Here     = Split-Path -Parent $MyInvocation.MyCommand.Path
$Bat      = Join-Path $Here "run_jobs.bat"
$Log      = Join-Path $Here "output\last_scheduled_run.log"
$PythonW  = Join-Path $Here ".venv\Scripts\pythonw.exe"

# --- full search ---
$TaskName = "Job Search"
Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false -ErrorAction SilentlyContinue
if ($Times.Count -gt 0) {
    $cmdLine = "/c start `"Job Search`" /min cmd /c `"set JOBHUNTER_SCHEDULED=1&& `"$Bat`" > `"$Log`" 2>&1`""
    $action   = New-ScheduledTaskAction -Execute "cmd.exe" -Argument $cmdLine -WorkingDirectory $Here
    $triggers = $Times | ForEach-Object { New-ScheduledTaskTrigger -Daily -At $_ }
    $settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
                -MultipleInstances IgnoreNew -ExecutionTimeLimit (New-TimeSpan -Hours 2)
    Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $triggers -Settings $settings `
        -Description "Full search of every job site. Change times in schedule_job_search.ps1." | Out-Null
    Write-Host "Scheduled '$TaskName' daily at: $($Times -join ', ')"
} else {
    Write-Host "Full daily search turned OFF."
}

# --- 24x7 watcher ---
$WatchName = "Job Search Watcher"
Unregister-ScheduledTask -TaskName $WatchName -Confirm:$false -ErrorAction SilentlyContinue
if ($WatchEveryMinutes -gt 0) {
    $action   = New-ScheduledTaskAction -Execute $PythonW -Argument "-m jobhunter.watch" -WorkingDirectory $Here
    $start    = (Get-Date).AddMinutes(1)
    $trigger  = New-ScheduledTaskTrigger -Once -At $start -RepetitionInterval (New-TimeSpan -Minutes $WatchEveryMinutes)
    $logon    = New-ScheduledTaskTrigger -AtLogOn -User "$env:USERDOMAIN\$env:USERNAME"
    # Also the moment Wi-Fi or a network connects (NetworkProfile event 10000), so a check starts as soon
    # as the internet is back instead of at the next 15-minute mark. Added 2026-09-26 after a rainy-night outage.
    $evtClass = Get-CimClass -ClassName MSFT_TaskEventTrigger -Namespace Root/Microsoft/Windows/TaskScheduler
    $network  = $evtClass | New-CimInstance -ClientOnly
    $network.Enabled = $true
    $network.Subscription = '<QueryList><Query Id="0" Path="Microsoft-Windows-NetworkProfile/Operational"><Select Path="Microsoft-Windows-NetworkProfile/Operational">*[System[Provider[@Name=''Microsoft-Windows-NetworkProfile''] and EventID=10000]]</Select></Query></QueryList>'
    $settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
                -MultipleInstances IgnoreNew -ExecutionTimeLimit (New-TimeSpan -Minutes 50)
    Register-ScheduledTask -TaskName $WatchName -Action $action -Trigger @($trigger, $logon, $network) -Settings $settings `
        -Description "Checks job sites every $WatchEveryMinutes minutes and alerts about new jobs. See jobhunter\watch.py." | Out-Null
    Write-Host "Scheduled '$WatchName' every $WatchEveryMinutes minutes (hidden). Log: output\watch.log"
} else {
    Write-Host "Watcher turned OFF."
}
# --- Telegram bot (only once setup_telegram.bat has connected it) ---
# Runs all the time while you are signed in. The 15-minute trigger restarts it if it ever stops;
# "IgnoreNew" keeps it to one copy. Log in output\bot.log
$BotName = "Job Search Bot"
Stop-ScheduledTask -TaskName $BotName -ErrorAction SilentlyContinue
Unregister-ScheduledTask -TaskName $BotName -Confirm:$false -ErrorAction SilentlyContinue
if (Test-Path (Join-Path $Here "config\telegram.yaml")) {
    $action   = New-ScheduledTaskAction -Execute $PythonW -Argument "-m jobhunter.tgbot" -WorkingDirectory $Here
    $atLogon  = New-ScheduledTaskTrigger -AtLogOn -User "$env:USERDOMAIN\$env:USERNAME"
    $keepUp   = New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(1) -RepetitionInterval (New-TimeSpan -Minutes 15)
    $settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
                -MultipleInstances IgnoreNew -ExecutionTimeLimit (New-TimeSpan -Seconds 0)
    Register-ScheduledTask -TaskName $BotName -Action $action -Trigger @($atLogon, $keepUp) -Settings $settings `
        -Description "Telegram bot for the job search. Set up with setup_telegram.bat." | Out-Null
    Start-ScheduledTask -TaskName $BotName
    Write-Host "Telegram bot '$BotName' is running (hidden). Log: output\bot.log"
}
Write-Host "If the laptop is off or asleep, everything catches up as soon as you're back."
if ($Host.Name -eq "ConsoleHost" -and -not $env:NO_PAUSE) { Read-Host "Press Enter to close" }
