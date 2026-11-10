"""Finite local operating defaults; no environment interpolation or credential loading."""

import tomllib
from pathlib import Path
from typing import Literal, Self

from pydantic import Field, model_validator

from .contracts import CallLimits, ClosedModel, RequestLimits
from .wire import MAX_DOCUMENT_BYTES


class Server(ClosedModel):
    bind_host: Literal["127.0.0.1", "::1"] = "127.0.0.1"
    port: int = Field(default=8080, ge=1024, le=65535)
    max_body_bytes: int = Field(default=2_097_152, ge=1024, le=2_097_152)
    data_dir: str = Field(default=".local/data", min_length=1, max_length=4096)

    @model_validator(mode="after")
    def concrete_path(self) -> Self:
        if (
            "\x00" in self.data_dir
            or ".." in Path(self.data_dir).parts
            or "$" in self.data_dir
            or "~" in self.data_dir
        ):
            raise ValueError("Data path must be explicit, without traversal or environment expansion")
        return self


class RuntimeLimits(ClosedModel):
    max_adms: int = Field(default=10, ge=1, le=100)
    serving_processes: int = Field(default=2, ge=1, le=32)
    background_processes: int = Field(default=1, ge=1, le=16)
    provider_concurrency: int = Field(default=2, ge=1, le=16)
    provider_concurrency_per_adm: int = Field(default=2, ge=1, le=16)
    conversation_check_processes: int = Field(default=1, ge=1, le=4)
    queue_items_per_adm: int = Field(default=1000, ge=1, le=100_000)
    queue_bytes_per_adm: int = Field(default=67_108_864, ge=1024, le=1_073_741_824)
    instance_storage_bytes: int = Field(default=536_870_912, ge=1_048_576, le=107_374_182_400)
    installation_storage_bytes: int = Field(default=5_368_709_120, ge=1_048_576, le=1_099_511_627_776)

    @model_validator(mode="after")
    def nested_limits(self) -> Self:
        if self.provider_concurrency_per_adm > self.provider_concurrency:
            raise ValueError("Per-ADM concurrency exceeds installation limit")
        if (
            self.queue_bytes_per_adm > self.instance_storage_bytes
            or self.instance_storage_bytes > self.installation_storage_bytes
        ):
            raise ValueError("Queue/instance/installation storage limits must be nested")
        return self


class EpisodeLimits(ClosedModel):
    max_calls: int = Field(default=3, ge=1, le=100)
    max_input_tokens: int = Field(default=96_000, ge=1, le=10_000_000)
    max_output_tokens: int = Field(default=24_576, ge=1, le=10_000_000)
    max_work: int = Field(default=6_000_000, ge=1, le=1_000_000_000)
    max_duration_ms: int = Field(default=360_000, ge=1, le=86_400_000)
    no_progress_attempts: int = Field(default=2, ge=1, le=100)
    private_draft_bytes: int = Field(default=2_097_152, ge=1024, le=16_777_216)

    @model_validator(mode="after")
    def useful_stop(self) -> Self:
        if self.no_progress_attempts > self.max_calls:
            raise ValueError("No-progress threshold exceeds episode calls")
        return self


class Quotas(ClosedModel):
    period_seconds: int = Field(default=86_400, ge=60, le=2_592_000)
    calls_per_adm: int = Field(default=20, ge=1, le=100_000)
    calls_installation: int = Field(default=100, ge=1, le=1_000_000)
    input_tokens_per_adm: int = Field(default=640_000, ge=1, le=100_000_000)
    input_tokens_installation: int = Field(default=3_200_000, ge=1, le=1_000_000_000)
    output_tokens_per_adm: int = Field(default=163_840, ge=1, le=100_000_000)
    output_tokens_installation: int = Field(default=819_200, ge=1, le=1_000_000_000)

    @model_validator(mode="after")
    def hierarchy(self) -> Self:
        for prefix in ("calls", "input_tokens", "output_tokens"):
            if getattr(self, prefix + "_per_adm") > getattr(self, prefix + "_installation"):
                raise ValueError("Per-ADM quota exceeds installation quota")
        return self


class Learning(ClosedModel):
    remote_calls_enabled: bool = False
    publication: Literal["review", "checked_auto"] = "review"
    default_conflict_mode: Literal["backward", "forward"] = "backward"
    call: CallLimits = Field(default_factory=CallLimits)
    episode: EpisodeLimits = Field(default_factory=EpisodeLimits)
    quotas: Quotas = Field(default_factory=Quotas)

    @model_validator(mode="after")
    def bounded_hierarchy(self) -> Self:
        for name in ("max_input_tokens", "max_output_tokens", "max_duration_ms"):
            if getattr(self.call, name) > getattr(self.episode, name):
                raise ValueError("Call cap exceeds episode cap")
        for name, quota in (
            ("max_calls", "calls_per_adm"),
            ("max_input_tokens", "input_tokens_per_adm"),
            ("max_output_tokens", "output_tokens_per_adm"),
        ):
            if getattr(self.episode, name) > getattr(self.quotas, quota):
                raise ValueError("Episode cap exceeds per-ADM quota")
        return self


class Sources(ClosedModel):
    batch_items: int = Field(default=100, ge=1, le=1000)
    item_bytes: int = Field(default=262_144, ge=1, le=2_097_152)
    batch_bytes: int = Field(default=2_097_152, ge=1, le=2_097_152)
    max_claims_per_item: int = Field(default=100, ge=1, le=1000)
    projection_entities: int = Field(default=128, ge=1, le=4096)
    projection_intervals: int = Field(default=256, ge=1, le=4096)
    projection_facts: int = Field(default=4096, ge=1, le=65_536)
    feed_enabled_by_default: bool = False

    @model_validator(mode="after")
    def batch_bound(self) -> Self:
        if self.feed_enabled_by_default:
            raise ValueError("Feeds require explicit enablement")
        if self.item_bytes > self.batch_bytes:
            raise ValueError("Single source item exceeds batch limit")
        return self


class Retention(ClosedModel):
    event_days: int = Field(default=30, ge=1, le=3650)
    diagnostic_days: int = Field(default=14, ge=1, le=3650)
    unreferenced_source_days: int = Field(default=90, ge=1, le=3650)
    idempotency_days: int = Field(default=90, ge=1, le=3650)
    automatic_cleanup: bool = False

    @model_validator(mode="after")
    def no_unimplemented_cleanup(self) -> Self:
        if self.automatic_cleanup:
            raise ValueError("Automatic retention is unavailable until dependency-aware cleanup exists")
        return self


class Proof(ClosedModel):
    required_lean_version: Literal["4.19.0"] = "4.19.0"
    lean_executable: str = Field(default="/opt/lean/bin/lean", min_length=1, max_length=4096)
    fallback: Literal["forbidden"] = "forbidden"


class AppConfig(ClosedModel):
    config_profile: Literal["awm-adm-config/2"] = "awm-adm-config/2"
    server: Server = Field(default_factory=Server)
    runtime: RuntimeLimits = Field(default_factory=RuntimeLimits)
    request: RequestLimits = Field(default_factory=RequestLimits)
    learning: Learning = Field(default_factory=Learning)
    sources: Sources = Field(default_factory=Sources)
    retention: Retention = Field(default_factory=Retention)
    proof: Proof = Field(default_factory=Proof)

    @model_validator(mode="after")
    def ingress_bound(self) -> Self:
        if self.sources.batch_bytes > self.server.max_body_bytes:
            raise ValueError("Source batch exceeds HTTP body limit")
        if self.sources.batch_bytes > self.runtime.queue_bytes_per_adm:
            raise ValueError("Source batch exceeds queue capacity")
        return self


def load_config(path: Path | None = None) -> AppConfig:
    if path is None:
        return AppConfig()
    with path.open("rb") as stream:
        raw = stream.read(MAX_DOCUMENT_BYTES + 1)
    if len(raw) > MAX_DOCUMENT_BYTES:
        raise ValueError("Configuration exceeds byte limit")
    return AppConfig.model_validate(tomllib.loads(raw.decode("utf-8")))
