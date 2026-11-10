"""Schema 3, applied inside the runtime's owned migration transaction."""


def extend(connection, kind):
    statements = (
        [
            "CREATE TABLE credentials (id TEXT PRIMARY KEY, digest TEXT UNIQUE NOT NULL, kind TEXT NOT NULL, scope BLOB NOT NULL, csrf TEXT, expires REAL NOT NULL, revoked INTEGER NOT NULL DEFAULT 0)",
            "CREATE TABLE operations (id TEXT PRIMARY KEY, idem TEXT UNIQUE NOT NULL, digest TEXT NOT NULL, kind TEXT NOT NULL, adm TEXT, body BLOB NOT NULL, status TEXT NOT NULL, result BLOB, error TEXT, created REAL NOT NULL)",
        ]
        if kind == "registry"
        else [
            "CREATE TABLE revisions (seq INTEGER PRIMARY KEY AUTOINCREMENT, id TEXT UNIQUE NOT NULL, context BLOB NOT NULL, payload BLOB NOT NULL, digest TEXT NOT NULL)",
            "CREATE TABLE control (id INTEGER PRIMARY KEY CHECK(id=1), revision TEXT, archived INTEGER NOT NULL DEFAULT 0, floor INTEGER NOT NULL DEFAULT 0)",
            "INSERT INTO control(id) VALUES(1)",
            "CREATE TABLE requests (seq INTEGER PRIMARY KEY AUTOINCREMENT, id TEXT UNIQUE NOT NULL, idem TEXT UNIQUE NOT NULL, digest TEXT NOT NULL, envelope BLOB NOT NULL, revision TEXT NOT NULL, context BLOB NOT NULL, status TEXT NOT NULL, attempt TEXT, generation TEXT, expires REAL, result BLOB, result_id TEXT UNIQUE, error BLOB, created REAL NOT NULL, updated REAL NOT NULL)",
            "CREATE TABLE attempts (seq INTEGER PRIMARY KEY AUTOINCREMENT, id TEXT UNIQUE NOT NULL, request_id TEXT NOT NULL, generation TEXT NOT NULL, status TEXT NOT NULL, started REAL NOT NULL, ended REAL)",
            "CREATE TABLE events (seq INTEGER PRIMARY KEY AUTOINCREMENT, payload BLOB NOT NULL, created REAL NOT NULL)",
            "CREATE TABLE consumers (id TEXT PRIMARY KEY, principal TEXT NOT NULL, cursor INTEGER NOT NULL)",
        ]
    )
    for statement in statements:
        connection.execute(statement)
