#!/bin/bash
set -e

echo "=== Sermon Shorts Generator Setup ==="

# System dependencies
echo "[1/3] Installing system dependencies..."
sudo apt update -qq
sudo apt install -y -qq ffmpeg

# Python virtual environment
echo "[2/3] Creating Python virtual environment..."
python3 -m venv .venv
source .venv/bin/activate

# Python packages
echo "[3/3] Installing Python packages..."
pip install --upgrade pip
pip install -r requirements.txt

# Create directories
mkdir -p output temp assets/fonts assets/music

# .env setup
if [ ! -f .env ]; then
    cp .env.example .env
    echo ""
    echo ">>> .env 파일이 생성되었습니다."
    echo ">>> OPENAI_API_KEY (Whisper STT용)와 GEMINI_API_KEY (하이라이트 분석용)를 입력해주세요."
fi

echo ""
echo "=== Setup complete! ==="
echo ""
echo "사용법:"
echo "  source .venv/bin/activate"
echo "  python cli.py 'https://youtube.com/watch?v=...'"
echo ""
echo "웹 UI:"
echo "  python web.py    # http://localhost:5000"
echo ""
