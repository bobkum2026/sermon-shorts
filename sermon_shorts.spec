# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec file for Sermon Shorts Generator."""

import os
import sys

block_cipher = None
base_dir = os.path.abspath('.')

# Platform-specific ffmpeg
if sys.platform == 'win32':
    ffmpeg_data = [('ffmpeg/ffmpeg.exe', 'ffmpeg'), ('ffmpeg/ffprobe.exe', 'ffmpeg')]
elif sys.platform == 'darwin':
    import shutil
    ffmpeg_path = shutil.which('ffmpeg')
    ffprobe_path = shutil.which('ffprobe')
    ffmpeg_data = []
    if ffmpeg_path: ffmpeg_data.append((ffmpeg_path, 'ffmpeg'))
    if ffprobe_path: ffmpeg_data.append((ffprobe_path, 'ffmpeg'))
else:
    ffmpeg_data = []

a = Analysis(
    ['launcher.py'],
    pathex=[base_dir],
    binaries=ffmpeg_data,
    datas=[
        ('templates', 'templates'),
        ('static', 'static'),
        ('assets/fonts', 'assets/fonts'),
        ('config.yaml', '.'),
        ('pipeline', 'pipeline'),
        ('services', 'services'),
        ('web.py', '.'),
    ],
    hiddenimports=[
        'flask', 'pydantic', 'yaml', 'dotenv', 'openai',
        'google.generativeai', 'yt_dlp', 'PIL', 'cv2', 'mediapipe',
        'pipeline.models', 'pipeline.orchestrator', 'pipeline.downloader',
        'pipeline.transcriber', 'pipeline.selector', 'pipeline.cropper',
        'pipeline.subtitler', 'pipeline.composer',
        'services.openai_client', 'services.gemini_client',
        'services.ffmpeg_wrapper', 'services.face_detector',
    ],
    excludes=['tkinter', 'matplotlib', 'scipy', 'notebook', 'pytest'],
    cipher=block_cipher,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz, a.scripts, [],
    exclude_binaries=True,
    name='SermonShorts',
    console=True,
    icon=None,
)

coll = COLLECT(
    exe, a.binaries, a.zipfiles, a.datas,
    name='SermonShorts',
)
