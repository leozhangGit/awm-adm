"""Schema 15: bounded deletion journal and gateway cleanup acknowledgements."""


def extend(db, kind):
    if kind != "registry":
        return
    db.execute(
        "CREATE TABLE deletions (id TEXT PRIMARY KEY, adm TEXT UNIQUE NOT NULL, idem TEXT UNIQUE NOT NULL, digest TEXT NOT NULL, stage TEXT NOT NULL, resume_stage TEXT, version INTEGER NOT NULL, inventory BLOB NOT NULL, created REAL NOT NULL, updated REAL NOT NULL)"
    )
    db.execute(
        "CREATE TABLE deletion_grants (grant_id TEXT PRIMARY KEY, operation_id TEXT NOT NULL, acknowledged INTEGER NOT NULL DEFAULT 0)"
    )
    db.execute(
        "UPDATE installation_upgrade SET target=15,status='migrating',components=? WHERE id=1",
        ('{"registry":15,"instances":15,"gateway":1}',),
    )
