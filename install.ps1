$ErrorActionPreference = 'Stop'
if (-not (Get-Command python -ErrorAction SilentlyContinue)) {
    throw 'Python 3.11 이상을 설치한 뒤 다시 실행하세요.'
}
python -c "import sys; sys.exit(0 if sys.version_info >= (3,11) else 1)"
if ($LASTEXITCODE -ne 0) { throw 'Python 3.11 이상이 필요합니다.' }
python (Join-Path $PSScriptRoot 'skills/exam-register/scripts/connector.py') install
if ($LASTEXITCODE -ne 0) { throw '스킬 설치에 실패했습니다.' }
Write-Host '스킬 설치 완료. README의 configure 명령으로 외부 편집기를 연결하세요.'
