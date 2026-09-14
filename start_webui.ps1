# QSearch WebUI 启动脚本 (PowerShell)

Write-Host "====================================" -ForegroundColor Cyan
Write-Host "QSearch WebUI Startup" -ForegroundColor Cyan
Write-Host "====================================" -ForegroundColor Cyan
Write-Host ""

# 设置数据库根目录
$env:QSEARCH_DATABASES_ROOT = "databases"
Write-Host "[1/3] 数据库目录: $env:QSEARCH_DATABASES_ROOT" -ForegroundColor Green

# 激活虚拟环境
if (Test-Path ".venv\Scripts\Activate.ps1") {
    Write-Host "[2/3] 激活虚拟环境..." -ForegroundColor Green
    & .venv\Scripts\Activate.ps1
} else {
    Write-Host "[2/3] 警告: 未找到虚拟环境 .venv\Scripts\" -ForegroundColor Yellow
    Write-Host "      尝试使用全局 Python 环境..." -ForegroundColor Yellow
}

# 启动 Streamlit
Write-Host "[3/3] 启动 Streamlit WebUI..." -ForegroundColor Green
Write-Host ""

streamlit run src/qsearch/webui/app.py

# 如果出错，暂停以查看错误信息
if ($LASTEXITCODE -ne 0) {
    Write-Host "`n发生错误，请检查上方输出" -ForegroundColor Red
    Read-Host "按 Enter 键退出"
}

# 如果出错，暂停以查看错误信息
if ($LASTEXITCODE -ne 0) {
    Write-Host "`n发生错误，请检查上方输出" -ForegroundColor Red
    Read-Host "按 Enter 键退出"
}
