$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

$match = Select-String -Path widle.py -Pattern '^__version__ = "(\d+)\.(\d+)\.(\d+)"$' | Select-Object -First 1
if (-not $match) { throw 'Could not find __version__ = "X.Y.Z" in widle.py' }
$parts = $match.Matches[0].Groups[1..3] | ForEach-Object { $_.Value }
$version = $parts -join "."
$exeName = "Widle-v$version"

if (Get-Process -Name "Widle*" -ErrorAction SilentlyContinue) {
    throw "Widle is still running. Right-click its tray icon and choose Exit, then run this script again."
}

if (-not (Test-Path ".venv-build")) {
    python -m venv .venv-build
}
& .\.venv-build\Scripts\python.exe -m pip install --disable-pip-version-check -q -r requirements-build.txt

& .\.venv-build\Scripts\python.exe -m unittest -q test_widle
if ($LASTEXITCODE -ne 0) { throw "Tests failed" }

New-Item -ItemType Directory -Force build | Out-Null
& .\.venv-build\Scripts\python.exe -c "import tray, pathlib; pathlib.Path('build/widle.ico').write_bytes(tray.ico_file())"
if ($LASTEXITCODE -ne 0) { throw "Icon generation failed" }

$fileVersion = ($parts + "0") -join ", "
@"
VSVersionInfo(
  ffi=FixedFileInfo(filevers=($fileVersion), prodvers=($fileVersion), mask=0x3f, flags=0x0,
                    OS=0x40004, fileType=0x1, subtype=0x0, date=(0, 0)),
  kids=[
    StringFileInfo([StringTable('040904B0', [
      StringStruct('FileDescription', 'Widle monthly profit widget'),
      StringStruct('FileVersion', '$version'),
      StringStruct('InternalName', 'Widle'),
      StringStruct('OriginalFilename', '$exeName.exe'),
      StringStruct('ProductName', 'Widle'),
      StringStruct('ProductVersion', '$version')])]),
    VarFileInfo([VarStruct('Translation', [1033, 1200])])
  ])
"@ | Set-Content -Encoding ASCII build\version_info.txt

& .\.venv-build\Scripts\pyinstaller.exe --noconfirm --onefile --windowed --name $exeName --icon build\widle.ico --version-file build\version_info.txt Widle.pyw
if ($LASTEXITCODE -ne 0) { throw "Build failed" }

$exe = "$PSScriptRoot\dist\$exeName.exe"
$shortcut = Join-Path ([Environment]::GetFolderPath("Desktop")) "Widle.lnk"
if (Test-Path $shortcut) {
    $link = (New-Object -ComObject WScript.Shell).CreateShortcut($shortcut)
    $link.TargetPath = $exe
    $link.WorkingDirectory = "$PSScriptRoot\dist"
    $link.Save()
    Write-Host "Desktop shortcut now points to $exeName.exe"
}

Write-Host "Built $exe"
