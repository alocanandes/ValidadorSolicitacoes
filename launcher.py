import os
import sys
import subprocess
import webbrowser
from pathlib import Path

def main():
    # Diretório base
    if getattr(sys, 'frozen', False):
        base_dir = Path(sys._MEIPASS) if hasattr(sys, "_MEIPASS") else Path(sys.executable).parent
        work_dir = Path(sys.executable).parent
    else:
        base_dir = Path(__file__).parent
        work_dir = base_dir

    # Caminho do app.py
    app_path = work_dir / "app.py"
    if not app_path.exists():
        maybe_app = Path(sys._MEIPASS) / "app.py" if hasattr(sys, "_MEIPASS") else None
        if maybe_app and maybe_app.exists():
            app_path = maybe_app
        else:
            raise FileNotFoundError("Não encontrei o app.py ao lado do executável.")

    # Abre navegador automaticamente
    try:
        webbrowser.open("http://localhost:8510", new=2)
    except Exception:
        pass

    # Executa o streamlit
    cmd = [sys.executable, "-m", "streamlit", "run", str(app_path),
           "--server.headless", "true", "--server.port", "8510"]

    subprocess.call(cmd, cwd=str(work_dir))

if __name__ == "__main__":
    main()
