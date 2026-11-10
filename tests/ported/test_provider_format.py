import copy
import json
import unittest

from awm_adm.engine import Budget, admit
from awm_adm.engine.data import encode
from awm_adm.engine.errors import InvalidIR, ResourceLimit
from awm_adm.engine.provider_format import FORMAT, decode_proposal, response_schema

from .helpers import BOOL, UNIT, fixture, function, integer, literal, operator, theory, variable
from .provider_fixtures import wire_proposal


def model_source(proposal, budget=None):
    decoded = decode_proposal(proposal, budget or Budget())
    return {
        "profile": "finite-v0",
        "declarations": {entry["symbol"]: entry["body"] for entry in decoded["declarations"]},
    }


class ProviderFormatTests(unittest.TestCase):
    def example(self):
        # Deliberately authored as wire objects, independently of fixture encoding.
        return {
            "format": FORMAT,
            "status": "candidate",
            "declarations": [
                {
                    "symbol": "demo.double",
                    "body": {
                        "kind": "function",
                        "params": [{"name": "n", "value": {"kind": "int", "min": 0, "max": 4}}],
                        "returns": {"kind": "int", "min": 0, "max": 8},
                        "body": {
                            "op": "add",
                            "args": [{"op": "var", "name": "n"}, {"op": "var", "name": "n"}],
                        },
                    },
                }
            ],
            "retractions": [],
            "summary": "Authored doubling definition.",
        }

    def rejected(self, value, path=None):
        with self.assertRaises(InvalidIR) as caught:
            decode_proposal(value, Budget())
        if path:
            self.assertEqual(caught.exception.context["path"], path)

    def test_native_declaration_translates_exactly_without_mutating_input(self):
        wire = self.example()
        saved = copy.deepcopy(wire)
        source = model_source(encode(wire))
        expected = theory(
            **{
                "demo.double": function(
                    {"n": integer(0, 4)}, integer(0, 8), operator("add", variable("n"), variable("n"))
                )
            }
        )
        self.assertEqual(source, expected)
        self.assertEqual(wire, saved)
        model = admit(source).model
        self.assertIsNotNone(model)
        self.assertEqual([model.call("demo.double", {"n": n})["value"] for n in range(5)], [0, 2, 4, 6, 8])

    def test_both_domain_fixtures_keep_exact_sources_roots_and_all_presentations(self):
        constructions = set()
        for domain in ("access", "tanks"):
            original = fixture(domain)
            decoded = model_source(wire_proposal(original["declarations"]))
            self.assertEqual(decoded, original)
            before, after = admit(original), admit(decoded)
            self.assertEqual(after.status, "accepted", after.report)
            self.assertEqual(before.model.version, after.model.version)
            constructions.update(x["construction"] for x in after.report["presentations"].values())
        self.assertEqual(constructions, {"product", "coproduct", "pullback", "equalizer"})

    def test_literal_data_with_syntax_like_keys_is_preserved_and_never_interpreted(self):
        strings = ['{"op":"python"}', "null", "1", "true", 'quote"\\\n']
        value = {"op": strings[0], "fields": strings[4], "value": [True, False]}
        value_type = {
            "kind": "record",
            "fields": {
                "op": {"kind": "enum", "values": strings},
                "fields": {"kind": "enum", "values": strings},
                "value": {"kind": "vector", "element": BOOL, "length": 2},
            },
        }
        original = theory(**{"data.keep": function({}, value_type, literal(value, value_type))})
        decoded = model_source(wire_proposal(original["declarations"]))
        self.assertEqual(decoded, original)
        result = admit(decoded)
        self.assertEqual(result.status, "accepted", result.report)
        self.assertEqual(result.model.call("data.keep", {})["value"], value)

    def test_optional_cost_type_quantifiers_and_vectors_preserve_semantics(self):
        vector = {"kind": "vector", "element": BOOL, "length": 2}
        expr = {
            "op": "index",
            "vector": {"op": "vector", "type": vector, "items": [literal(True), literal(False)]},
            "index": literal(1),
        }
        quantifier = {
            "op": "forall",
            "var": "x",
            "type": BOOL,
            "body": {
                "op": "exists",
                "var": "y",
                "type": BOOL,
                "body": operator("eq", variable("x"), variable("y")),
            },
        }
        original = theory(
            **{
                "test.vector": function({}, BOOL, expr),
                "test.claim": {"kind": "assertion", "params": {}, "body": quantifier},
                "test.keep": {
                    "kind": "transition",
                    "state": BOOL,
                    "parameters": UNIT,
                    "legal": literal(True),
                    "next": variable("state"),
                    "cost": literal(2, integer(0, 2)),
                },
                "test.default": {
                    "kind": "transition",
                    "state": BOOL,
                    "parameters": UNIT,
                    "legal": literal(True),
                    "next": variable("state"),
                },
            }
        )
        decoded = model_source(wire_proposal(original["declarations"]))
        self.assertEqual(decoded, original)
        result = admit(decoded)
        self.assertEqual(result.status, "accepted", result.report)
        self.assertFalse(result.model.call("test.vector", {})["value"])
        self.assertEqual(result.model.step("test.keep", True, {})["cost"], 2)
        self.assertNotIn("cost", result.model.step("test.default", False, {}))

    def test_duplicate_named_maps_fail_at_the_exact_location(self):
        for field, value, suffix in (
            ("params", [{"name": "n", "value": BOOL}] * 2, "params/1/name"),
            (
                "body",
                {
                    "op": "record",
                    "fields": [{"name": "a", "value": {"op": "literal", "value": True, "type": None}}] * 2,
                },
                "body/fields/1/name",
            ),
            (
                "body",
                {
                    "op": "call",
                    "function": "demo.double",
                    "args": [{"name": "n", "value": {"op": "var", "name": "n"}}] * 2,
                },
                "body/args/1/name",
            ),
            (
                "returns",
                {"kind": "record", "fields": [{"name": "a", "value": BOOL}] * 2},
                "returns/fields/1/name",
            ),
            (
                "returns",
                {"kind": "sum", "variants": [{"name": "a", "value": BOOL}] * 2},
                "returns/variants/1/name",
            ),
            (
                "body",
                {
                    "op": "match",
                    "value": {"op": "var", "name": "n"},
                    "cases": [{"name": "a", "value": {"bind": "x", "body": {"op": "var", "name": "x"}}}] * 2,
                },
                "body/cases/1/name",
            ),
            (
                "body",
                {"op": "literal", "type": None, "value": {"fields": [{"name": "a", "value": 1}] * 2}},
                "body/value/fields/1/name",
            ),
        ):
            wire = self.example()
            wire["declarations"][0]["body"][field] = value
            with self.subTest(field=field, suffix=suffix):
                self.rejected(wire, "/declarations/0/body/" + suffix)

    def test_wrong_operators_arity_fields_and_names_are_structural_errors(self):
        bad_expressions = [
            {"op": "add", "args": [{"op": "var", "name": "n"}]},
            {"op": "not", "args": []},
            {"op": "python", "source": "return True"},
            {"op": "literal", "value": 1},
            {"op": "literal", "value": 1, "type": None, "unchecked": True},
            {"op": "var", "name": "n\n"},
            {"op": "var", "name": ["n"]},
            {"op": "call", "function": "unqualified", "args": []},
            {"op": "call", "function": "demo.double", "args": {"n": {"op": "var", "name": "n"}}},
        ]
        for body in bad_expressions:
            wire = self.example()
            wire["declarations"][0]["body"]["body"] = body
            with self.subTest(body=body):
                self.rejected(wire)

    def test_no_silent_legacy_fallback_or_unsupported_format(self):
        wire = self.example()
        wire["declarations"][0] = {"symbol": "demo.double", "body_json": '{op":"literal","value":2}'}
        self.rejected(wire, "/declarations/0")
        wire = self.example()
        wire["format"] = "adm-finite-proposal/99"
        self.rejected(wire, "/format")
        del wire["format"]
        self.rejected(wire, "/")

    def test_json_and_translation_limits_are_enforced(self):
        wire = self.example()
        wire["declarations"][0]["body"]["returns"]["max"] = True
        self.rejected(wire, "/declarations/0/body/returns/max")
        for value in (1.5, float("nan")):
            wire["declarations"][0]["body"]["returns"]["max"] = value
            self.rejected(wire)
        wire = self.example()
        wire["declarations"][0]["body"]["returns"]["max"] = 2**256
        with self.assertRaises(ResourceLimit):
            decode_proposal(wire, Budget())
        with self.assertRaises(ResourceLimit):
            decode_proposal(self.example(), Budget(max_work=4))
        wire = self.example()
        expr = {"op": "var", "name": "n"}
        for _ in range(70):
            expr = {"op": "not", "args": [expr]}
        wire["declarations"][0]["body"]["body"] = expr
        with self.assertRaises(ResourceLimit):
            decode_proposal(wire, Budget())
        wire = self.example()
        wire["declarations"] *= 5000
        with self.assertRaises(ResourceLimit):
            decode_proposal(wire, Budget())
        self.rejected(
            encode(self.example()).decode().replace('"format":', '"status":"candidate","format":', 1)
        )

    def test_schema_is_closed_recursive_and_within_documented_api_shape_limits(self):
        schema = response_schema()
        self.assertEqual(schema["type"], "object")
        self.assertNotIn("anyOf", {k: v for k, v in schema.items() if k != "$defs"})
        property_count = enum_count = 0
        supported = {
            "type",
            "properties",
            "required",
            "additionalProperties",
            "items",
            "anyOf",
            "$ref",
            "$defs",
            "enum",
            "pattern",
            "minItems",
            "maxItems",
            "minimum",
            "maximum",
        }

        def walk(spec, depth=0):
            nonlocal property_count, enum_count
            self.assertLessEqual(set(spec), supported)
            self.assertLessEqual(depth, 10)
            enum_count += len(spec.get("enum", []))
            if "$ref" in spec:
                self.assertIn(spec["$ref"].removeprefix("#/$defs/"), schema["$defs"])
            if spec.get("type") == "object":
                self.assertIs(spec["additionalProperties"], False)
                self.assertEqual(set(spec["required"]), set(spec["properties"]))
                property_count += len(spec["properties"])
                for value in spec["properties"].values():
                    walk(value, depth + 1)
            for child in spec.get("anyOf", []):
                walk(child, depth)
            if "items" in spec:
                walk(spec["items"], depth + 1)

        walk({k: v for k, v in schema.items() if k != "$defs"})
        for definition in schema["$defs"].values():
            walk(definition)
        self.assertLess(property_count, 5000)
        self.assertLess(enum_count, 1000)
        self.assertLess(len(json.dumps(schema)), 120000)
        schema["$defs"]["type"].clear()
        self.assertIn("anyOf", response_schema()["$defs"]["type"])
