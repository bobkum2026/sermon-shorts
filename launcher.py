#!/usr/bin/env python3
"""Sermon Shorts Generator - Desktop Launcher.

Opens the web UI in the default browser automatically.
Used as the PyInstaller entry point for the .exe build.
"""

import logging
import os
import sys
import threading
import time
import webbrowser
from pathlib import Path

# Fix paths for PyInstaller bundled app
if getattr(sys, 'frozen', False):
    # Running as compiled exe
    BASE_DIR = Path(sys._MEIPASS)
    os.chdir(BASE_DIR)
    # Add ffmpeg to PATH
    ffmpeg_dir = BASE_DIR / "ffmpeg"
    if ffmpeg_dir.exists():
        os.environ["PATH"] = str(ffmpeg_dir) + os.pathsep + os.environ.get("PATH", "")
    # Set font path
    font_dir = BASE_DIR / "assets" / "fonts"
    if font_dir.exists():
        os.environ["FONTCONFIG_PATH"] = str(font_dir)
else:
    BASE_DIR = Path(__file__).parent

# Load .env
from dotenv import load_dotenv
env_path = BASE_DIR / ".env"
if not env_path.exists():
    # Check next to the exe (outside the bundle)
    exe_dir = Path(sys.executable).parent if getattr(sys, 'frozen', False) else BASE_DIR
    env_path = exe_dir / ".env"
load_dotenv(env_path)

PORT = 10000

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)


def open_browser():
    """Open browser after a short delay."""
    time.sleep(2)
    webbrowser.open(f"http://localhost:{PORT}")


def main():
    # Check API keys
    if not os.getenv("OPENAI_API_KEY"):
        print()
        print("  [!] OPENAI_API_KEY not found!")
        print(f"  Please create a .env file next to the executable with:")
        print(f"    OPENAI_API_KEY=sk-...")
        print(f"    GEMINI_API_KEY=...  (optional)")
        print()
        input("  Press Enter to exit...")
        sys.exit(1)

    print()
    print("  ╔══════════════════════════════════════╗")
    print("  ║   Sermon Shorts Generator            ║")
    print(f"  ║   http://localhost:{PORT}             ║")
    print("  ║   (Browser will open automatically)  ║")
    print("  ║   Press Ctrl+C to quit               ║")
    print("  ╚══════════════════════════════════════╝")
    print()

    # Open browser in background
    threading.Thread(target=open_browser, daemon=True).start()

    # Start Flask (0.0.0.0 for Docker access)
    from web import app
    app.run(host="0.0.0.0", port=PORT, debug=False)


if __name__ == "__main__":
    main()
