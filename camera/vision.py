import os, glob, subprocess, base64
import cv2
from ultralytics import YOLO

model = YOLO("yolov8n.pt")

def split_video(video_path, out_dir, clip_seconds=10):
    """Cut a video into 10s clips using ffmpeg."""
    os.makedirs(out_dir, exist_ok=True)
    pattern = os.path.join(out_dir, "clip_%03d.mp4")
    subprocess.run([
        "ffmpeg", "-y", "-i", video_path,
        "-c:v", "libx264", "-preset", "veryfast", "-an",
        "-force_key_frames", f"expr:gte(t,n_forced*{clip_seconds})",
        "-f", "segment", "-segment_time", str(clip_seconds),
        "-reset_timestamps", "1", pattern
    ], check=True, capture_output=True)
    return sorted(glob.glob(os.path.join(out_dir, "clip_*.mp4")))

def detect_person(clip_path, conf=0.4):
    """Run YOLO on 1 frame per second. Returns a dict for the agent."""
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

    return {
        "clip_id": os.path.splitext(os.path.basename(clip_path))[0],
        "clip_path": clip_path,
        "person_detected": max_count > 0,
        "person_count": max_count,
        "yolo_conf": round(max_conf, 2),
        "frames_checked": checked,
    }

def get_keyframes_b64(clip_path, n=3, width=640):
    """Grab n evenly spaced frames as base64 JPEGs, for Kashika to send to Gemini."""
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

if __name__ == "__main__":
    clips = split_video("videos/empty_hallway.mp4", "storage/cam1")
    for c in clips:
        print(detect_person(c))