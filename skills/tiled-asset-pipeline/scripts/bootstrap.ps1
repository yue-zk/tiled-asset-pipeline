param([string]$Workspace = (Get-Location).Path)
$ErrorActionPreference = 'Stop'
$PSNativeCommandUseErrorActionPreference = $false
$scriptDirectory = $PSScriptRoot
$pythonExecutable = $null
foreach ($candidate in @('python3', 'python')) {
    $command = Get-Command $candidate -ErrorAction SilentlyContinue
    if ($command -and $command.Source -notmatch '[\\/]WindowsApps[\\/]') {
        & $command.Source -c 'import sys; sys.exit(not(sys.version_info.major == 3 and 11 <= sys.version_info.minor <= 14))' 2>$null
        if ($LASTEXITCODE -eq 0) { $pythonExecutable = $command.Source; break }
    }
}
if (-not $pythonExecutable) {
    $launcher = Get-Command py -ErrorAction SilentlyContinue
    if ($launcher) {
        $launched = & $launcher.Source -3 -c 'import sys; sys.exit(1) if not(sys.version_info.major == 3 and 11 <= sys.version_info.minor <= 14) else print(sys.executable)' 2>$null
        if ($LASTEXITCODE -eq 0) { $pythonExecutable = $launched }
    }
}
if (-not $pythonExecutable) {
    $uvCommand = Get-Command uv -ErrorAction SilentlyContinue
    $userBin = Join-Path ([Environment]::GetFolderPath('UserProfile')) '.local/bin'
    $uvExecutable = if ($uvCommand) { $uvCommand.Source } else { Join-Path $userBin 'uv.exe' }
    if (-not (Test-Path -LiteralPath $uvExecutable)) {
        Write-Host 'Installing uv from https://astral.sh/uv/install.ps1 into the user directory.'
        $installer = Join-Path ([IO.Path]::GetTempPath()) ('tiled-uv-' + [Guid]::NewGuid().ToString('N') + '.ps1')
        $oldInstallDir, $oldNoModify = $env:UV_INSTALL_DIR, $env:UV_NO_MODIFY_PATH
        try {
            Invoke-WebRequest -Uri 'https://astral.sh/uv/install.ps1' -OutFile $installer
            $env:UV_INSTALL_DIR, $env:UV_NO_MODIFY_PATH = $userBin, '1'
            & $installer
            if (-not (Test-Path -LiteralPath $uvExecutable)) { throw 'uv installation did not produce the expected executable.' }
        } finally {
            $env:UV_INSTALL_DIR, $env:UV_NO_MODIFY_PATH = $oldInstallDir, $oldNoModify
            Remove-Item -LiteralPath $installer -ErrorAction SilentlyContinue
        }
    }
    & $uvExecutable python install 3.12
    if ($LASTEXITCODE -ne 0) { throw 'uv Python installation failed; see references/environment.md.' }
    $pythonExecutable = & $uvExecutable python find --managed-python 3.12
    if ($LASTEXITCODE -ne 0) { throw 'uv could not locate Python 3.12.' }
}
& $pythonExecutable -B (Join-Path $scriptDirectory 'pipeline.py') doctor --install --workspace $Workspace
exit $LASTEXITCODE
