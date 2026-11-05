# Called only when start.bat cannot find a suitable runtime. No admin needed.
$ErrorActionPreference = 'Stop'
try {
    $answer = Read-Host 'Download and install official Python 3.12 for your Windows account? [Y/N]'
    if ($answer -notmatch '^(y|yes)$') {
        Write-Host 'Install Python 3.10+ from https://www.python.org/downloads/windows/ and run start.bat again.'
        exit 1
    }
    if (-not [Environment]::Is64BitOperatingSystem) {
        throw 'Automatic setup requires 64-bit Windows. Install the matching Python package manually.'
    }
    # Stable Python 3.12 Windows installer. TLS + official python.org source;
    # require a valid Python Software Foundation Authenticode signature before running.
    $installer = Join-Path $env:TEMP ('tailchat-python-' + [guid]::NewGuid().ToString() + '.exe')
    [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
    Write-Host 'Downloading Python from python.org...'
    Invoke-WebRequest -UseBasicParsing -Uri 'https://www.python.org/ftp/python/3.12.10/python-3.12.10-amd64.exe' -OutFile $installer
    $signature = Get-AuthenticodeSignature -LiteralPath $installer
    if ($signature.Status -ne 'Valid' -or $signature.SignerCertificate.Subject -notmatch 'Python Software Foundation') {
        throw 'The Python installer signature could not be verified. Download Python manually from python.org.'
    }
    Write-Host 'Installing Python. This may take a few minutes...'
    $process = Start-Process -FilePath $installer -ArgumentList '/quiet InstallAllUsers=0 Include_launcher=1 InstallLauncherAllUsers=0 Include_test=0 PrependPath=1' -WindowStyle Hidden -Wait -PassThru
    if ($process.ExitCode -notin @(0, 3010)) { throw "Python setup failed with exit code $($process.ExitCode)." }
    Write-Host 'Python installed. If the launcher still cannot find it, reopen start.bat.'
    exit 0
} catch {
    Write-Host ('Python setup failed: ' + $_.Exception.Message) -ForegroundColor Red
    Write-Host 'Manual download: https://www.python.org/downloads/windows/'
    exit 1
}
