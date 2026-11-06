# Starts the API with the project's virtual environment (..\.venv), whether or not it is activated.
# Run from the backend folder:  .\dev.ps1
$python = Join-Path $PSScriptRoot "..\.venv\Scripts\python.exe"
if (-not (Test-Path $python)) {
    Write-Error "No virtual environment at ..\.venv. Create it first (see the README)."
    exit 1
}
Set-Location $PSScriptRoot
& $python -m uvicorn app.main:app --reload @args
