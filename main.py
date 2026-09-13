"""
AI Book-to-Game Engine
Entry point — starts the local web server and optionally opens the browser.
"""
import json
import os
import sys
import webbrowser
from pathlib import Path


def load_config() -> dict:
    data_dir_env = os.environ.get("AITEXTGAME_DATA_DIR")
    base_dir = Path(__file__).parent
    
    if data_dir_env:
        config_path = Path(data_dir_env) / "config.json"
        if not config_path.exists():
            import shutil
            config_path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(base_dir / "config.json", config_path)
    else:
        config_path = base_dir / "config.json"
        
    if not config_path.exists():
        print("ERROR: config.json not found.")
        sys.exit(1)
    with open(config_path, "r", encoding="utf-8") as f:
        return json.load(f)


def ensure_data_dirs(config: dict) -> None:
    """Create data subdirectories if they don't exist."""
    data_dir_env = os.environ.get("AITEXTGAME_DATA_DIR")
    base = Path(data_dir_env) if data_dir_env else Path(config["app"]["data_dir"])
    for subdir in ["books", "games", "images", "saves"]:
        (base / subdir).mkdir(parents=True, exist_ok=True)


def main() -> None:
    config = load_config()
    ensure_data_dirs(config)

    host = config["app"]["host"]
    port = config["app"]["port"]
    open_browser = config["app"].get("open_browser", True)

    print(f"\n  AI Book-to-Game Engine")
    print(f"  -------------------------------------")
    print(f"  Running at: http://{host}:{port}")
    print(f"  Press Ctrl+C to stop\n")

    if open_browser and not os.environ.get("NO_BROWSER"):
        import threading
        def _open():
            import time
            time.sleep(1.2)
            webbrowser.open(f"http://{host}:{port}")
        threading.Thread(target=_open, daemon=True).start()

    # Import here so config is loaded first
    import uvicorn
    import ui.app as ui_app
    uvicorn.run(
        ui_app.app,
        host=host,
        port=port,
        reload=False,
        log_level="warning",
    )


if __name__ == "__main__":
    main()
