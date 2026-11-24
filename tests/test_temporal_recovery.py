"""Authored interruptions of mixed-evidence publication; no provider dispatch."""

from uuid import uuid4

import pytest

from awm_adm.runtime.service import Runtime

from .temporal_support import catalog, fact
from .test_application import configuration
from .test_sources import finish, ingest, install, job
from .test_temporal_evidence import ask


@pytest.mark.parametrize("stage", ["revision", "support", "receipt"])
def test_mixed_publication_rolls_back_every_binding_on_interruption(tmp_path, monkeypatch, stage):
    config = configuration(tmp_path / "store")
    rt = Runtime(config, start_scheduler=False)
    try:
        key = rt.create("Interrupted mixed publication")["id"]
        install(rt, key, projection=catalog())
        source = ingest(rt, key, [fact(i) for i in range(3)])
        extracted = finish(rt, key, job(rt, key, source))
        episode = rt.sources.create_projection(
            key,
            {
                "idempotency_key": str(uuid4()),
                "expected_revision": rt.store.info(key)["revision_id"],
                "expected_generation": 1,
                "claim_ids": [r["claim"]["claim_id"] for r in extracted["result"]["claims"]],
            },
        )
        ready = finish(rt, key, episode, "source_episodes")
        assert ready["status"] == "awaiting_review"
        rt.sources.review(
            key, ready["id"], {"expected_revision": rt.store.info(key)["revision_id"], "approve": True}
        )
        before = rt.store.revision(key)
        with rt.store.db(key) as db:
            revisions = db.execute("SELECT count(*) FROM revisions").fetchone()[0]
        publish, save, emit = rt.sources.publish, rt.sources.save, rt.store.emit

        def interrupted_publish(*args, **kw):
            result = publish(*args, **kw)
            if stage == "revision":
                raise OSError("Authored interrupted transaction")
            return result

        def interrupted_save(db, table, item):
            result = save(db, table, item)
            if stage == "support" and table == "source_episodes" and item["status"] == "accepted":
                raise OSError("Authored interrupted transaction")
            return result

        def interrupted_emit(*args, **kw):
            result = emit(*args, **kw)
            if stage == "receipt" and args[2] == "candidate.accepted":
                raise OSError("Authored interrupted transaction")
            return result

        with monkeypatch.context() as patch:
            patch.setattr(rt.sources, "publish", interrupted_publish)
            patch.setattr(rt.sources, "save", interrupted_save)
            patch.setattr(rt.store, "emit", interrupted_emit)
            with pytest.raises(OSError, match="Authored interrupted"):
                rt.sources.tick()
        assert rt.store.revision(key) == before
        with rt.store.db(key) as db:
            assert db.execute("SELECT count(*) FROM revisions").fetchone()[0] == revisions
            assert db.execute("SELECT count(*) FROM source_support").fetchone()[0] == 0
            assert db.execute("SELECT count(*) FROM source_claims WHERE status='accepted'").fetchone()[0] == 0
        assert rt.learning.usage()["calls"] == 0
    finally:
        rt.close()
    recovered = Runtime(config, start_scheduler=False)
    try:
        assert recovered.store.revision(key) == before
        assert recovered.sources.get(key, "source_episodes", episode["id"])["status"] == "stopped"
        assert all(ask(recovered, key, i)["status"] == "needs_input" for i in range(3))
        assert recovered.learning.usage()["calls"] == 0
    finally:
        recovered.close()
