$ErrorActionPreference = "Stop"

Set-Location -LiteralPath $PSScriptRoot
if (Test-Path -LiteralPath ".\dist\DeepCodeWinApp\_internal\data") {
    Write-Warning "Old packaged runtime data exists under dist\DeepCodeWinApp\_internal\data. Do not distribute it; it may contain API keys."
}
python -m pip install pyinstaller
python -m PyInstaller --noconsole --clean --name DeepCodeWinApp .\run_app.py
