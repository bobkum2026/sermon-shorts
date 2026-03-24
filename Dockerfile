FROM python:3.12-slim

# System dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    fonts-noto-cjk \
    libgl1 \
    libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# App files
COPY pipeline/ pipeline/
COPY services/ services/
COPY templates/ templates/
COPY static/ static/
COPY assets/ assets/
COPY config.yaml .
COPY web.py .
COPY launcher.py .

# Directories
RUN mkdir -p output temp assets/fonts assets/music

# Download Korean font (backup if system font missing)
RUN python -c "\
import urllib.request, re; \
css = urllib.request.urlopen(urllib.request.Request( \
    'https://fonts.googleapis.com/css2?family=Noto+Sans+KR:wght@700', \
    headers={'User-Agent':'Mozilla/5.0'})).read().decode(); \
url = re.search(r'src: url\((https://[^)]+\.ttf)\)', css); \
url and urllib.request.urlretrieve(url.group(1), 'assets/fonts/NotoSansKR-Bold.ttf') \
" || true

EXPOSE 10000

CMD ["python", "launcher.py"]
