"""Schema 12: retained teaching preparation and immutable approved specifications."""


def extend(db, kind):
    if kind == "registry":
        db.execute(
            "UPDATE installation_upgrade SET target=12,status='migrating',components=? WHERE id=1",
            ('{"registry":12,"instances":12,"gateway":1}',),
        )
    else:
        db.execute(
            "CREATE TABLE teaching_tasks (seq INTEGER PRIMARY KEY AUTOINCREMENT,id TEXT UNIQUE NOT NULL,conversation TEXT NOT NULL,status TEXT NOT NULL,body BLOB NOT NULL)"
        )
        db.execute("CREATE INDEX teaching_conversation ON teaching_tasks(conversation,seq)")
