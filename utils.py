import os
import libsql  # type: ignore


def get_db(sync: bool = False):
    url = os.environ.get("TURSO_DATABASE_URL", "")
    token = os.environ.get("TURSO_AUTH_TOKEN", "")
    conn = libsql.connect("/tmp/nutrition.db", sync_url=url, auth_token=token)
    if sync:
        conn.sync()
    return conn
