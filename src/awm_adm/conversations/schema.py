"""Schema 10: additive conversations; explicit interpretation records stay untouched."""


def extend(db, kind):
    if kind == "registry":
        db.execute(
            "UPDATE installation_upgrade SET target=10,status='migrating',components=? WHERE id=1",
            ('{"registry":10,"instances":10,"gateway":1}',),
        )
        return
    for sql in (
        "CREATE TABLE chat_conversations (seq INTEGER PRIMARY KEY AUTOINCREMENT,id TEXT UNIQUE NOT NULL,idem TEXT UNIQUE NOT NULL,digest TEXT NOT NULL,body BLOB NOT NULL)",
        "CREATE TABLE chat_turns (seq INTEGER PRIMARY KEY AUTOINCREMENT,id TEXT UNIQUE NOT NULL,conversation TEXT NOT NULL,body BLOB NOT NULL)",
        "CREATE TABLE chat_inputs (idem TEXT PRIMARY KEY,digest TEXT NOT NULL,conversation TEXT NOT NULL,turn_id TEXT NOT NULL)",
        "CREATE TABLE chat_questions (id TEXT PRIMARY KEY,conversation TEXT NOT NULL,status TEXT NOT NULL,body BLOB NOT NULL)",
        "CREATE TABLE chat_proposals (id TEXT PRIMARY KEY,conversation TEXT NOT NULL,status TEXT NOT NULL,body BLOB NOT NULL)",
        "CREATE TABLE chat_decisions (id TEXT PRIMARY KEY,idem TEXT UNIQUE NOT NULL,digest TEXT NOT NULL,proposal TEXT UNIQUE NOT NULL,status TEXT NOT NULL,body BLOB NOT NULL)",
        "CREATE TABLE chat_work (seq INTEGER PRIMARY KEY AUTOINCREMENT,id TEXT UNIQUE NOT NULL,conversation TEXT NOT NULL,status TEXT NOT NULL,body BLOB NOT NULL)",
        "CREATE TABLE chat_attachments (id TEXT PRIMARY KEY,idem TEXT UNIQUE NOT NULL,digest TEXT NOT NULL,body BLOB NOT NULL)",
        "CREATE INDEX chat_turn_conversation ON chat_turns(conversation,seq)",
        "CREATE INDEX chat_work_status ON chat_work(status,seq)",
    ):
        db.execute(sql)
