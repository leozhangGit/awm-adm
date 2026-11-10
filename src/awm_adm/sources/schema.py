"""Schema 6: immutable material, manual extraction, and ordered projection receipts."""


def extend(db, kind):
    statements = (
        [
            "CREATE TABLE source_arrivals (id TEXT PRIMARY KEY, adm TEXT NOT NULL, seq INTEGER NOT NULL, data BLOB NOT NULL, UNIQUE(adm,seq))",
        ]
        if kind == "registry"
        else [
            "CREATE TABLE source_profiles (generation INTEGER PRIMARY KEY, data BLOB NOT NULL)",
            "INSERT INTO source_profiles VALUES(0,'{}')",
            "CREATE TABLE source_versions (seq INTEGER PRIMARY KEY AUTOINCREMENT, id TEXT UNIQUE NOT NULL, source TEXT NOT NULL, item TEXT NOT NULL, version TEXT NOT NULL, data BLOB NOT NULL, UNIQUE(source,item,version))",
            "CREATE TABLE source_heads (source TEXT NOT NULL,item TEXT NOT NULL,version TEXT NOT NULL,PRIMARY KEY(source,item))",
            "CREATE TABLE source_batches (idem TEXT PRIMARY KEY,digest TEXT NOT NULL,data BLOB NOT NULL)",
            "CREATE TABLE source_jobs (seq INTEGER PRIMARY KEY AUTOINCREMENT,id TEXT UNIQUE NOT NULL,idem TEXT UNIQUE NOT NULL,digest TEXT NOT NULL,pipeline TEXT UNIQUE NOT NULL,status TEXT NOT NULL,data BLOB NOT NULL)",
            "CREATE TABLE source_claims (id TEXT PRIMARY KEY,job TEXT NOT NULL,version TEXT NOT NULL,status TEXT NOT NULL,data BLOB NOT NULL)",
            "CREATE TABLE source_episodes (seq INTEGER PRIMARY KEY AUTOINCREMENT,id TEXT UNIQUE NOT NULL,idem TEXT UNIQUE NOT NULL,digest TEXT NOT NULL,status TEXT NOT NULL,data BLOB NOT NULL)",
            "CREATE TABLE source_support (symbol TEXT PRIMARY KEY,claim TEXT NOT NULL,version TEXT NOT NULL,status TEXT NOT NULL)",
            "CREATE TABLE source_revalidations (id TEXT PRIMARY KEY,data BLOB NOT NULL)",
        ]
    )
    for statement in statements:
        db.execute(statement)
