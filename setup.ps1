# One time install for the job search. Double-click setup.bat rather than running this file.
# 1. Finds Python 3.11 or newer (a normal build, not the free-threaded one). Installs Python 3.12 with winget if missing.
# 2. Finds Google Chrome (used to read Naukri and to make the CV PDFs). Installs it with winget if missing.
# 3. Creates the .venv folder and installs the packages in requirements.txt.
# Safe to run again. It only installs what is missing.

$ErrorActionPreference = "Continue"
$Here = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $Here

function Say($text) { Write-Host "  $text" }

function Stop-Setup($text) {
    Write-Host ""
    Say $text
    Say "Setup did not finish. Fix the problem above and run setup.bat again."
    exit 1
}

$Check = "import sys, sysconfig; ok = sys.version_info[:2] >= (3, 11) and not sysconfig.get_config_var('Py_GIL_DISABLED'); print(sys.executable if ok else '')"

function Test-Python($exe, $extra) {
    try {
        $out = & $exe @extra -c $Check 2>$null
        if ($LASTEXITCODE -eq 0 -and $out) {
            $path = ($out | Select-Object -Last 1).ToString().Trim()
            if ($path -and (Test-Path $path)) { return $path }
        }
    } catch {}
    return $null
}

function Find-Python {
    if (Get-Command py -ErrorAction SilentlyContinue) {
        foreach ($v in "-3.12", "-3.13", "-3.11", "-3.14") {
            $p = Test-Python "py" @($v)
            if ($p) { return $p }
        }
    }
    if (Get-Command python -ErrorAction SilentlyContinue) {
        $p = Test-Python "python" @()
        if ($p) { return $p }
    }
    foreach ($v in "312", "313", "311", "314") {
        $exe = Join-Path $env:LOCALAPPDATA "Programs\Python\Python$v\python.exe"
        if (Test-Path $exe) {
            $p = Test-Python $exe @()
            if ($p) { return $p }
        }
    }
    return $null
}

function Find-Chrome {
    $paths = @(
        (Join-Path $env:ProgramFiles "Google\Chrome\Application\chrome.exe"),
        (Join-Path ${env:ProgramFiles(x86)} "Google\Chrome\Application\chrome.exe"),
        (Join-Path $env:LOCALAPPDATA "Google\Chrome\Application\chrome.exe")
    )
    foreach ($p in $paths) { if ($p -and (Test-Path $p)) { return $p } }
    return $null
}

function Install-App($id, $name, $extra) {
    if (-not (Get-Command winget -ErrorAction SilentlyContinue)) { return }
    Say "$name is not installed. Installing it now, this can take a few minutes..."
    Say "(If Windows asks for permission, click Yes.)"
    & winget install -e --id $id --silent --accept-package-agreements --accept-source-agreements @extra | Out-Host
}

Write-Host ""
Say "Job search setup. The first time takes about 5 to 10 minutes."
Write-Host ""

# 1. Python
$py = Find-Python
if (-not $py) {
    Install-App "Python.Python.3.12" "Python" @("--scope", "user")
    $py = Find-Python
}
if (-not $py) {
    Stop-Setup "Python could not be installed by itself. Install Python 3.12 from python.org/downloads (tick 'Add python.exe to PATH')."
}
Say "Python found at $py"

# 2. Google Chrome
$chrome = Find-Chrome
if (-not $chrome) {
    Install-App "Google.Chrome" "Google Chrome" @()
    $chrome = Find-Chrome
}
if (-not $chrome) {
    Stop-Setup "Google Chrome could not be installed by itself. Install it from google.com/chrome."
}
Say "Google Chrome found"

# 3. The .venv folder with the packages
$venvPy = Join-Path $Here ".venv\Scripts\python.exe"
if (-not (Test-Path $venvPy)) {
    Say "Creating the .venv folder..."
    & $py -m venv (Join-Path $Here ".venv")
    if (-not (Test-Path $venvPy)) { Stop-Setup "Could not create the .venv folder." }
}
Say "Installing the packages the job search needs..."
& $venvPy -m pip install --upgrade pip --quiet --disable-pip-version-check | Out-Host
& $venvPy -m pip install -r (Join-Path $Here "requirements.txt") --quiet --disable-pip-version-check | Out-Host
if ($LASTEXITCODE -ne 0) { Stop-Setup "Installing the packages failed. Check the internet connection." }

Write-Host ""
Say "Setup complete."
exit 0
