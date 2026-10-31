import os
import glob
import time
import shutil
import subprocess
from datetime import datetime

# ---------------- Config ----------------
CAPACITY_MB = 100                 # fake evidence disk (small on purpose, for demos)
ARCHIVE_CAPACITY_MB = 300         # separate budget for the 24h archive
ARCHIVE_RETENTION_HOURS = float(os.environ.get("ARCHIVE_HOURS", 24))  # demo: set ARCHIVE_HOURS=0.05

# Contract thresholds (single source of truth for the team)
SCORE_JUNK = 0.3                  # below this: junk
SCORE_CRITICAL = 0.7              # above this: critical
DISK_RENT_PERCENT = 80            # above this (and critical): rent space from a peer

BASE = os.path.dirname(os.path.abspath(__file__))
STORAGE_ROOT = os.path.join(BASE, "..", "storage")

CAM_ID = os.environ.get("CAM_ID", "cam1")


def set_camera(cam_id):
    """main.py calls this once at startup: set_camera(args.id)"""
    global CAM_ID
    CAM_ID = cam_id


# ---------------- Paths and status ----------------
def storage_dir(cam_id):
    d = os.path.join(STORAGE_ROOT, cam_id)
    os.makedirs(d, exist_ok=True)
    return d


def clip_path(cam_id, clip_id):
    """clip_id like 'hallway_000' -> storage/cam1/hallway_000.mp4"""
    return os.path.join(storage_dir(cam_id), f"{clip_id}.mp4")


def usage_mb(cam_id):
    """Evidence tier only. Ignores subfolders, so the archive is NOT counted."""
    d = storage_dir(cam_id)
    total = sum(os.path.getsize(os.path.join(d, f))
                for f in os.listdir(d) if os.path.isfile(os.path.join(d, f)))
    return round(total / 1e6, 2)


def disk_status(cam_id=None):
    cam_id = cam_id or CAM_ID
    used = usage_mb(cam_id)
    return {"used_mb": used, "free_mb": round(CAPACITY_MB - used, 2),
            "percent": round(100 * used / CAPACITY_MB, 1)}


def list_clips(cam_id=None):
    """Real evidence clips (ignores filler files and the archive)."""
    cam_id = cam_id or CAM_ID
    out = []
    for p in sorted(glob.glob(os.path.join(storage_dir(cam_id), "*.mp4"))):
        out.append({"clip_id": os.path.splitext(os.path.basename(p))[0],
                    "size_mb": round(os.path.getsize(p) / 1e6, 2)})
    return out


# ---------------- Evidence tier actions ----------------
def evict_clip_on(cam_id, clip_id):
    path = clip_path(cam_id, clip_id)
    if not os.path.exists(path):
        return {"ok": False, "error": f"{clip_id} not found"}
    size = os.path.getsize(path) / 1e6
    os.remove(path)
    meta = path.replace(".mp4", ".json")
    if os.path.exists(meta):
        os.remove(meta)
    return {"ok": True, "clip_id": clip_id, "freed_mb": round(size, 2)}


def _duration_s(path):
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=nw=1:nk=1", path],
        capture_output=True, text=True, check=True)
    return float(out.stdout.strip())


def compress_clip_on(cam_id, clip_id, target_ratio=0.5):
    """Re-encode so the file is about target_ratio of its size (0.5 = 50% smaller)."""
    path = clip_path(cam_id, clip_id)
    if not os.path.exists(path):
        return {"ok": False, "error": f"{clip_id} not found"}

    tmp = path + ".tmp"
    before = os.path.getsize(path)
    try:
        kbps = max(50, int(before * target_ratio * 8 / _duration_s(path) / 1000))
        subprocess.run([
            "ffmpeg", "-y", "-i", path,
            "-c:v", "libx264", "-b:v", f"{kbps}k",
            "-maxrate", f"{kbps}k", "-bufsize", f"{2 * kbps}k",
            "-preset", "veryfast", "-an", "-f", "mp4", tmp
        ], check=True, capture_output=True)
    except subprocess.CalledProcessError as e:
        if os.path.exists(tmp):
            os.remove(tmp)
        return {"ok": False, "error": "ffmpeg failed", "details": e.stderr.decode()[-200:]}

    shutil.move(tmp, path)
    after = os.path.getsize(path)
    return {"ok": True, "clip_id": clip_id,
            "before_mb": round(before / 1e6, 2), "after_mb": round(after / 1e6, 2),
            "saved_pct": round(100 * (1 - after / before), 1)}


# ---------------- Contract-compliant names (what Gemini calls) ----------------
def evict_clip(clip_id):
    return evict_clip_on(CAM_ID, clip_id)


def compress_clip(clip_id):
    return compress_clip_on(CAM_ID, clip_id)

# auction_remote_storage(clip_id) is Dhyan/Kashika's (network layer)


# ---------------- 24h archive (every clip, low quality, rolling) ----------------
def archive_dir(cam_id):
    d = os.path.join(storage_dir(cam_id), "archive")
    os.makedirs(d, exist_ok=True)
    return d


def archive_clip(cam_id, src_path, crf=36, scale_width=426, fps=10):
    """Save a low-quality copy of EVERY clip. Called before the agent decides anything."""
    dst = os.path.join(archive_dir(cam_id), os.path.basename(src_path))
    try:
        subprocess.run([
            "ffmpeg", "-y", "-i", src_path,
            "-vf", f"fps={fps},scale={scale_width}:-2",
            "-c:v", "libx264", "-crf", str(crf),
            "-preset", "veryfast", "-an", dst
        ], check=True, capture_output=True)
    except subprocess.CalledProcessError as e:
        return {"ok": False, "error": "ffmpeg failed", "details": e.stderr.decode()[-200:]}
    return {"ok": True, "clip_id": os.path.splitext(os.path.basename(dst))[0],
            "size_mb": round(os.path.getsize(dst) / 1e6, 3)}


def list_archive(cam_id=None):
    cam_id = cam_id or CAM_ID
    out = []
    for p in sorted(glob.glob(os.path.join(archive_dir(cam_id), "*.mp4")), key=os.path.getmtime):
        out.append({"clip_id": os.path.splitext(os.path.basename(p))[0],
                    "size_mb": round(os.path.getsize(p) / 1e6, 3),
                    "recorded_at": datetime.fromtimestamp(os.path.getmtime(p)).isoformat(timespec="seconds")})
    return out


def archive_status(cam_id=None):
    clips = list_archive(cam_id)
    return {"archive_clips": len(clips),
            "archive_mb": round(sum(c["size_mb"] for c in clips), 2),
            "archive_capacity_mb": ARCHIVE_CAPACITY_MB}


def expire_archive(cam_id=None, hours=None):
    """Delete archive clips older than `hours`, then enforce the size cap (oldest first)."""
    cam_id = cam_id or CAM_ID
    hours = ARCHIVE_RETENTION_HOURS if hours is None else hours
    files = sorted(glob.glob(os.path.join(archive_dir(cam_id), "*.mp4")), key=os.path.getmtime)
    cutoff = time.time() - hours * 3600
    expired = 0
    for p in list(files):
        if os.path.getmtime(p) < cutoff:
            os.remove(p)
            files.remove(p)
            expired += 1
    while files and sum(os.path.getsize(p) for p in files) / 1e6 > ARCHIVE_CAPACITY_MB:
        os.remove(files.pop(0))
        expired += 1
    return {"expired": expired, **archive_status(cam_id)}


# ---------------- Demo helpers ----------------
def fill_disk(cam_id=None, target_percent=95):
    """'Trigger Disk Full' button: writes junk files into the evidence tier."""
    cam_id = cam_id or CAM_ID
    d = storage_dir(cam_id)
    need_mb = CAPACITY_MB * target_percent / 100 - usage_mb(cam_id)
    i = 0
    while need_mb > 0:
        chunk = min(10, need_mb)
        with open(os.path.join(d, f"filler_{i}.bin"), "wb") as f:
            f.write(os.urandom(int(chunk * 1e6)))
        need_mb -= chunk
        i += 1
    return disk_status(cam_id)


def clear_filler(cam_id=None):
    """Reset after a demo."""
    cam_id = cam_id or CAM_ID
    removed = 0
    for p in glob.glob(os.path.join(storage_dir(cam_id), "filler_*.bin")):
        os.remove(p)
        removed += 1
    return {"removed": removed, **disk_status(cam_id)}


if __name__ == "__main__":
    # Non-destructive checks. Evict/compress change real files, so test those on a backup.
    print("Status:", disk_status("cam1"))
    print("Clips:", list_clips("cam1"))
    for c in list_clips("cam1"):
        print("Archive:", archive_clip("cam1", clip_path("cam1", c["clip_id"])))
    print("Archive status:", archive_status("cam1"))
    print("Disk after archiving (should be unchanged):", disk_status("cam1"))
    print("Fill:", fill_disk("cam1"))
    print("Clear:", clear_filler("cam1"))
