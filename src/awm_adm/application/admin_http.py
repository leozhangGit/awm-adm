"""Administrator inputs and cookie-only public session interface."""

from typing import Literal

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import Field, SecretStr

from ..contracts import ClosedModel
from ..runtime.protocol import RuntimeFault
from .admin import COOKIE, SESSION_SECONDS, Administrator, csrf_for


class LoginInput(ClosedModel):
    profile: Literal["awm-adm-v3-logininput/0.1"] = "awm-adm-v3-logininput/0.1"
    email: str = Field(min_length=3, max_length=254)
    password: SecretStr = Field(min_length=1, max_length=1024)


class SetupInput(LoginInput):
    profile: Literal["awm-adm-v3-setupinput/0.1"] = "awm-adm-v3-setupinput/0.1"
    password: SecretStr = Field(min_length=15, max_length=1024)
    bootstrap_token: SecretStr = Field(min_length=40, max_length=256)


class RecoveryInput(ClosedModel):
    reset_token: SecretStr = Field(min_length=40, max_length=256)
    password: SecretStr = Field(min_length=15, max_length=1024)


class PasswordInput(ClosedModel):
    current_password: SecretStr = Field(min_length=1, max_length=1024)
    new_password: SecretStr = Field(min_length=15, max_length=1024)


def clear_cookie(value):
    response = JSONResponse(value)
    response.delete_cookie(COOKIE, path="/api")
    return response


def session_response(issued):
    response = clear_cookie({k: v for k, v in issued.items() if k != "token"})
    # This service is restricted to local HTTP; off-host deployment/TLS is not supported.
    response.set_cookie(
        COOKIE, issued["token"], httponly=True, samesite="strict", max_age=SESSION_SECONDS, path="/api"
    )
    return response


def attach(app, auth, runtime):
    admin = Administrator(auth)
    router = APIRouter(prefix="/api/v1/auth", tags=["administrator"])

    def source(request):
        return request.client.host if request.client else "unknown"

    @router.get("/status")
    def status():
        return {"setup_required": admin.metadata() is None}

    @router.post("/setup")
    def setup(body: SetupInput, request: Request):
        return session_response(
            admin.setup(
                body.email,
                body.password.get_secret_value(),
                body.bootstrap_token.get_secret_value(),
                source(request),
            )
        )

    @router.post("/login")
    def login(body: LoginInput, request: Request):
        return session_response(admin.login(body.email, body.password.get_secret_value(), source(request)))

    @router.get("/me")
    def me(request: Request):
        principal = auth.require(request, owner=True)
        if principal["kind"] != "session" or principal.get("admin_generation") is None:
            raise RuntimeFault("unauthorized", "Administrator login required")
        return {
            "id": principal["id"],
            "administrator": admin.metadata(),
            "csrf": csrf_for(request.cookies[COOKIE]),
            "request_limits": runtime.limits(),
        }

    @router.post("/logout")
    def logout(request: Request):
        principal = auth.require(request, owner=True)
        if principal["kind"] != "session":
            raise RuntimeFault("forbidden", "Browser session required")
        auth.revoke(principal["id"])
        return clear_cookie({"status": "signed_out"})

    @router.post("/recover")
    def recover(body: RecoveryInput, request: Request):
        return clear_cookie(
            admin.recover(
                body.reset_token.get_secret_value(), body.password.get_secret_value(), source(request)
            )
        )

    @router.post("/password")
    def password(body: PasswordInput, request: Request):
        return clear_cookie(
            admin.change_password(
                request,
                body.current_password.get_secret_value(),
                body.new_password.get_secret_value(),
                source(request),
            )
        )

    app.include_router(router)
