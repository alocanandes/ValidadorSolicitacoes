# launcher.py
import sys
import subprocess
import webbrowser
from pathlib import Path

PORT = "8510"  # porta fixa (ajuste se necessário)

def resource_path(rel: str) -> Path:
    """Resolve caminho tanto no EXE (onefile) quanto no dev."""
    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        base = Path(sys._MEIPASS)   # conteúdo extraído do onefile
    else:
        base = Path(__file__).parent
    return (base / rel).resolve()

def main():
    app_path = resource_path("app.py")

    # fallback: tentar ao lado do executável (ex.: onedir)
    if not app_path.exists():
        alt = Path(sys.executable).parent / "app.py"
        if alt.exists():
            app_path = alt
        else:
            raise FileNotFoundError("app.py não encontrado no bundle nem ao lado do executável.")

    # inicia o streamlit no app.py empacotado
    cmd = [
        sys.executable, "-m", "streamlit", "run", str(app_path),
        "--server.headless", "true",
        "--server.port", PORT,
        "--browser.gatherUsageStats", "false",
    ]
    subprocess.Popen(cmd)  # inicia o servidor
    webbrowser.open_new_tab(f"http://localhost:{PORT}")  # abre o navegador

if __name__ == "__main__":
    main()
