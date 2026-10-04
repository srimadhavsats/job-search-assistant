# Creates a "Job Search" shortcut on your Desktop that runs run_jobs.bat.
# Run once:  right-click this file -> "Run with PowerShell"
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
$shell = New-Object -ComObject WScript.Shell
$lnk = $shell.CreateShortcut((Join-Path ([Environment]::GetFolderPath("Desktop")) "Job Search.lnk"))
$lnk.TargetPath = Join-Path $here "run_jobs.bat"
$lnk.WorkingDirectory = $here
$lnk.IconLocation = "shell32.dll,22"
$lnk.Description = "Search jobs and update Jobs.xlsx"
$lnk.Save()
Write-Host "Shortcut created on your Desktop: Job Search"
