import asyncio
from camera.crypto import VaultCrypto
from camera.ledger import Ledger
from camera.p2p import send_clip, audit_peer

async def run_full_simulation():
    print("1. SETTING UP THE ECONOMY")
    db = Ledger("test_bank.db")
    db.set_balance("cam1", 100.0)
    db.set_balance("cam2", 10.0)
    print(f"Cam1 Balance: {db.get_balance('cam1')} | Cam2 Balance: {db.get_balance('cam2')}")

    print("\n 2. ENCRYPTING THE FAKE VIDEO ")
    crypto = VaultCrypto("cam1_key.bin")
    fake_video_bytes = b"This is fake YOLO video data for testing."
    encrypted_blob = crypto.encrypt(fake_video_bytes)
    print(f"Original size: {len(fake_video_bytes)} bytes")
    print(f"Encrypted size (with nonce + seal): {len(encrypted_blob)} bytes")

    print("\n 3. PAYING FOR STORAGE")
    # Cam1 pays Cam2 5 credits for storage
    success = db.transfer("cam1", "cam2", 5.0, "won_auction")
    if success:
        print("Payment successful!")
        print(f"Cam1 Balance: {db.get_balance('cam1')} | Cam2 Balance: {db.get_balance('cam2')}")
    else:
        print("Payment failed!")

    print("\n4. NETWORK TRANSFER (Requires Cam2 running on port 8002) ---")
    try:
        # Note: 'python camera/p2p.py --id cam2 --port 8002' must be running in another terminal
        upload_receipt = await send_clip("http://localhost:8002", "clip_001", "cam1", encrypted_blob)
        print("Upload Receipt from Cam2:", upload_receipt)

        print("\n 5. CRYPTOGRAPHIC AUDIT (Slashing Check) ")
        passed = await audit_peer("http://localhost:8002", "clip_001", "cam1", encrypted_blob)
        if passed:
            print("AUDIT PASSED: Cam2 still has the untampered file.")
        else:
            print("AUDIT FAILED: Slashing Cam2's credits!")
            db.slash("cam2", 10.0, "failed_audit")
            print(f"Cam2 Balance after slash: {db.get_balance('cam2')}")
            
    except Exception as e:
        print("\n[!] Network failed. Did you start Cam2 in another terminal on port 8002?")
        print(f"Error: {e}")

if __name__ == "__main__":
    asyncio.run(run_full_simulation())