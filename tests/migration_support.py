"""Remove additive fields when reconstructing an older registry fixture."""


def remove_lifecycle(db):
    for table in ("deletion_grants", "deletions"):
        db.execute(f"DROP TABLE IF EXISTS {table}")


def remove_allowances(db):
    remove_lifecycle(db)
    for table in (
        "spending_control",
        "spending_history",
        "prices",
        "allowances",
        "charges",
        "budget_children",
        "legacy_spending",
        "provider_lanes",
    ):
        db.execute(f"DROP TABLE IF EXISTS {table}")
    if any(r[1] == "lane" for r in db.execute("PRAGMA table_info(grants)")):
        db.execute("ALTER TABLE grants DROP COLUMN lane")


def remove_admin(db):
    remove_allowances(db)
    for table in ("administrator", "auth_control", "auth_tickets", "auth_attempts", "installation_upgrade"):
        db.execute(f"DROP TABLE {table}")
    db.execute("ALTER TABLE credentials DROP COLUMN admin_generation")


def remove_conversations(db):
    remove_lifecycle(db)
    for table in (
        "chat_conversations",
        "chat_turns",
        "chat_inputs",
        "chat_questions",
        "chat_proposals",
        "chat_decisions",
        "chat_work",
        "chat_attachments",
        "chat_presentations",
        "teaching_tasks",
        "teaching_commands",
        "intake_material",
        "intake_upload_keys",
        "intake_receipts",
        "source_notice_resolutions",
    ):
        db.execute(f"DROP TABLE IF EXISTS {table}")
