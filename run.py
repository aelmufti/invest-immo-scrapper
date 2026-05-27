"""Point d'entrée unique — démarre l'API+scheduler ET l'UI Streamlit.

Usage :
    python run.py          # API + scheduler + UI (par défaut)
    python run.py --api    # API + scheduler seulement
    python run.py --ui     # UI seulement (la base doit déjà exister)

Implémentation : on lance Streamlit dans un sous-processus, et FastAPI/uvicorn
dans le processus principal (qui détient le scheduler APScheduler). Cela permet
un arrêt propre avec Ctrl+C.
"""

from __future__ import annotations

import argparse
import logging
import signal
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from core.settings import get_settings, setup_logging  # noqa: E402
from data.database import init_db  # noqa: E402

logger = logging.getLogger("run")


def _start_streamlit() -> subprocess.Popen:
    """Démarre Streamlit en sous-processus, sur le port configuré."""
    s = get_settings()
    cmd = [
        sys.executable, "-m", "streamlit", "run", str(ROOT / "app" / "app.py"),
        "--server.port", str(s.streamlit_port),
        "--server.headless", "true",
        "--browser.gatherUsageStats", "false",
    ]
    logger.info("Démarrage Streamlit : %s", " ".join(cmd))
    return subprocess.Popen(cmd, cwd=str(ROOT))


def _run_api_blocking() -> None:
    """Lance uvicorn en mode bloquant (gère le scheduler APScheduler via lifespan)."""
    import uvicorn
    s = get_settings()
    logger.info("Démarrage API+scheduler sur http://%s:%s", s.api_host, s.api_port)
    uvicorn.run(
        "services.api:app",
        host=s.api_host,
        port=s.api_port,
        log_level="info",
        reload=False,
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="invest-immo-scrapper launcher")
    g = parser.add_mutually_exclusive_group()
    g.add_argument("--api", action="store_true", help="API + scheduler seulement")
    g.add_argument("--ui", action="store_true", help="UI Streamlit seulement")
    args = parser.parse_args()

    setup_logging()
    init_db()

    if args.ui:
        proc = _start_streamlit()
        try:
            proc.wait()
        except KeyboardInterrupt:
            proc.terminate()
        return

    if args.api:
        _run_api_blocking()
        return

    # Mode par défaut : les deux
    streamlit_proc = _start_streamlit()

    def _shutdown(signum, frame):  # noqa: ANN001
        logger.info("Signal reçu (%s), arrêt…", signum)
        try:
            streamlit_proc.terminate()
        except Exception:
            pass
        sys.exit(0)

    signal.signal(signal.SIGINT, _shutdown)
    signal.signal(signal.SIGTERM, _shutdown)

    s = get_settings()
    print()
    print("=" * 70)
    print(f"  API      : http://{s.api_host}:{s.api_port}    (docs : /docs)")
    print(f"  UI       : http://{s.api_host}:{s.streamlit_port}")
    print("  Ctrl+C   : arrêt propre")
    print("=" * 70)
    print()

    try:
        _run_api_blocking()  # bloquant, garde le scheduler vivant
    finally:
        try:
            streamlit_proc.terminate()
            streamlit_proc.wait(timeout=5)
        except Exception:
            pass


if __name__ == "__main__":
    main()
