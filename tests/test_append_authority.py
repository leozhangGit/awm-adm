"""Historical login credentials cannot act as source-queue bearer credentials."""

import pytest
from starlette.requests import Request

from awm_adm.application.auth import AppendAuthority
from awm_adm.runtime.protocol import RuntimeFault, dumps

from .test_application import app_runtime as app_runtime
from .test_application import tank


def test_append_credentials_keep_scope_and_expiry_without_session_authentication(app_runtime):
    rt = app_runtime
    key = tank(rt)
    auth = AppendAuthority(rt.store)
    issued = auth.issue(adms=[key])
    request = Request(
        {"type": "http", "headers": [(b"authorization", b"Bearer " + issued["token"].encode())]}
    )
    assert auth.require(request, key)["owner"] is False
    for change in (
        "kind='session'",
        "revoked=1",
        "expires=0",
    ):
        with rt.store.db() as db:
            db.execute("UPDATE credentials SET kind='token',revoked=0,expires=9999999999")
            db.execute("UPDATE credentials SET " + change)
        with pytest.raises(RuntimeFault) as error:
            auth.require(request, key)
        assert error.value.code == "unauthorized"
    with rt.store.db() as db:
        db.execute(
            "UPDATE credentials SET kind='token',revoked=0,expires=9999999999,scope=?",
            (dumps({"adms": [key], "permissions": ["read"]}),),
        )
    with pytest.raises(RuntimeFault) as error:
        auth.require(request, key)
    assert error.value.code == "forbidden"
    with pytest.raises(RuntimeFault), rt.store.db() as db:
        auth._issue(db, adms=[key], permissions=["read"], seconds=60)
