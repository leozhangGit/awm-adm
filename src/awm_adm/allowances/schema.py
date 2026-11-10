"""Schema 9. Existing grant counters and outcomes are not rewritten."""

from ..runtime.protocol import loads


def extend(db, kind):
    if kind != "registry":
        return
    for sql in (
        "CREATE TABLE spending_control (id INTEGER PRIMARY KEY CHECK(id=1), generation INTEGER NOT NULL, body BLOB NOT NULL)",
        "INSERT INTO spending_control VALUES(1,0,'{}')",
        "CREATE TABLE spending_history (generation INTEGER PRIMARY KEY, body BLOB NOT NULL)",
        "CREATE TABLE prices (seq INTEGER PRIMARY KEY AUTOINCREMENT, id TEXT UNIQUE NOT NULL, idem TEXT UNIQUE NOT NULL, digest TEXT NOT NULL, body BLOB NOT NULL, revoked INTEGER NOT NULL DEFAULT 0)",
        "CREATE TABLE allowances (seq INTEGER PRIMARY KEY AUTOINCREMENT, id TEXT UNIQUE NOT NULL, idem TEXT UNIQUE NOT NULL, digest TEXT NOT NULL, body BLOB NOT NULL, state TEXT NOT NULL DEFAULT 'active')",
        "CREATE TABLE charges (grant_id TEXT PRIMARY KEY, allowance_id TEXT NOT NULL, reserved INTEGER NOT NULL, settled TEXT, state TEXT NOT NULL, price BLOB NOT NULL)",
        "CREATE TABLE budget_children (allowance_id TEXT NOT NULL, operation_id TEXT NOT NULL, digest TEXT NOT NULL, body BLOB NOT NULL, used_work INTEGER, PRIMARY KEY(allowance_id,operation_id))",
        "CREATE TABLE legacy_spending (grant_id TEXT PRIMARY KEY)",
        "CREATE TABLE provider_lanes (lane TEXT PRIMARY KEY, last_adm TEXT, last_claim INTEGER NOT NULL DEFAULT 0, suspended INTEGER NOT NULL DEFAULT 0)",
        "INSERT INTO provider_lanes(lane) VALUES('interaction'),('learning')",
        "ALTER TABLE grants ADD COLUMN lane TEXT NOT NULL DEFAULT 'learning'",
    ):
        db.execute(sql)
    db.execute(
        "UPDATE installation_upgrade SET target=9,status='migrating',components=? WHERE id=1",
        ('{"registry":9,"instances":9,"gateway":1}',),
    )
    for row in db.execute("SELECT id,body,calls FROM grants").fetchall():
        body = loads(row[1])
        if body["purpose"] == "interpretation":
            db.execute("UPDATE grants SET lane='interaction' WHERE id=?", (row[0],))
        config = db.execute(
            "SELECT config FROM connections WHERE id=? AND version=?",
            (body["connection_id"], body["connection_version"]),
        ).fetchone()
        if row[2] and (config is None or loads(config[0])["provider"] != "recorded"):
            db.execute("INSERT INTO legacy_spending VALUES(?)", (row[0],))
