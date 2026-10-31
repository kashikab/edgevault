import sqlite3
import time
from typing import Optional

class Ledger:
    def __init__(self, db_path: str = "ledger.db"):
        self.db_path = db_path
        self._init_db()

    def _get_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        """Initializes accounts and transactions tables."""
        with self._get_connection() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS accounts (
                    cam_id TEXT PRIMARY KEY,
                    balance REAL NOT NULL DEFAULT 100.0
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS transactions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    sender TEXT NOT NULL,
                    receiver TEXT NOT NULL,
                    amount REAL NOT NULL,
                    reason TEXT NOT NULL,
                    timestamp REAL NOT NULL
                )
            """)
            conn.commit()

    def get_balance(self, cam_id: str) -> float:
        """Gets balance, creating account with 100.0 credits if new."""
        with self._get_connection() as conn:
            row = conn.execute("SELECT balance FROM accounts WHERE cam_id = ?", (cam_id,)).fetchone()
            if row is None:
                conn.execute("INSERT INTO accounts (cam_id, balance) VALUES (?, 100.0)", (cam_id,))
                conn.commit()
                return 100.0
            return float(row["balance"])

    def set_balance(self, cam_id: str, balance: float) -> None:
        """Directly sets balance (useful for setup and testing)."""
        with self._get_connection() as conn:
            conn.execute(
                "INSERT INTO accounts (cam_id, balance) VALUES (?, ?) ON CONFLICT(cam_id) DO UPDATE SET balance = ?",
                (cam_id, balance, balance)
            )
            conn.commit()

    def transfer(self, sender: str, receiver: str, amount: float, reason: str = "storage_payment") -> bool:
        """Transfers credits between two cameras atomically."""
        if amount <= 0:
            return False

        with self._get_connection() as conn:
            cur = conn.cursor()
            sender_bal = self.get_balance(sender)
            if sender_bal < amount:
                return False

            self.get_balance(receiver)  # ensure receiver account exists

            cur.execute("UPDATE accounts SET balance = balance - ? WHERE cam_id = ?", (amount, sender))
            cur.execute("UPDATE accounts SET balance = balance + ? WHERE cam_id = ?", (amount, receiver))
            cur.execute(
                "INSERT INTO transactions (sender, receiver, amount, reason, timestamp) VALUES (?, ?, ?, ?, ?)",
                (sender, receiver, amount, reason, time.time())
            )
            conn.commit()
            return True

    def slash(self, cam_id: str, penalty: float, reason: str = "failed_audit") -> float:
        """Penalizes a camera for failed audits or dropped files."""
        with self._get_connection() as conn:
            cur = conn.cursor()
            current_bal = self.get_balance(cam_id)
            new_bal = max(0.0, current_bal - penalty)
            cur.execute("UPDATE accounts SET balance = ? WHERE cam_id = ?", (new_bal, cam_id))
            cur.execute(
                "INSERT INTO transactions (sender, receiver, amount, reason, timestamp) VALUES (?, 'BURN_ADDRESS', ?, ?, ?)",
                (cam_id, penalty, reason, time.time())
            )
            conn.commit()
            return new_bal