#!/usr/bin/env python3
"""Flask web UI for Sermon Short-form Generator."""

from __future__ import annotations

import json
import logging
import threading
from pathlib import Path

from flask import Flask, jsonify, render_template, request, send_file

from pipeline.models import JobConfig, PipelineResult
from pipeline.orchestrator import get_status, run

app = Flask(__name__)
app.config['MAX_CONTENT_LENGTH'] = 2 * 1024 * 1024 * 1024  # 2GB upload limit

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)

UPLOAD_DIR = Path("./uploads")
UPLOAD_DIR.mkdir(exist_ok=True)

_results: dict[str, PipelineResult] = {}


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/generate", methods=["POST"])
def generate():
    # Handle both JSON and multipart form data (file upload)
    if request.content_type and "multipart" in request.content_type:
        return _generate_from_upload()
    else:
        return _generate_from_json()


def _generate_from_json():
    data = request.json or {}
    url = data.get("url", "").strip()
    if not url:
        return jsonify({"error": "URL is required"}), 400

    config = _build_config(data, youtube_url=url)
    _start_pipeline(config)
    return jsonify({"job_id": config.job_id})


def _generate_from_upload():
    file = request.files.get("file")
    if not file or not file.filename:
        return jsonify({"error": "File is required"}), 400

    # Parse other form fields
    data = json.loads(request.form.get("settings", "{}"))

    # Save uploaded file
    config = _build_config(data)
    config.job_temp_dir.mkdir(parents=True, exist_ok=True)
    save_path = config.job_temp_dir / f"upload_{file.filename}"
    file.save(str(save_path))
    config.local_file = save_path

    _start_pipeline(config)
    return jsonify({"job_id": config.job_id})


def _build_config(data: dict, youtube_url: str = "") -> JobConfig:
    return JobConfig(
        youtube_url=youtube_url,
        num_clips=int(data.get("num_clips", 5)),
        min_duration=int(data.get("min_duration", 30)),
        max_duration=int(data.get("max_duration", 90)),
        subtitle_style=data.get("subtitle_style", "capcut"),
        ai_engine=data.get("ai_engine", "openai"),
        add_music=data.get("add_music", False),
        add_hook=data.get("add_hook", True),
        add_zoom_cuts=data.get("add_zoom_cuts", True),
        add_emoji=data.get("add_emoji", True),
        add_progress_bar=data.get("add_progress_bar", True),
        title_text=data.get("title_text", ""),
        scripture_text=data.get("scripture_text", ""),
        speaker_text=data.get("speaker_text", ""),
        title_font_size=int(data.get("title_font_size", 90)),
        sub_font_size=int(data.get("sub_font_size", 44)),
        bar_ratio=int(data.get("bar_ratio", 40)),
        title_y_pct=int(data.get("title_y_pct", 25)),
        sub_y_pct=int(data.get("sub_y_pct", 65)),
        quotes=data.get("quotes", []),
        language=data.get("language", "auto"),
    )


def _start_pipeline(config: JobConfig):
    def _run():
        try:
            result = run(config)
            _results[config.job_id] = result
        except Exception as e:
            logging.error("Pipeline error: %s", e)

    thread = threading.Thread(target=_run, daemon=True)
    thread.start()


@app.route("/status/<job_id>")
def status(job_id: str):
    st = get_status(job_id)
    if not st:
        return jsonify({"error": "Job not found"}), 404
    return jsonify(st.model_dump())


@app.route("/result/<job_id>")
def result(job_id: str):
    res = _results.get(job_id)
    if not res:
        return jsonify({"error": "Result not found"}), 404

    clips = []
    for clip in res.clips:
        if clip.error is None and clip.final_path:
            clips.append({
                "index": clip.index,
                "filename": clip.final_path.name,
                "download_url": f"/download/{job_id}/{clip.index}",
            })

    return jsonify({
        "job_id": job_id,
        "title": res.source_metadata.title,
        "elapsed": f"{res.elapsed_seconds:.0f}s",
        "clips": clips,
        "total": len(res.clips),
        "successful": len(clips),
    })


@app.route("/download/<job_id>/<int:clip_index>")
def download(job_id: str, clip_index: int):
    res = _results.get(job_id)
    if not res:
        return jsonify({"error": "Result not found"}), 404

    clip = next((c for c in res.clips if c.index == clip_index), None)
    if not clip or not clip.final_path or not clip.final_path.exists():
        return jsonify({"error": "Clip not found"}), 404

    return send_file(
        clip.final_path,
        as_attachment=True,
        download_name=f"short_{clip_index:02d}.mp4",
    )


if __name__ == "__main__":
    print()
    print("  Sermon Shorts Generator - Web UI")
    print("  http://localhost:10000")
    print()
    app.run(host="0.0.0.0", port=10000, debug=True)
