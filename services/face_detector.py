"""Face detection for smart cropping. Supports MediaPipe and OpenCV fallback."""

from __future__ import annotations

import logging
from pathlib import Path

import cv2
import numpy as np

logger = logging.getLogger(__name__)


def detect_face_positions(
    video_path: Path,
    sample_interval: float = 0.5,
    smoothing_factor: float = 0.3,
) -> list[float]:
    """Detect face center-x positions throughout a video.

    Returns a list of normalized x positions (0-1) for each sampled frame.
    Uses exponential moving average for smooth panning.
    Falls back to 0.5 (center) if no faces detected.
    """
    detector = _get_detector()
    if detector is None:
        logger.warning("No face detector available, using center crop")
        return []

    cap = cv2.VideoCapture(str(video_path))
    if not cap.isOpened():
        logger.error("Cannot open video: %s", video_path)
        return []

    fps = cap.get(cv2.CAP_PROP_FPS) or 30
    frame_interval = max(1, int(fps * sample_interval))
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))

    raw_positions: list[float | None] = []
    frame_idx = 0

    while True:
        ret, frame = cap.read()
        if not ret:
            break

        if frame_idx % frame_interval == 0:
            center_x = _detect_face_center(frame, detector)
            raw_positions.append(center_x)

        frame_idx += 1

    cap.release()

    if not raw_positions:
        return []

    positions = _interpolate_nones(raw_positions)
    smoothed = _smooth_ema(positions, smoothing_factor)

    # Expand to per-frame positions
    per_frame = []
    for i in range(total_frames):
        sample_idx = i // frame_interval
        if sample_idx >= len(smoothed):
            sample_idx = len(smoothed) - 1
        per_frame.append(smoothed[sample_idx])

    return per_frame


def _get_detector():
    """Get a face detector — try MediaPipe first, fall back to OpenCV Haar cascade."""
    # Try MediaPipe new API
    try:
        import mediapipe as mp
        from mediapipe.tasks import python as mp_python
        from mediapipe.tasks.python import vision

        # New MediaPipe Tasks API
        base_options = mp_python.BaseOptions(
            model_asset_path=_get_mediapipe_model_path()
        )
        options = vision.FaceDetectorOptions(
            base_options=base_options,
            min_detection_confidence=0.5,
        )
        return ("mediapipe_tasks", vision.FaceDetector.create_from_options(options))
    except Exception:
        pass

    # Try MediaPipe legacy API
    try:
        import mediapipe as mp
        mp_face = mp.solutions.face_detection
        detector = mp_face.FaceDetection(model_selection=1, min_detection_confidence=0.5)
        return ("mediapipe_legacy", detector)
    except Exception:
        pass

    # Fall back to OpenCV Haar cascade
    try:
        cascade_path = cv2.data.haarcascades + "haarcascade_frontalface_default.xml"
        cascade = cv2.CascadeClassifier(cascade_path)
        if not cascade.empty():
            logger.info("Using OpenCV Haar cascade for face detection")
            return ("opencv", cascade)
    except Exception:
        pass

    return None


def _get_mediapipe_model_path() -> str:
    """Try to find or download the MediaPipe face detection model."""
    import os
    model_dir = os.path.expanduser("~/.cache/mediapipe/")
    model_path = os.path.join(model_dir, "blaze_face_short_range.tflite")

    if os.path.exists(model_path):
        return model_path

    # Download the model
    try:
        import urllib.request
        os.makedirs(model_dir, exist_ok=True)
        url = "https://storage.googleapis.com/mediapipe-models/face_detector/blaze_face_short_range/float16/1/blaze_face_short_range.tflite"
        urllib.request.urlretrieve(url, model_path)
        return model_path
    except Exception:
        raise FileNotFoundError("Cannot find or download MediaPipe face detection model")


def _detect_face_center(frame: np.ndarray, detector: tuple) -> float | None:
    """Detect the most prominent face center-x in a frame."""
    kind, det = detector
    h, w = frame.shape[:2]

    if kind == "mediapipe_tasks":
        import mediapipe as mp
        mp_image = mp.Image(image_format=mp.ImageFormat.SRGB, data=cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))
        results = det.detect(mp_image)
        if results.detections:
            best = max(results.detections, key=lambda d: d.bounding_box.width * d.bounding_box.height)
            cx = (best.bounding_box.origin_x + best.bounding_box.width / 2) / w
            return cx
        return None

    elif kind == "mediapipe_legacy":
        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        results = det.process(rgb)
        if results.detections:
            best = max(
                results.detections,
                key=lambda d: d.location_data.relative_bounding_box.width
                * d.location_data.relative_bounding_box.height,
            )
            bbox = best.location_data.relative_bounding_box
            return bbox.xmin + bbox.width / 2
        return None

    elif kind == "opencv":
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        faces = det.detectMultiScale(gray, scaleFactor=1.1, minNeighbors=5, minSize=(60, 60))
        if len(faces) > 0:
            # Largest face
            best = max(faces, key=lambda f: f[2] * f[3])
            x, y, fw, fh = best
            return (x + fw / 2) / w
        return None

    return None


def _interpolate_nones(values: list[float | None]) -> list[float]:
    """Fill None values by linear interpolation from neighbors."""
    result = list(values)
    n = len(result)

    first_valid = next((i for i, v in enumerate(result) if v is not None), None)
    if first_valid is None:
        return [0.5] * n

    for i in range(first_valid):
        result[i] = result[first_valid]

    last_valid_idx = first_valid
    for i in range(first_valid + 1, n):
        if result[i] is not None:
            gap = i - last_valid_idx
            if gap > 1:
                for j in range(1, gap):
                    t = j / gap
                    result[last_valid_idx + j] = (
                        result[last_valid_idx] * (1 - t) + result[i] * t
                    )
            last_valid_idx = i
        elif i == n - 1:
            for j in range(last_valid_idx + 1, n):
                result[j] = result[last_valid_idx]

    return [v if v is not None else 0.5 for v in result]


def _smooth_ema(values: list[float], alpha: float) -> list[float]:
    """Apply exponential moving average."""
    if not values:
        return values
    smoothed = [values[0]]
    for v in values[1:]:
        smoothed.append(alpha * v + (1 - alpha) * smoothed[-1])
    return smoothed
