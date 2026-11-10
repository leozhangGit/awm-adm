"""Schema 13: idempotent owner commands for durable teaching execution."""


def extend(db, kind):
    if kind == "registry":
        db.execute(
            "UPDATE installation_upgrade SET target=13,status='migrating',components=? WHERE id=1",
            ('{"registry":13,"instances":13,"gateway":1}',),
        )
    else:
        db.execute(
            "CREATE TABLE teaching_commands (id TEXT PRIMARY KEY,task TEXT NOT NULL,digest TEXT NOT NULL,body BLOB NOT NULL)"
        )
