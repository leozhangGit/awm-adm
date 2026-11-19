"""Imported history metadata remains locally available without provider authority."""

from awm_adm.conversations.history import options

from .test_application import app_runtime as app_runtime
from .test_application import client
from .test_sources import ingest, install, lookup, project


def test_imported_history_options_are_local_without_new_source_authority(app_runtime):
    rt = app_runtime
    key = rt.create("Historical metadata")["id"]
    install(rt, key)
    project(rt, key, ingest(rt, key))
    clone = rt.create("Independent copy", snapshot=rt.store.revision(key)["snapshot"])["id"]
    assert rt.sources.policy(clone).get("projection") is None
    before = rt.learning.usage()
    chosen = options(rt.conversations, clone)
    assert chosen["context"] == rt.conversations.context(clone)
    assert chosen["projections"][0]["entities"] == ["site"]
    assert chosen["projections"][0]["predicates"][0]["symbol"] == "site.capacity"
    assert lookup(rt, clone, 2021)["status"] == "succeeded"
    assert rt.learning.usage() == before
    with client(rt) as c:
        response = c.get(f"/api/v1/adms/{clone}/history-options")
        assert response.status_code == 200
        assert response.json() == chosen
    with rt.store.db(clone) as db:
        assert not db.execute("SELECT 1 FROM source_versions").fetchone()
    assert rt.sources.policy(clone).get("projection") is None
