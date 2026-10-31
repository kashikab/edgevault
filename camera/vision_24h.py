import os, glob, time, subprocess, base64
from collections import deque
from datetime import datetime

import cv2
from ultralytics import YOLO

import tools   # same folder; used to archive every clip

model = YOLO("yolov8n.pt")

BASE = os.path.dirname(os.path.abspath(__file__))

# Rolling memory for GET /recent_detections (contract shape)
_recent = deque(maxlen=50)


def recent_detections():
    """Exactly the contract shape: [{"time": "14:02:10", "person_seen": true}]"""
    return list(_recent)


def split_video(video_path, out_dir, clip_seconds=10):
    """Cut a video into 10s clips using ffmpeg."""
    if not os.path.exists(video_path):
        raise FileNotFoundError(f"Video not found: {video_path}")
    os.makedirs(out_dir, exist_ok=True)
    stem = os.path.splitext(os.path.basename(video_path))[0]   # "hallway"
    pattern = os.path.join(out_dir, f"{stem}_%03d.mp4")        # hallway_000.mp4
    try:
        subprocess.run([
            "ffmpeg", "-y", "-i", video_path,
            "-c:v", "libx264", "-preset", "veryfast", "-an",
            "-force_key_frames", f"expr:gte(t,n_forced*{clip_seconds})",
            "-f", "segment", "-segment_time", str(clip_seconds),
            "-reset_timestamps", "1", pattern
        ], check=True, capture_output=True)
    except subprocess.CalledProcessError as e:
        print(e.stderr.decode()[-500:])    # shows the real ffmpeg error
        raise
    return sorted(glob.glob(os.path.join(out_dir, f"{stem}_*.mp4")))


def detect_person(clip_path, conf=0.4):
    """Run YOLO on 1 frame per second. Returns a dict for the agent (YOLO pre-filter)."""
    cap = cv2.VideoCapture(clip_path)
    fps = int(cap.get(cv2.CAP_PROP_FPS) or 30)
    total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    max_conf, max_count, checked = 0.0, 0, 0

    for i in range(0, total, fps):          # step = 1 second
        cap.set(cv2.CAP_PROP_POS_FRAMES, i)
        ok, frame = cap.read()
        if not ok:
            break
        result = model(frame, classes=[0], conf=conf, verbose=False)[0]  # class 0 = person
        checked += 1
        max_count = max(max_count, len(result.boxes))
        for b in result.boxes:
            max_conf = max(max_conf, float(b.conf))
    cap.release()

    result_dict = {
        "clip_id": os.path.splitext(os.path.basename(clip_path))[0],
        "clip_path": clip_path,
        "person_detected": max_count > 0,
        "person_count": max_count,
        "yolo_conf": round(max_conf, 2),
        "frames_checked": checked,
    }
    _recent.append({"time": datetime.now().strftime("%H:%M:%S"),
                    "person_seen": result_dict["person_detected"]})
    return result_dict


def get_keyframes_b64(clip_path, n=3, width=640):
    """Grab n evenly spaced frames as base64 JPEGs, for Gemini."""
    cap = cv2.VideoCapture(clip_path)
    total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    frames = []
    for k in range(n):
        cap.set(cv2.CAP_PROP_POS_FRAMES, int(total * (k + 0.5) / n))
        ok, frame = cap.read()
        if ok:
            h, w = frame.shape[:2]
            frame = cv2.resize(frame, (width, int(h * width / w)))
            _, buf = cv2.imencode(".jpg", frame)
            frames.append(base64.b64encode(buf).decode())
    cap.release()
    return frames


def stream_clips(clips, cam_id=None, delay=10):
    """Simulated live feed. For each clip: archive it (24h backup), expire old
    archive clips, then yield the YOLO result. Use delay=2-3 for fast testing."""
    cam_id = cam_id or tools.CAM_ID
    for c in clips:
        tools.archive_clip(cam_id, c)      # 1. every clip gets a cheap 24h copy
        tools.expire_archive(cam_id)       # 2. drop anything older than retention
        yield detect_person(c)             # 3. YOLO result goes on to the agent
        time.sleep(delay)


if __name__ == "__main__":
    video = os.path.join(BASE, "..", "videos", "hallway.mp4")
    out = os.path.join(BASE, "..", "storage", "cam1")
    clips = split_video(video, out)
    for c in clips:
        print(detect_person(c))
    print(recent_detections())
