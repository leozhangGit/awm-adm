"""Owned schema 14; original source bytes and immutable intake acknowledgements."""


def extend(db, kind):
    if kind == "registry":
        db.execute(
            "UPDATE installation_upgrade SET target=14,status='migrating',components=? WHERE id=1",
            ('{"registry":14,"instances":14,"gateway":1}',),
        )
        return
    for sql in (
        "CREATE TABLE intake_material (id TEXT PRIMARY KEY,source TEXT NOT NULL,item TEXT NOT NULL,version TEXT NOT NULL,body BLOB NOT NULL,UNIQUE(source,item,version))",
        "CREATE TABLE intake_upload_keys (idem TEXT PRIMARY KEY,digest TEXT NOT NULL,attachment TEXT NOT NULL)",
        "CREATE TABLE intake_receipts (id TEXT PRIMARY KEY,digest TEXT NOT NULL,credential TEXT NOT NULL,task TEXT NOT NULL,created REAL NOT NULL,body BLOB NOT NULL)",
        "CREATE TABLE source_notice_resolutions (id TEXT PRIMARY KEY,body BLOB NOT NULL)",
    ):
        db.execute(sql)
