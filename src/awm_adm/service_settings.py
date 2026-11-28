"""Durable installation limits; changes never reinterpret captured work or knowledge."""

from pydantic import Field

from .contracts import ClosedModel
from .llm_limits import CallPolicy
from .runtime.protocol import RuntimeFault, dumps, loads
from .temporal_evidence.capacity import PREDICATES


class SettingsValues(ClosedModel):
    llm_call: CallPolicy = Field(default_factory=CallPolicy)
    catalog_predicate_limit: int = Field(default=PREDICATES, ge=1, le=PREDICATES, strict=True)


class SettingsUpdate(ClosedModel):
    expected_revision: int = Field(ge=0, strict=True)
    values: SettingsValues


class ServiceSettings:
    def __init__(self, runtime):
        self.rt, self.store = runtime, runtime.store
        self.defaults = SettingsValues(
            llm_call=runtime.config.llm.call,
            catalog_predicate_limit=runtime.config.sources.catalog_predicate_limit,
        )
        with self.store.lock, self.store.db() as db:
            row = db.execute("SELECT revision,body FROM service_settings WHERE id=1").fetchone()
            self.revision = row["revision"]
            self.has_override = row["body"] is not None
            self.values = SettingsValues.model_validate(loads(row["body"])) if row["body"] else self.defaults
            self._validate(self.values)
            self._apply(self.values)

    def _validate(self, values):
        config = self.rt.config.model_dump()
        config["llm"]["call"] = values.llm_call.model_dump()
        config["sources"]["catalog_predicate_limit"] = values.catalog_predicate_limit
        type(self.rt.config).model_validate(config)

    def _apply(self, values):
        # Replace one immutable policy; startup config and captured work stay intact.
        self.values = values

    @property
    def call(self):
        return self.values.llm_call

    def get(self):
        with self.store.lock:
            return {
                "revision": self.revision,
                "values": self.values.model_dump(),
                "defaults": self.defaults.model_dump(),
            }

    def update(self, source):
        command = SettingsUpdate.model_validate(source)
        with self.store.lock:
            if command.expected_revision != self.revision:
                if command.values == self.values:  # An identical lost-response replay.
                    return self.get()
                raise RuntimeFault("settings_conflict", "Settings changed; reload before saving")
            try:
                self._validate(command.values)
            except ValueError as error:
                raise RuntimeFault("invalid_settings", "Settings exceed supported workflow bounds") from error
            if self.has_override and command.values == self.values:
                return self.get()
            with self.store.db() as db, self.store.transaction(db):
                db.execute(
                    "UPDATE service_settings SET revision=revision+1,body=? WHERE id=1",
                    (dumps(command.values.model_dump()),),
                )
            self.revision += 1
            self.has_override = True
            self._apply(command.values)
            return self.get()
