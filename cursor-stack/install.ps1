# Cursor Stack installer for Windows
# Запуск: Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass; .\cursor-stack\install.ps1

$ErrorActionPreference = "Stop"

Write-Host "=== Cursor Stack Installer ===" -ForegroundColor Cyan
Write-Host ""

# --- 1. Проверка Docker ---
Write-Host "[1/5] Проверка Docker..." -ForegroundColor Yellow
try {
    docker ps | Out-Null
    Write-Host "  OK: Docker работает" -ForegroundColor Green
} catch {
    Write-Host "  ОШИБКА: Docker не запущен. Запусти Docker Desktop и дождись пока кит в трее стабилизируется." -ForegroundColor Red
    exit 1
}

# --- 2. Запуск Qdrant ---
Write-Host ""
Write-Host "[2/5] Запуск Qdrant..." -ForegroundColor Yellow
$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
Push-Location $scriptDir
try {
    docker compose up -d
    Start-Sleep -Seconds 3
    $health = Invoke-WebRequest -Uri "http://localhost:6333/" -UseBasicParsing -ErrorAction SilentlyContinue
    if ($health.StatusCode -eq 200) {
        Write-Host "  OK: Qdrant работает на http://localhost:6333" -ForegroundColor Green
    } else {
        Write-Host "  ВНИМАНИЕ: Qdrant запущен но health check не прошёл" -ForegroundColor Yellow
    }
} finally {
    Pop-Location
}

# --- 3. Копирование Cursor Rules ---
Write-Host ""
Write-Host "[3/5] Установка Cursor Rules..." -ForegroundColor Yellow
$rulesTarget = Join-Path $env:USERPROFILE ".cursor\rules"
New-Item -ItemType Directory -Force -Path $rulesTarget | Out-Null

$rulesSource = Join-Path $scriptDir "rules"
Get-ChildItem -Path $rulesSource -Filter "*.mdc" | ForEach-Object {
    Copy-Item -Path $_.FullName -Destination $rulesTarget -Force
    Write-Host "  Скопировано: $($_.Name)" -ForegroundColor Gray
}
Write-Host "  OK: Rules установлены в $rulesTarget" -ForegroundColor Green

# --- 4. Запрос OpenAI ключа ---
Write-Host ""
Write-Host "[4/5] Настройка OpenAI API ключа для embeddings" -ForegroundColor Yellow
Write-Host "  (можно пропустить, тогда будет использоваться локальный fastembed)" -ForegroundColor Gray
$openaiKey = Read-Host "  OpenAI API ключ (или Enter чтобы пропустить)"

# --- 5. Запрос пути к проекту ---
Write-Host ""
Write-Host "[5/5] Путь к рабочему проекту (для filesystem MCP)" -ForegroundColor Yellow
Write-Host "  Пример: C:\Users\$env:USERNAME\projects\my-app" -ForegroundColor Gray
$projectPath = Read-Host "  Путь к проекту (или Enter для $env:USERPROFILE)"
if ([string]::IsNullOrWhiteSpace($projectPath)) {
    $projectPath = $env:USERPROFILE
}

# --- Генерация mcp.json ---
$cursorDir = Join-Path $env:USERPROFILE ".cursor"
New-Item -ItemType Directory -Force -Path $cursorDir | Out-Null
$mcpPath = Join-Path $cursorDir "mcp.json"

$template = Get-Content (Join-Path $scriptDir "mcp.json.template") -Raw
$projectPathEscaped = $projectPath.Replace("\", "\\")
$mcpContent = $template.Replace("REPLACE_WITH_YOUR_PROJECT_PATH", $projectPathEscaped)

if ([string]::IsNullOrWhiteSpace($openaiKey)) {
    Write-Host "  Используем локальный fastembed (без OpenAI)" -ForegroundColor Gray
    $mcpContent = $mcpContent.Replace('"EMBEDDING_PROVIDER": "openai"', '"EMBEDDING_PROVIDER": "fastembed"')
    $mcpContent = $mcpContent.Replace('"EMBEDDING_MODEL": "text-embedding-3-small"', '"EMBEDDING_MODEL": "sentence-transformers/all-MiniLM-L6-v2"')
    $mcpContent = $mcpContent -replace ',\s*"OPENAI_API_KEY":\s*"REPLACE_WITH_YOUR_KEY"', ''
} else {
    $mcpContent = $mcpContent.Replace("REPLACE_WITH_YOUR_KEY", $openaiKey)
}

if (Test-Path $mcpPath) {
    $backup = "$mcpPath.bak"
    Copy-Item -Path $mcpPath -Destination $backup -Force
    Write-Host "  Существующий mcp.json сохранён как $backup" -ForegroundColor Gray
}

Set-Content -Path $mcpPath -Value $mcpContent -Encoding UTF8
Write-Host "  OK: MCP конфиг записан в $mcpPath" -ForegroundColor Green

# --- Итог ---
Write-Host ""
Write-Host "=== Установка завершена ===" -ForegroundColor Cyan
Write-Host ""
Write-Host "Следующие шаги:" -ForegroundColor Yellow
Write-Host "  1. Полностью закрой Cursor (правый клик по иконке в трее -> Quit)"
Write-Host "  2. Открой Cursor заново"
Write-Host "  3. Проверь MCP: Settings -> MCP -> qdrant-memory должен быть зелёным"
Write-Host "  4. В чате используй: @superpowers, @code-review и т.д."
Write-Host ""
Write-Host "Qdrant UI: http://localhost:6333/dashboard" -ForegroundColor Gray
