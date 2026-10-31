import os
import time
import logging
import hashlib
import argparse
import secrets
import httpx
import uvicorn
from typing import List, Dict, Any
from fastapi import FastAPI, File, Form, UploadFile, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
import datetime


logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

class BidRequest(BaseModel):
    clip_size_mb: float
    from_cam: str = Field(alias="from")

class ProveRequest(BaseModel):
    clip_id: str
    owner: str
    nonce: str

def get_used_mb(storage_dir: str) -> float:
    """Calculates total used space in the storage directory in MB."""
    total_bytes = 0
    for root, _, files in os.walk(storage_dir):
        for file in files:
            total_bytes += os.path.getsize(os.path.join(root, file))
    return total_bytes / (1024 * 1024)

def add_detection(app: FastAPI, clip_id: str, score: float, reason: str) -> None:
    """Appends a new threat detection to the in-memory list."""
    app.state.detections.append({
        "clip_id": clip_id,
        "score": score,
        "reason": reason,
        "timestamp": time.time()
    })

def create_app(cam_id: str, storage_dir: str, capacity_mb: float = 100.0) -> FastAPI:
    """Factory function to create and configure the EdgeVault P2P FastAPI node."""
    os.makedirs(storage_dir, exist_ok=True)

    app = FastAPI(title=f"EdgeVault Node - {cam_id}")
    app.state.detections = []
    
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.get("/status")
    def get_status(request: Request) -> Dict[str, Any]:
        """Returns the current storage utilization and capacity."""
        logger.info(f"GET /status called by {request.client.host}")
        used_mb = get_used_mb(storage_dir)
        return {
            "cam_id": cam_id,
            "used_mb": round(used_mb, 2),
            "free_mb": round(max(0.0, capacity_mb - used_mb), 2),
            "capacity_mb": capacity_mb
        }

    @app.post("/bid")
    def place_bid(bid: BidRequest, request: Request) -> Dict[str, Any]:
        """Evaluates available capacity and prices storage dynamically."""
        logger.info(f"POST /bid called for {bid.clip_size_mb}MB from {bid.from_cam}")
        used_mb = get_used_mb(storage_dir)
        free_mb = max(0.0, capacity_mb - used_mb)
        
        can_store = (free_mb - bid.clip_size_mb) >= 5.0
        ask_price = 1.0 + 4.0 * (used_mb / capacity_mb)
        
        return {
            "cam_id": cam_id,
            "ask_price": round(ask_price, 2),
            "free_mb": round(free_mb, 2),
            "can_store": can_store
        }

    @app.post("/store")
    async def store_clip(
        request: Request,
        clip_id: str = Form(...),
        owner: str = Form(...),
        file: UploadFile = File(...)
    ) -> Dict[str, Any]:
        """Receives an encrypted blob and saves it if capacity permits."""
        logger.info(f"POST /store called by {owner} for clip {clip_id}")
        
        contents = await file.read()
        file_size_mb = len(contents) / (1024 * 1024)
        
        used_mb = get_used_mb(storage_dir)
        if capacity_mb - used_mb < file_size_mb:
            raise HTTPException(status_code=507, detail="Insufficient storage capacity")

        owner_dir = os.path.join(storage_dir, f"stored_for_{owner}")
        os.makedirs(owner_dir, exist_ok=True)
        file_path = os.path.join(owner_dir, f"{clip_id}.bin")
        
        with open(file_path, "wb") as f:
            f.write(contents)

        return {
            "ok": True,
            "clip_id": clip_id,
            "stored_by": cam_id,
            "size_mb": round(file_size_mb, 2)
        }

    @app.post("/prove")
    def prove_possession(payload: ProveRequest, request: Request) -> Dict[str, str]:
        """Performs a hash audit to prove a requested file remains unmodified."""
        logger.info(f"POST /prove called by {payload.owner} for clip {payload.clip_id}")
        
        file_path = os.path.join(storage_dir, f"stored_for_{payload.owner}", f"{payload.clip_id}.bin")
        if not os.path.exists(file_path):
            raise HTTPException(status_code=404, detail="not_found")
            
        with open(file_path, "rb") as f:
            file_bytes = f.read()
            
        nonce_bytes = payload.nonce.encode("utf-8")
        proof_hash = hashlib.sha256(nonce_bytes + file_bytes).hexdigest()
        
        return {
            "clip_id": payload.clip_id,
            "proof": proof_hash
        }

    @app.get("/recent_detections")
    def recent_detections(request: Request, since_seconds: float = 60.0) -> List[Dict[str, Any]]:
        """Returns detections logged within the trailing time window, formatted to the contract."""
        logger.info(f"GET /recent_detections called for past {since_seconds}s")
        now = time.time()
        cutoff = now - since_seconds
        
        formatted_results = []
        for d in app.state.detections:
            if d["timestamp"] >= cutoff:
                # Convert the raw Unix timestamp into the required "HH:MM:SS" format
                formatted_time = datetime.datetime.fromtimestamp(d["timestamp"]).strftime("%H:%M:%S")
                
                formatted_results.append({
                    "time": formatted_time,
                    "person_seen": True  # If it made it into this log, YOLO detected a person
                })
                
        return formatted_results

    @app.get("/retrieve/{owner}/{clip_id}")
    def retrieve_clip(owner: str, clip_id: str, request: Request) -> FileResponse:
        """Downloads a previously stored blob to its rightful owner."""
        logger.info(f"GET /retrieve called by {owner} for clip {clip_id}")
        file_path = os.path.join(storage_dir, f"stored_for_{owner}", f"{clip_id}.bin")
        if not os.path.exists(file_path):
            raise HTTPException(status_code=404, detail="File not found")
        return FileResponse(file_path)

    return app

async def request_bids(peer_urls: List[str], clip_size_mb: float, my_id: str) -> List[Dict[str, Any]]:
    """Requests storage bids from network peers concurrently."""
    bids = []
    async with httpx.AsyncClient(timeout=2.0) as client:
        for url in peer_urls:
            try:
                response = await client.post(
                    f"{url.rstrip('/')}/bid",
                    json={"clip_size_mb": clip_size_mb, "from": my_id}
                )
                if response.status_code == 200:
                    bids.append(response.json())
            except httpx.RequestError:
                continue
    return sorted([b for b in bids if b.get("can_store")], key=lambda x: x["ask_price"])

async def send_clip(peer_url: str, clip_id: str, owner: str, blob: bytes) -> Dict[str, Any]:
    """Uploads a clip to a selected peer node."""
    async with httpx.AsyncClient() as client:
        files = {"file": (f"{clip_id}.bin", blob, "application/octet-stream")}
        data = {"clip_id": clip_id, "owner": owner}
        response = await client.post(f"{peer_url.rstrip('/')}/store", data=data, files=files)
        response.raise_for_status()
        return response.json()

async def audit_peer(peer_url: str, clip_id: str, owner: str, expected_blob: bytes) -> bool:
    """Challenges a peer to prove possession of an untampered file."""
    nonce = secrets.token_hex(16)
    expected_hash = hashlib.sha256(nonce.encode("utf-8") + expected_blob).hexdigest()
    
    async with httpx.AsyncClient(timeout=3.0) as client:
        try:
            response = await client.post(
                f"{peer_url.rstrip('/')}/prove",
                json={"clip_id": clip_id, "owner": owner, "nonce": nonce}
            )
            if response.status_code != 200:
                return False
            
            peer_proof = response.json().get("proof")
            return peer_proof == expected_hash
        except httpx.RequestError:
            return False


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run an EdgeVault camera node.")
    parser.add_argument("--id", type=str, required=True, help="Camera ID (e.g., cam1)")
    parser.add_argument("--port", type=int, required=True, help="Port to run on")
    args = parser.parse_args()

    storage_dir = os.path.join("storage", args.id)
    app = create_app(cam_id=args.id, storage_dir=storage_dir)
    
    uvicorn.run(app, host="0.0.0.0", port=args.port)
    
    
