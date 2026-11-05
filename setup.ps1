# One-command setup on Windows 10/11: Julia, the LDraw parts, RVO2, the Julia packages, the Jupyter kernel and the
# Python environment for the dashboard and JupyterLab. Nothing else needs to be installed first except Git.
# Safe to run again: finished steps are skipped and interrupted downloads resume.
#     powershell -ExecutionPolicy Bypass -File setup.ps1     (or double-click setup.bat)
param(
    [string]$Rvo2Env = 'C:\Conda-Envs\lego_rvo2',
    [string]$BuildDir = 'C:\rvo2build'   # short path: the old GCC fails on paths over 260 characters
)
$ErrorActionPreference = 'Stop'
$Repo = $PSScriptRoot
$Rvo2Commit = '4174d402b4f229275f9f441709e8cf6aaece42c4'
$JuliaVersion = (Select-String -Path "$Repo\Manifest.toml" -Pattern '^julia_version = "(.+)"').Matches[0].Groups[1].Value
$NeedsPython311 = 'import sys; sys.exit(sys.version_info[:2] < (3, 11))'
$TestsRvo2 = 'import rvo2; s = rvo2.PyRVOSimulator(0.025, 2., 5, 2., 1., .5, 4., (0., 0.)); s.setAgentAlpha(s.addAgent((0., 0.)), .5)'

function Step($message) { Write-Host "`n=== $message" -ForegroundColor Cyan }

function Run {
    $exe, $rest = $args
    & $exe $rest   # not @rest: with one argument $rest is a string, and splatting would split it into characters
    if ($LASTEXITCODE) { throw "Failed with exit code ${LASTEXITCODE}: $exe $rest" }
}

function Works {
    $ErrorActionPreference = 'Continue'   # in PowerShell 5.1, 'Stop' turns a native program's stderr into an exception
    $exe, $rest = $args
    if (-not (Get-Command $exe -ErrorAction SilentlyContinue)) { return $false }
    & $exe $rest *> $null
    return $LASTEXITCODE -eq 0
}

function Download($url, $to) {
    if (Test-Path $to) { return }
    # Best effort: otherwise many networks fail here with CRYPT_E_REVOCATION_OFFLINE.
    Run curl.exe --ssl-revoke-best-effort -fL --retry 10 --retry-delay 10 --retry-all-errors -C - -o "$to.part" $url
    Move-Item "$to.part" $to
}

# Moves the result into place only once it is complete, so that stopping half-way cannot look like a finished install.
function Unpack($zip, $topFolder, $to) {
    $unpacking = "$to.unpacking"
    if (Test-Path $unpacking) { Remove-Item $unpacking -Recurse -Force }
    New-Item -ItemType Directory -Force $unpacking | Out-Null
    Run "$env:SystemRoot\System32\tar.exe" -xf $zip -C $unpacking
    Move-Item "$unpacking\$topFolder" $to
    Remove-Item $unpacking, $zip -Recurse -Force
}

function Micromamba {
    New-Item -ItemType Directory -Force $BuildDir | Out-Null
    Download 'https://github.com/mamba-org/micromamba-releases/releases/latest/download/micromamba-win-64' "$BuildDir\micromamba.exe"
    $env:MAMBA_ROOT_PREFIX = "$BuildDir\mamba"
    $env:MAMBA_SSL_NO_REVOKE = 'true'   # the same CRYPT_E_REVOCATION_OFFLINE; certificates are still verified
    Run "$BuildDir\micromamba.exe" @args
}

Step "Julia $JuliaVersion"
$Julia = @(
    (Get-ChildItem "$env:USERPROFILE\.julia\juliaup\julia-$JuliaVersion+*\bin\julia.exe" -ErrorAction SilentlyContinue).FullName
    "$env:LOCALAPPDATA\Programs\Julia-$JuliaVersion\bin\julia.exe"
) | Where-Object { $_ -and (Test-Path $_) } | Select-Object -First 1
if (-not $Julia -and (Get-Command julia -ErrorAction SilentlyContinue) -and (& julia --version) -match [regex]::Escape($JuliaVersion)) {
    $Julia = (Get-Command julia).Source
}
if (-not $Julia) {
    # The other Julia versions on this computer stay as they are: results are only comparable on the recorded version.
    $series = $JuliaVersion -replace '\.\d+$', ''
    New-Item -ItemType Directory -Force "$env:LOCALAPPDATA\Programs" | Out-Null
    $zip = "$env:TEMP\julia-$JuliaVersion-win64.zip"
    Download "https://julialang-s3.julialang.org/bin/winnt/x64/$series/julia-$JuliaVersion-win64.zip" $zip
    Unpack $zip "julia-$JuliaVersion" "$env:LOCALAPPDATA\Programs\Julia-$JuliaVersion"
    $Julia ="$env:LOCALAPPDATA\Programs\Julia-$JuliaVersion\bin\julia.exe"
}
Write-Host $Julia

Step 'LDraw parts library (about 140 MB to download)'
# LDrawParser's default is <home>/Documents/ldraw, even when Windows redirects Documents to OneDrive. Julia's home is
# USERPROFILE, whereas $HOME in PowerShell 5.1 can be a network drive.
if (Test-Path "$env:USERPROFILE\Documents\ldraw\parts") {
    Write-Host 'Already installed.'
} else {
    New-Item -ItemType Directory -Force "$env:USERPROFILE\Documents" | Out-Null
    $zip = "$env:TEMP\ldraw-complete.zip"
    Download 'https://library.ldraw.org/library/updates/complete.zip' $zip
    Unpack $zip 'ldraw' "$env:USERPROFILE\Documents\ldraw"
}

Step 'RVO2 collision avoidance (Python 3.7, built from source)'
$Python37 = "$Rvo2Env\python.exe"
if (Works $Python37 -c $TestsRvo2) {
    Write-Host 'Already installed.'
} else {
    if (-not (Test-Path $Python37)) { Micromamba create -y -p $Rvo2Env -c conda-forge python=3.7 pip }
    Run $Python37 -m pip install cython==0.29.36
    if (-not (Test-Path "$BuildDir\gcc\Library\mingw-w64\bin\g++.exe")) { Micromamba create -y -p "$BuildDir\gcc" -c msys2 m2w64-toolchain }
    if (-not (Test-Path "$BuildDir\Python-RVO2")) {
        Run git clone https://github.com/sisl/Python-RVO2.git "$BuildDir\Python-RVO2"
        Run git -C "$BuildDir\Python-RVO2" checkout $Rvo2Commit
    }
    $src = "$BuildDir\Python-RVO2\src"
    $savedPath = $env:PATH
    $env:PATH = "$BuildDir\gcc\Library\mingw-w64\bin;$env:PATH"
    Run $Python37 -m cython --cplus -3 -o "$BuildDir\rvo2.cpp" "$src\rvo2.pyx"
    Run g++ -O2 -shared -std=c++11 -DMS_WIN64 -D_hypot=hypot "-I$Rvo2Env\include" "-I$src" `
        "$BuildDir\rvo2.cpp" "$src\Agent.cpp" "$src\KdTree.cpp" "$src\Obstacle.cpp" "$src\RVOSimulator.cpp" `
        -static-libgcc -static-libstdc++ '-Wl,-Bstatic,--whole-archive' -lwinpthread '-Wl,--no-whole-archive,-Bdynamic' `
        "-L$Rvo2Env" -lpython37 -o "$BuildDir\rvo2.pyd"
    $env:PATH = $savedPath
    Copy-Item "$BuildDir\rvo2.pyd" "$Rvo2Env\Lib\site-packages\rvo2.pyd" -Force
    Run $Python37 -c $TestsRvo2
}

Step 'Julia packages and the Jupyter kernel (the slowest step: 10-30 minutes the first time)'
$env:PYTHON = $Python37   # also stops PyCall's build from downloading its own Miniconda
Run $Julia "$Repo\scripts\setup_julia.jl"

Step 'Python environment for the dashboard and JupyterLab'
$VenvPython = "$Repo\dashboard\.venv\Scripts\python.exe"
if ((Test-Path $VenvPython) -and -not (Works $VenvPython -c $NeedsPython311)) { Remove-Item "$Repo\dashboard\.venv" -Recurse -Force }
if (-not (Test-Path $VenvPython)) {
    $base = @(@('py', '-3.13'), @('py', '-3.12'), @('py', '-3.11'), @('python'), @('python3')) |
        Where-Object { Works @_ -c $NeedsPython311 } | Select-Object -First 1
    if (-not $base) {
        $own = "$(Split-Path $Rvo2Env)\constructionlab_python"
        if (-not (Test-Path "$own\python.exe")) { Micromamba create -y -p $own -c conda-forge python=3.13 }
        $base = , "$own\python.exe"
    }
    $createVenv = @($base) + '-m', 'venv', "$Repo\dashboard\.venv"
    Run @createVenv
}
Run $VenvPython -m pip install -r "$Repo\dashboard\requirements.txt" -r "$Repo\notebooks\requirements.txt"

Step 'Checking the installation with a real simulation'
Run $Julia "--project=$Repo" "$Repo\scripts\verify_install.jl"

New-Item -ItemType File -Force "$Repo\dashboard\.venv\.setup-complete" | Out-Null   # the launchers look for this
if (Test-Path $BuildDir) { Remove-Item $BuildDir -Recurse -Force }   # only the compiler and downloads; rvo2 is installed
Write-Host "`nSetup finished. Start the dashboard with dashboard\start_dashboard.bat and the notebook with notebooks\start_notebook.bat." -ForegroundColor Green
