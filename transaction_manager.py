import os
from typing import Any

import httpx
from urllib.parse import urljoin
from utils import get_db


class TransactionManager:
    """Syncs transactions from Plaid into the local SQLite database and
    provides read access to the stored records."""

    PLAID_URL: str = "https://production.plaid.com"
    TIMEOUT: int = 30

    CREDS: dict[str, str] = {
        "client_id": os.environ["PLAID_CLIENT_ID"],
        "secret": os.environ["PLAID_SECRET"],
        "access_token": os.environ["PLAID_ACCESS_TOKEN"],
    }

    UPSERT: str = """
    INSERT INTO transactions (transaction_id, authorized_date, amount, merchant_name, category)
    VALUES (?, ?, ?, ?, ?)
    ON CONFLICT(transaction_id) DO UPDATE SET
      authorized_date = excluded.authorized_date,
      amount          = excluded.amount,
      merchant_name   = excluded.merchant_name,
      category        = excluded.category;
    """

    @staticmethod
    def row(txn: dict[str, Any]) -> tuple:
        """Convert a Plaid transaction dict into the tuple expected by UPSERT."""
        return (
            txn["transaction_id"],
            txn.get("authorized_date") or txn["date"],
            txn["amount"],
            txn.get("merchant_name") or txn.get("name"),
            " ".join(txn.get("category") or []),
        )

    def sync(self) -> dict[str, int]:
        """Pull all pages from Plaid's /transactions/sync since the last saved
        cursor, applying each page's added/modified/removed rows and the new
        cursor in a single DB transaction per page.

        Returns:
            dict with counts of added, modified, and removed transactions.
        """
        conn = get_db(sync=True)

        cur = conn.execute("SELECT cursor FROM sync_state WHERE id = 1").fetchone()
        cursor = cur[0] if cur else None

        result = dict(added=0, modified=0, removed=0)
        with httpx.Client(timeout=self.TIMEOUT) as client:
            while True:
                body = {**self.CREDS, "count": 500}
                if cursor:
                    body["cursor"] = cursor

                r = client.post(
                    urljoin(self.PLAID_URL, "/transactions/sync"), json=body
                )
                r.raise_for_status()
                page = r.json()

                with conn:  # one transaction: rows + cursor together
                    conn.executemany(
                        self.UPSERT,
                        [self.row(t) for t in page["added"] + page["modified"]],
                    )
                    conn.executemany(
                        "DELETE FROM transactions WHERE transaction_id = ?",
                        [(t["transaction_id"],) for t in page["removed"]],
                    )
                    conn.execute(
                        "INSERT INTO sync_state (id, cursor) VALUES (1, ?) "
                        "ON CONFLICT(id) DO UPDATE SET cursor = excluded.cursor",
                        (page["next_cursor"],),
                    )

                cursor = page["next_cursor"]

                result["added"] += len(page["added"])
                result["modified"] += len(page["modified"])
                result["removed"] += len(page["removed"])

                if not page["has_more"]:
                    break

        conn.close()
        return result

    def get_transactions_by_date(self, date_str: str) -> list[Any]:
        """Return all stored transactions authorized on the given date (YYYY-MM-DD)."""
        conn = get_db()
        cur = conn.execute(
            "SELECT transaction_id, authorized_date, amount, merchant_name, category "
            "FROM transactions WHERE authorized_date = ?",
            (date_str,),
        )
        transactions = cur.fetchall()
        conn.close()
        return transactions

    def get_transactions_by_date_range(self, start_date: str, end_date: str) -> list[Any]:
        """Return all stored transactions authorized between start_date and
        end_date (inclusive, YYYY-MM-DD)."""
        conn = get_db()
        cur = conn.execute(
            "SELECT transaction_id, authorized_date, amount, merchant_name, category "
            "FROM transactions WHERE authorized_date BETWEEN ? AND ?",
            (start_date, end_date),
        )
        transactions = cur.fetchall()
        conn.close()
        return transactions

    def get_transactions_by_merchant(self, merchant_name: str) -> list[Any]:
        """Return all stored transactions for an exact merchant name match."""
        conn = get_db()
        cur = conn.execute(
            "SELECT transaction_id, authorized_date, amount, merchant_name, category "
            "FROM transactions WHERE merchant_name = ?",
            (merchant_name,),
        )
        transactions = cur.fetchall()
        conn.close()
        return transactions

    def get_transactions_by_category(self, category: str) -> list[Any]:
        """Return all stored transactions matching an exact category string
        (categories are stored as a single space-joined string, see `row`)."""
        conn = get_db()
        cur = conn.execute(
            "SELECT transaction_id, authorized_date, amount, merchant_name, category "
            "FROM transactions WHERE category = ?",
            (category,),
        )
        transactions = cur.fetchall()
        conn.close()
        return transactions

    def get_recurring_transactions(self) -> dict[str, Any]:
        """Fetch recurring transaction streams directly from Plaid's
        /transactions/recurring/get endpoint (not read from the local DB)."""
        with httpx.Client(timeout=self.TIMEOUT) as client:
            r = client.post(
                urljoin(self.PLAID_URL, "/transactions/recurring/get"), json=self.CREDS
            )
            r.raise_for_status()
            transactions = r.json()
        return transactions
