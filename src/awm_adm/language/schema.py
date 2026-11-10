"""Schema 5: app-owned vocabulary, conversations, interpretations and consent."""


def extend(db, kind):
    if kind == "registry":
        return
    for statement in [
        "CREATE TABLE language_profiles (generation INTEGER PRIMARY KEY, data BLOB NOT NULL)",
        "INSERT INTO language_profiles VALUES(0,'{}')",
        "CREATE TABLE conversations (seq INTEGER PRIMARY KEY AUTOINCREMENT, id TEXT UNIQUE NOT NULL, idem TEXT UNIQUE NOT NULL, digest TEXT NOT NULL, title TEXT NOT NULL, created REAL NOT NULL)",
        "CREATE TABLE interpretations (seq INTEGER PRIMARY KEY AUTOINCREMENT, id TEXT UNIQUE NOT NULL, idem TEXT UNIQUE NOT NULL, digest TEXT NOT NULL, conversation TEXT NOT NULL, status TEXT NOT NULL, data BLOB NOT NULL)",
        "CREATE TABLE language_executions (interpretation TEXT PRIMARY KEY, idem TEXT UNIQUE NOT NULL, digest TEXT NOT NULL, request TEXT UNIQUE NOT NULL)",
        "CREATE TABLE teaching_drafts (seq INTEGER PRIMARY KEY AUTOINCREMENT, id TEXT UNIQUE NOT NULL, idem TEXT UNIQUE NOT NULL, digest TEXT NOT NULL, conversation TEXT NOT NULL, data BLOB NOT NULL)",
    ]:
        db.execute(statement)
