"""Schema 8: local administrator and bounded credentials; no model changes."""

import time


def extend(db, kind):
    if kind != "registry":
        return
    for statement in (
        "CREATE TABLE administrator (id INTEGER PRIMARY KEY CHECK(id=1), uid TEXT NOT NULL, email TEXT NOT NULL, password_hash TEXT NOT NULL, generation INTEGER NOT NULL)",
        "CREATE TABLE auth_control (id INTEGER PRIMARY KEY CHECK(id=1), legacy_until REAL NOT NULL)",
        "CREATE TABLE auth_tickets (kind TEXT PRIMARY KEY, digest TEXT NOT NULL, expires REAL NOT NULL)",
        "CREATE TABLE auth_attempts (key TEXT PRIMARY KEY, count INTEGER NOT NULL, expires REAL NOT NULL)",
        "ALTER TABLE credentials ADD COLUMN admin_generation INTEGER",
        "CREATE TABLE installation_upgrade (id INTEGER PRIMARY KEY CHECK(id=1), target INTEGER NOT NULL, status TEXT NOT NULL, components BLOB NOT NULL)",
        'INSERT INTO installation_upgrade VALUES(1,8,\'migrating\',\'{"registry":8,"instances":8,"gateway":1}\')',
    ):
        db.execute(statement)
    db.execute("INSERT INTO auth_control VALUES(1,?)", (time.time() + 900,))
