"""Owned schema 4: durable learning intents, reservations and receiver records."""


def extend(db, kind):
    if kind == "registry":
        statements = [
            "CREATE TABLE learning_control (id INTEGER PRIMARY KEY CHECK(id=1), generation INTEGER NOT NULL DEFAULT 0, enabled INTEGER NOT NULL DEFAULT 0, public_key BLOB, clock REAL NOT NULL DEFAULT 0)",
            "INSERT INTO learning_control(id) VALUES(1)",
            "CREATE TABLE connections (seq INTEGER PRIMARY KEY AUTOINCREMENT, id TEXT NOT NULL, version INTEGER NOT NULL, idem TEXT UNIQUE NOT NULL, digest TEXT NOT NULL, config BLOB NOT NULL, status TEXT NOT NULL, UNIQUE(id,version))",
            "CREATE TABLE grants (seq INTEGER PRIMARY KEY AUTOINCREMENT, id TEXT UNIQUE NOT NULL, adm TEXT, episode TEXT, status TEXT NOT NULL, body BLOB NOT NULL, outcome BLOB, created REAL NOT NULL, input_tokens INTEGER NOT NULL, output_tokens INTEGER NOT NULL, calls INTEGER NOT NULL DEFAULT 1, unresolved INTEGER NOT NULL DEFAULT 1)",
            "CREATE TABLE connection_tests (id TEXT PRIMARY KEY, idem TEXT UNIQUE NOT NULL, digest TEXT NOT NULL, grant_id TEXT NOT NULL)",
        ]
    else:
        statements = [
            "CREATE TABLE episodes (seq INTEGER PRIMARY KEY AUTOINCREMENT, id TEXT UNIQUE NOT NULL, idem TEXT UNIQUE NOT NULL, digest TEXT NOT NULL, data BLOB NOT NULL)",
            "CREATE TABLE interests (episode TEXT NOT NULL, request TEXT NOT NULL, PRIMARY KEY(episode,request))",
            "CREATE TABLE learning_receipts (seq INTEGER PRIMARY KEY AUTOINCREMENT, id TEXT UNIQUE NOT NULL, episode TEXT NOT NULL, status TEXT NOT NULL, data BLOB NOT NULL)",
            "ALTER TABLE attempts ADD COLUMN revision TEXT",
            "UPDATE attempts SET revision=(SELECT revision FROM requests WHERE requests.id=attempts.request_id)",
            "ALTER TABLE requests ADD COLUMN initial_revision TEXT",
            "UPDATE requests SET initial_revision=revision",
        ]
    for statement in statements:
        db.execute(statement)
