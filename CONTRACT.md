# EdgeVault System Contract

## 1. Decision Thresholds
All cameras will use these exact ranges to decide what to do with a clip:
- **Score below 0.3**: Junk footage. Delete or compress it immediately.[cite: 11]
- **Score 0.3 to 0.7**: Unsure. Ask a neighbor camera. If still unsure, compress the clip by 50% and alert the guard.[cite: 11]
- **Score above 0.7**: Critical event. Keep the clip. If the local disk is above 80% full, rent space from a peer.[cite: 11]

## 2. Message Shapes (JSON)
When pieces of code talk to each other over the network or between Python files, they must send data in exactly this format:
- **Detection Result**: `{"clip_id": "c12", "score": 0.91, "reason": "person at restricted door"}`[cite: 11]
- **Neighbor Question (GET /recent_detections)**: Returns `[{"time": "14:02:10", "person_seen": true}]`[cite: 11]
- **Bid Request**: `{"clip_size_mb": 20, "from": "cam1"}`[cite: 11]
- **Bid Reply**: `{"ask_price": 1.2, "free_mb": 85}`[cite: 11]

## 3. Function Names & Inputs
If you are writing the Python tools that the Gemini agent will call, you must name them exactly this with these exact arguments:
- `evict_clip(clip_id)`[cite: 11]
- `compress_clip(clip_id)`[cite: 11]
- `auction_remote_storage(clip_id)`[cite: 11]
