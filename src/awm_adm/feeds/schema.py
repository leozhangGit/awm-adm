"""Schema 7: feed intents, bounded reservations and shared processing interests."""


def extend(db, kind):
    if kind == "registry":
        return
    for sql in (
        "CREATE TABLE feeds (seq INTEGER PRIMARY KEY AUTOINCREMENT,id TEXT UNIQUE NOT NULL,idem TEXT UNIQUE NOT NULL,digest TEXT NOT NULL,data BLOB NOT NULL)",
        "CREATE TABLE feed_runs (id TEXT PRIMARY KEY,pipeline TEXT UNIQUE NOT NULL,status TEXT NOT NULL,data BLOB NOT NULL)",
        "CREATE TABLE feed_items (seq INTEGER PRIMARY KEY AUTOINCREMENT,feed TEXT NOT NULL,source_seq INTEGER NOT NULL,pass_id TEXT NOT NULL,run TEXT NOT NULL,data BLOB NOT NULL,UNIQUE(feed,source_seq,pass_id))",
        "CREATE TABLE feed_controls (idem TEXT PRIMARY KEY,digest TEXT NOT NULL,data BLOB NOT NULL)",
        "CREATE TABLE coverage_transitions (seq INTEGER PRIMARY KEY AUTOINCREMENT,data BLOB NOT NULL)",
        "CREATE INDEX feed_items_run ON feed_items(run)",
    ):
        db.execute(sql)
