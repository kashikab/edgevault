import os
import sys
import time
import httpx

sys.path.insert(0, "camera")
import vision
from scorer import score_clip
from tools_24h import archive_clip, expire_archive

# ============================================================
#  CONFIGURATION
# ============================================================
MY_CAM_ID   = "cam1"
PEER_URLS   = ["http://127.0.0.1:8002"]
HUB_URL     = "http://127.0.0.1:9000/event"

# ============================================================
#  BROADCAST LOG
#  Prints to terminal AND sends to Siddharth's hub dashboard
# ============================================================
def broadcast_log(event_type: str, text: str):
    print(f"  [{event_type}] {text}")
    try:
        httpx.post(HUB_URL, json={
            "cam":  MY_CAM_ID,
            "type": event_type.lower(),
            "msg":  text
        }, timeout=1.0)
    except httpx.RequestError:
        pass

# ============================================================
#  MAIN AGENT LOOP
# ============================================================
def process_camera_feed(video_file_path, storage_dir, camera_context):
    import concurrent.futures

    print(f"\n{'='*60}")
    print(f"  Splitting {video_file_path} into clips...")
    os.makedirs(storage_dir, exist_ok=True)
    clips = vision.split_video(video_file_path, storage_dir)
    print(f"  {len(clips)} clip(s) created.\n")

    for clip_path in clips:
        print(f"\n  --- Processing {os.path.basename(clip_path)} ---")

        # ── STEP 0: Archive EVERY clip first (24h safety net) ────
        # This runs before the agent decides anything.
        # Even if the clip is junk it stays in the archive for 24h.
        print("  [ARCHIVE] Saving low-quality copy to 24h archive...")
        archive_result = archive_clip(MY_CAM_ID, clip_path)
        if archive_result.get("ok"):
            print(f"  [ARCHIVE] Saved ({archive_result['size_mb']} MB). "
                  f"Expires in 24h.")
        else:
            print(f"  [ARCHIVE] Warning: {archive_result.get('error')}")

        # Also expire any archive clips older than 24h
        expire_archive(MY_CAM_ID)

        # ── STEP 1: YOLO fast filter ──────────────────────────────
        vision_data = vision.detect_person(clip_path)

        if not vision_data["person_detected"]:
            broadcast_log("PERCEIVE", "No person detected. Junk clip.")
            broadcast_log("EVICT",    "Low score. Deleted from evidence tier.")
            if os.path.exists(clip_path):
                os.remove(clip_path)
            continue

        broadcast_log("PERCEIVE",
            f"Person detected (YOLO conf: {vision_data['yolo_conf']})")

        # ── STEP 2: Gemini scoring (non-blocking with spinner) ────
        print("  [AGENT] Sending frame to Gemini AI (live inference)...")
        b64_frames = vision.get_keyframes_b64(clip_path, n=1, width=320)

        with concurrent.futures.ThreadPoolExecutor() as ex:
            future = ex.submit(score_clip, b64_frames, camera_context)
            try:
                threat = future.result(timeout=15)
            except concurrent.futures.TimeoutError:
                threat = {
                    "score": 0.8 if camera_context.get(
                        "time_of_day") == "night" else 0.1,
                    "reason": "Fallback: Gemini timed out"
                }

        score    = float(threat["score"])
        reason   = threat["reason"]
        disk_pct = camera_context["disk_percent"]
        clip_id  = os.path.basename(clip_path).replace(".mp4", "")

        broadcast_log("REASON",
            f"Score {score} | Disk {disk_pct}% | {reason}")

        # ── STEP 3: Decision routing ──────────────────────────────

        # LOW: junk
        if score < 0.3:
            broadcast_log("EVICT", "Score below 0.3. Deleted from evidence tier.")
            if os.path.exists(clip_path):
                os.remove(clip_path)

        # MEDIUM: cross-check neighbor
        elif 0.3 <= score <= 0.7:
            broadcast_log("PERCEIVE",
                "Score unsure (0.3-0.7). Querying neighbor camera...")

            cleared           = False
            neighbor_confirmed = False

            for peer in PEER_URLS:
                try:
                    resp = httpx.get(
                        f"{peer}/recent_detections", timeout=2.0)

                    if resp.status_code == 200 and len(resp.json()) > 0:
                        detection = resp.json()[0]
                        activity  = detection.get("activity", "")

                        if "non-threatening" in activity \
                                or "phone" in activity:
                            broadcast_log("REASON",
                                f"Neighbor says: '{activity}'. "
                                f"Cleared as false alarm.")
                            broadcast_log("EVICT",
                                "False alarm confirmed. "
                                "Deleted from evidence tier.")
                            if os.path.exists(clip_path):
                                os.remove(clip_path)
                            cleared = True
                        else:
                            broadcast_log("REASON",
                                "Neighbor confirmed threat. "
                                "Upgrading score to 0.8.")
                            score              = 0.8
                            neighbor_confirmed = True
                        break

                    else:
                        broadcast_log("REASON",
                            "Neighbor saw nothing. "
                            "Treating as false alarm.")
                        broadcast_log("EVICT",
                            "No confirmation. "
                            "Deleted from evidence tier.")
                        if os.path.exists(clip_path):
                            os.remove(clip_path)
                        cleared = True
                        break

                except httpx.RequestError:
                    broadcast_log("REASON",
                        "Neighbor offline. Keeping clip as precaution.")
                    score = 0.8
                    break

            if cleared:
                print(f"\n  Waiting 3s before next clip...")
                time.sleep(3)
                continue

        # HIGH: keep or auction
        if score > 0.7:
            if disk_pct <= 80:
                broadcast_log("ALERT",
                    "Critical clip. Disk OK. Kept locally.")

            else:
                clip_size_mb = os.path.getsize(clip_path) / (1024 * 1024)
                broadcast_log("PERCEIVE",
                    f"Disk at {disk_pct}%. "
                    f"Auctioning {round(clip_size_mb, 1)}MB to peers...")

                auction_won = False
                for peer in PEER_URLS:
                    try:
                        print(f"  → Contacting {peer} for bid...")
                        bid_r = httpx.post(
                            f"{peer}/bid",
                            json={"clip_size_mb": clip_size_mb,
                                  "from": MY_CAM_ID},
                            timeout=3.0
                        )

                        if bid_r.status_code == 200 \
                                and bid_r.json().get("can_store"):
                            ask = bid_r.json()["ask_price"]
                            print(f"  ← {peer} bids {ask} credits.")

                            with open(clip_path, "rb") as f:
                                store_r = httpx.post(
                                    f"{peer}/store",
                                    data={"clip_id": clip_id,
                                          "owner":   MY_CAM_ID},
                                    files={"file": (
                                        f"{clip_id}.mp4",
                                        f.read(),
                                        "application/octet-stream"
                                    )},
                                    timeout=10.0
                                )

                            if store_r.status_code == 200:
                                broadcast_log("TRANSFER",
                                    f"Clip stored on {peer}. "
                                    f"Paid {ask} credits. "
                                    f"Local copy deleted.")
                                if os.path.exists(clip_path):
                                    os.remove(clip_path)
                                auction_won = True
                                break
                        else:
                            print(f"  ← {peer} declined (full or offline).")

                    except httpx.RequestError:
                        print(f"  ← {peer} unreachable.")
                        continue

                if not auction_won:
                    broadcast_log("ALERT",
                        "No peers available. "
                        "Keeping critical clip locally.")

        print(f"\n  Waiting 3s before next clip (rate limit buffer)...")
        time.sleep(3)

# ============================================================
#  SCENARIOS
# ============================================================
SCENARIOS = {
    "1": {
        "label": "Empty Hallway — expect: deleted instantly",
        "video": "videos/empty_hallway.mp4",
        "storage": "storage/cam1",
        "context": {
            "camera_name": "cam1_hallway",
            "time_of_day": "day",
            "is_restricted": False,
            "disk_percent": 40
        }
    },
    "2": {
        "label": "Normal Person — expect: low score, deleted",
        "video": "videos/normal.mp4",
        "storage": "storage/cam1",
        "context": {
            "camera_name": "cam1_hallway",
            "time_of_day": "day",
            "is_restricted": False,
            "disk_percent": 40
        }
    },
    "3": {
        "label": "Hallway Person — expect: unsure, cross-checks neighbor",
        "video": "videos/hallway.mp4",
        "storage": "storage/cam1",
        "context": {
            "camera_name": "cam1_hallway",
            "time_of_day": "day",
            "is_restricted": True,
            "disk_percent": 50
        }
    },
    "4": {
        "label": "Seemingly Suspicious — expect: cam2 clears as phone user",
        "video": "videos/seemingly_suspicious.mp4",
        "storage": "storage/cam1",
        "context": {
            "camera_name": "cam1_entrance",
            "time_of_day": "day",
            "is_restricted": True,
            "disk_percent": 55
        }
    },
    "5": {
        "label": "Suspicious Activity — expect: high score, auctions to peer",
        "video": "videos/suspicious.mp4",
        "storage": "storage/cam1",
        "context": {
            "camera_name": "cam1_restricted_zone",
            "time_of_day": "night",
            "is_restricted": True,
            "disk_percent": 92
        }
    },
}

def print_menu():
    print("\n" + "="*60)
    print("  EDGEVAULT AGENT — LIVE DEMO")
    print("="*60)
    for k, s in SCENARIOS.items():
        print(f"  {k}  {s['label']}")
    print("  6  Run all scenarios back to back")
    print("  0  Exit")
    print("="*60)
    print("  NOTE: Gemini is called live. Spinner shows while")
    print("        AI is thinking. Fallback fires if API is slow.")
    print("="*60)

# ============================================================
#  ENTRY POINT
# ============================================================
if __name__ == "__main__":
    import shutil

    while True:
        print_menu()
        choice = input("\n  Enter number: ").strip()

        if choice == "0":
            print("  Exiting.")
            break

        elif choice in SCENARIOS:
            # Wipe old clips so each run starts fresh
            if os.path.exists("storage/cam1"):
                for f in os.listdir("storage/cam1"):
                    fp = os.path.join("storage/cam1", f)
                    if os.path.isfile(fp) and f.endswith(".mp4"):
                        os.remove(fp)

            s = SCENARIOS[choice]
            print(f"\n{'='*60}")
            print(f"  {s['label']}")
            print(f"{'='*60}")
            process_camera_feed(s["video"], s["storage"], s["context"])
            input("\n  Press Enter to return to menu...")

        elif choice == "6":
            if os.path.exists("storage/cam1"):
                shutil.rmtree("storage/cam1")
            print("\n  Running all scenarios back to back...\n")
            for k in ["1", "2", "3", "4", "5"]:
                s = SCENARIOS[k]
                print(f"\n{'='*60}")
                print(f"  {s['label']}")
                print(f"{'='*60}")
                process_camera_feed(
                    s["video"], s["storage"], s["context"])
                print("  Pausing 5s before next scenario...")
                time.sleep(5)
            print(f"\n{'='*60}")
            print("  ALL SCENARIOS COMPLETE")
            print(f"{'='*60}")
            input("\n  Press Enter to return to menu...")

        else:
            print("  Invalid choice. Try again.")
