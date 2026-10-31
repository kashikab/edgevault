import os
import time
import httpx
import vision
from scorer import score_clip

# --- Network Configuration ---
MY_CAM_ID = "cam1"
# For the demo, we assume Dhyan's server is running as Camera 2 on port 8002
PEER_URLS = ["http://127.0.0.1:8002"] 

def process_camera_feed(video_file_path, storage_dir, camera_context):
    print(f"--- Splitting {video_file_path} into clips ---")
    clips = vision.split_video(video_file_path, storage_dir)

    for clip_path in clips:
        print(f"\n============================================")
        print(f"[VISION] Processing {clip_path}...")
        
        vision_data = vision.detect_person(clip_path)

        if not vision_data["person_detected"]:
            print("[VISION] Empty frame. Evicting clip immediately to save space.")
            if os.path.exists(clip_path):
                os.remove(clip_path)
            continue

        print(f"[VISION] Person detected! (YOLO Conf: {vision_data['yolo_conf']})")
        print("[AGENT] Extracting keyframes and querying Gemini...")
        
        b64_frames = vision.get_keyframes_b64(clip_path)
        threat_assessment = score_clip(b64_frames, camera_context)
        
        print(f"[AGENT] Gemini Score: {threat_assessment['score']}")
        print(f"[AGENT] Reasoning: {threat_assessment['reason']}")
        
        score = float(threat_assessment['score'])
        clip_id = os.path.basename(clip_path).replace(".mp4", "")
        
        # ---------------------------------------------------------
        # THE INTEGRATION: DECISION ROUTING & P2P EXECUTION
        # ---------------------------------------------------------
        if score < 0.3:
            print("[DECISION] Score below 0.3. Junk footage. Deleting.")
            if os.path.exists(clip_path):
                os.remove(clip_path)
            
        elif 0.3 <= score <= 0.7:
            print("[DECISION] Score 0.3-0.7. Unsure. Querying neighbors...")
            neighbor_saw_someone = False
            
            for peer in PEER_URLS:
                try:
                    resp = httpx.get(f"{peer}/recent_detections", timeout=2.0)
                    if resp.status_code == 200 and len(resp.json()) > 0:
                        neighbor_saw_someone = True
                        break
                except httpx.RequestError:
                    continue
            
            if neighbor_saw_someone:
                print("[NETWORK] A neighbor ALSO saw a person! Upgrading to CRITICAL.")
                score = 0.8 # Upgrade threat
            else:
                print("[NETWORK] Neighbors saw nothing. False alarm. Deleting.")
                if os.path.exists(clip_path):
                    os.remove(clip_path)
                continue # Skip the rest of the loop

        if score > 0.7:
            print("[DECISION] Score above 0.7. CRITICAL.")
            if camera_context['disk_percent'] > 80:
                clip_size_mb = os.path.getsize(clip_path) / (1024 * 1024)
                print(f"[DECISION] Disk at {camera_context['disk_percent']}%. Auctioning {round(clip_size_mb, 2)}MB...")
                
                auction_won = False
                for peer in PEER_URLS:
                    try:
                        # 1. Ask for a bid
                        bid_resp = httpx.post(f"{peer}/bid", json={"clip_size_mb": clip_size_mb, "from": MY_CAM_ID})
                        if bid_resp.status_code == 200 and bid_resp.json().get("can_store"):
                            ask_price = bid_resp.json()["ask_price"]
                            print(f"[NETWORK] Bid accepted by {peer} for {ask_price} credits. Transferring...")
                            
                            # 2. Transfer the file
                            with open(clip_path, "rb") as f:
                                files = {"file": (f"{clip_id}.mp4", f.read(), "application/octet-stream")}
                                data = {"clip_id": clip_id, "owner": MY_CAM_ID}
                                store_resp = httpx.post(f"{peer}/store", data=data, files=files)
                                
                            if store_resp.status_code == 200:
                                print("[NETWORK] Transfer complete! Deleting local copy.")
                                os.remove(clip_path)
                                auction_won = True
                                break
                    except httpx.RequestError as e:
                        print(f"[NETWORK] Failed to contact peer {peer}: {e}")
                
                if not auction_won:
                    print("[NETWORK] Auction failed (peers full/offline). Keeping local copy.")
            else:
                print("[DECISION] Keeping clip on local disk.")

        print("\nWaiting 5 seconds to respect API rate limits...")
        time.sleep(5)

if __name__ == "__main__":
    sample_video = "sample_videos/cam1_intruder.mp4"
    if not os.path.exists(sample_video):
        print(f"ERROR: Cannot find {sample_video}.")
    else:
        cam1_context = {
            "camera_name": "cam1_hallway",
            "time_of_day": "night",
            "is_restricted": True,
            "disk_percent": 85 
        }
        process_camera_feed(sample_video, "storage/cam1", cam1_context)