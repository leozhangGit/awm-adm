"""Owned schema 16: single connection and direct model exchanges; artifacts unchanged."""


def extend(db, kind):
    if kind == "registry":
        db.execute("UPDATE installation_upgrade SET target=16,status='migrating' WHERE id=1")
        db.execute(
            "CREATE TABLE connection_control (id INTEGER PRIMARY KEY CHECK(id=1), generation INTEGER NOT NULL DEFAULT 0, connection_id TEXT, state TEXT NOT NULL DEFAULT 'disabled', operation_id TEXT, error TEXT)"
        )
        rows = db.execute("SELECT DISTINCT id FROM connections").fetchall()
        db.execute(
            "INSERT INTO connection_control(id,connection_id) VALUES(1,?)",
            (rows[0][0] if len(rows) == 1 else None,),
        )
        db.execute(
            "CREATE TABLE connection_operations (seq INTEGER PRIMARY KEY AUTOINCREMENT, id TEXT UNIQUE NOT NULL, idem TEXT UNIQUE NOT NULL, digest TEXT NOT NULL, kind TEXT NOT NULL, body BLOB NOT NULL, grant_id TEXT, status TEXT NOT NULL, error TEXT, created REAL NOT NULL)"
        )
        db.execute("ALTER TABLE grants ADD COLUMN dispatched_at REAL")
        # An upgrade is never permission to test a key or resume remote work.
        db.execute("UPDATE learning_control SET enabled=0,generation=generation+1 WHERE id=1")
    else:
        db.execute(
            "CREATE TABLE direct_interactions (seq INTEGER PRIMARY KEY AUTOINCREMENT, id TEXT UNIQUE NOT NULL, idem TEXT UNIQUE NOT NULL, digest TEXT NOT NULL, channel TEXT NOT NULL, conversation TEXT NOT NULL, origin TEXT NOT NULL, reply_to TEXT, created REAL NOT NULL)"
        )
        db.execute("CREATE INDEX direct_channel_seq ON direct_interactions(channel,seq)")
        db.execute("CREATE INDEX direct_activity_time ON direct_interactions(created,seq)")
