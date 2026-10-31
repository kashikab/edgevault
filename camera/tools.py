import os, subprocess, shutil

CAPACITY_MB = 100

def storage_dir(cam_id):
    d = f"../storage/{cam_id}"
    os.makedirs(d, exist_ok=True)
    return d

def usage_mb(cam_id):
    d = storage_dir(cam_id)
    total = sum(os.path.getsize(os.path.join(d, f)) for f in os.listdir(d))
    return round(total / 1e6, 2)

def disk_status(cam_id):
    used = usage_mb(cam_id)
    return {"used_mb": used, "free_mb": round(CAPACITY_MB - used, 2),
            "percent": round(100 * used / CAPACITY_MB, 1)}

def evict_clip(cam_id, clip_id):
    path = os.path.join(storage_dir(cam_id), f"{clip_id}.mp4")
    if not os.path.exists(path):
        return {"ok": False, "error": "not found"}
    size = os.path.getsize(path) / 1e6
    os.remove(path)
    return {"ok": True, "freed_mb": round(size, 2)}

def compress_clip(cam_id, clip_id, crf=35, scale_width=480):
    path = os.path.join(storage_dir(cam_id), f"{clip_id}.mp4")
    tmp = path + ".tmp.mp4"
    before = os.path.getsize(path)
    subprocess.run([
        "ffmpeg", "-y", "-i", path,
        "-vf", f"scale={scale_width}:-2", "-c:v", "libx264",
        "-crf", str(crf), "-preset", "veryfast", "-an", tmp
    ], check=True, capture_output=True)
    shutil.move(tmp, path)
    after = os.path.getsize(path)
    return {"ok": True, "before_mb": round(before/1e6, 2),
            "after_mb": round(after/1e6, 2),
            "saved_pct": round(100 * (1 - after/before), 1)}

def fill_disk(cam_id, target_percent=95):
    """For the 'Trigger Disk Full' demo button: writes junk files."""
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
