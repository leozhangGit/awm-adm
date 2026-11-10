"""Deterministic generation of owned boundary schemas."""

import json
from pathlib import Path

from .config import AppConfig
from .contracts import SCHEMAS
from .feeds.models import CoverageInput, FeedControl, FeedInput, Reprocess
from .sources.models import BatchInput, ExtractionOutput, JobInput, PolicyInput, Projection, ProjectionInput


def documents():
    result = {}
    for name, model in {
        **SCHEMAS,
        "AppConfig": AppConfig,
        "SourceBatch": BatchInput,
        "SourceJob": JobInput,
        "SourcePolicy": PolicyInput,
        "FactProjection": Projection,
        "ProjectionEpisode": ProjectionInput,
        "SourceExtraction": ExtractionOutput,
        "Feed": FeedInput,
        "FeedControl": FeedControl,
        "FeedReprocess": Reprocess,
        "CoverageTransition": CoverageInput,
    }.items():
        schema = model.model_json_schema()
        schema["$schema"] = "https://json-schema.org/draft/2020-12/schema"
        schema["$id"] = f"urn:awm-adm:m0:{name}"
        result[name + ".schema.json"] = (
            json.dumps(schema, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
        )
    return result


def export_schemas(output: Path, *, check=False):
    expected = documents()
    if check:
        if {p.name for p in output.glob("*.schema.json")} != set(expected):
            raise ValueError("Schema inventory differs")
        for name, content in expected.items():
            if (output / name).read_text() != content:
                raise ValueError(f"Schema drift: {name}")
    else:
        output.mkdir(parents=True, exist_ok=True)
        for name, content in expected.items():
            (output / name).write_text(content)
