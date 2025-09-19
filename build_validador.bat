@echo off
setlocal

REM Caminho base do projeto
set PROJECT_DIR=%~dp0
cd /d %PROJECT_DIR%

REM Se não existir venv, cria
if not exist ".venv" (
    echo [INFO] Criando ambiente virtual...
    python -m venv .venv
)

REM Ativa o venv
call .venv\Scripts\activate.bat

REM Atualiza pip
echo [INFO] Atualizando pip...
python -m pip install --upgrade pip setuptools wheel

REM Instala dependencias do requirements.txt (se existir)
if exist "requirements.txt" (
    echo [INFO] Instalando dependencias de requirements.txt...
    pip install -r requirements.txt
)

REM Garante que o PyInstaller esta instalado
pip install pyinstaller

REM Compila o EXE
echo [INFO] Gerando executavel...
python -m PyInstaller --onefile --noconsole --name ValidadorSolicitacoes --add-data "app.py;." launcher.py

echo.
echo [SUCESSO] Executavel gerado em: %PROJECT_DIR%dist\ValidadorSolicitacoes.exe
pause

