"""Schema 11: immutable presentations; no changes to prior conversation consent."""


def extend(db, kind):
    if kind == "registry":
        db.execute(
            "UPDATE installation_upgrade SET target=11,status='migrating',components=? WHERE id=1",
            ('{"registry":11,"instances":11,"gateway":1}',),
        )
    else:
        db.execute(
            "CREATE TABLE chat_presentations (id TEXT PRIMARY KEY,conversation TEXT NOT NULL,body BLOB NOT NULL)"
        )
        db.execute("CREATE INDEX chat_presentation_conversation ON chat_presentations(conversation)")
