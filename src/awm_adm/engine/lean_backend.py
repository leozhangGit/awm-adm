"""Pinned Lean kernel checking of generated, data-only invariant certificates.

Never accepts provider Lean source, imports, tactics, executables, or reports.
Only numeric table indices are interpolated into an owned proof template.
"""

import os
import re
import subprocess
import tempfile
from pathlib import Path

from .artifacts import digest
from .data import MAX_BYTES
from .errors import InvalidIR, Rejected, ResourceLimit, UnsupportedFeature

LEAN_VERSION = "4.19.0"
TEMPLATE = Path(__file__).with_name("formal") / "Invariant.lean"
TEMPLATE_BYTES = TEMPLATE.read_bytes()
MAX_OUTPUT = 64_000


def render_source(table, initial, invariant):
    """The caller supplies a freshly reified table; validate indices defensively."""
    count = len(table["states"])

    def index(value):
        if type(value) is not int or not 0 <= value < count:
            raise InvalidIR("Invalid formal table index")
        return str(value)

    edges = sorted({(edge["source"], edge["target"]) for edge in table["edges"]})
    pairs = ", ".join(f"({index(s)}, {index(t)})" for s, t in edges)
    inv = ", ".join(index(i) for i in invariant)
    goals = ", ".join(index(i) for i in table["goals"])
    source = (
        TEMPLATE_BYTES.decode("utf-8")
        + f"""
set_option maxRecDepth 4096
set_option maxHeartbeats 2000000
namespace ADM.Instance
def edges : List (Nat × Nat) := [{pairs}]
def inv : List Nat := [{inv}]
def goals : List Nat := [{goals}]
def initial : Nat := {index(initial)}
def edge (s t : Nat) : Prop := (s, t) ∈ edges

theorem starts : initial ∈ inv := by decide
theorem closed : ∀ e ∈ edges, e.1 ∈ inv → e.2 ∈ inv := by decide
theorem excludes : ∀ s ∈ inv, s ∉ goals := by decide

theorem certified {{s : Nat}} (reached : ADM.Reach edge initial s) : s ∉ goals := by
  apply ADM.excludes_goal starts (I := fun s => s ∈ inv) (G := fun s => s ∈ goals) ?_ ?_ reached
  · intro s t inside action
    exact closed (s, t) action inside
  · exact excludes
end ADM.Instance
#print axioms ADM.Instance.certified
"""
    )
    if len(source.encode()) > MAX_BYTES:
        raise ResourceLimit("Generated Lean source exceeds byte limit")
    return source.encode()


class LeanBackend:
    """An explicit, trusted local compiler path; never installed automatically."""

    def __init__(self, executable):
        path = Path(executable).expanduser()
        if not path.is_absolute():
            raise InvalidIR("Lean executable must be an absolute path")
        self.executable = str(path)

    @classmethod
    def from_env(cls):
        path = os.environ.get("AWM_ADM_LEAN")
        return cls(path) if path else None

    def _run(self, arguments, directory, budget):
        # Exclude LEAN_PATH and other import/config overrides. The installed
        # compiler and its bundled Init are explicitly part of the trust base.
        environment = {key: os.environ[key] for key in ("PATH", "SYSTEMROOT", "TMPDIR") if key in os.environ}
        environment["LANG"] = "C.UTF-8"
        with tempfile.TemporaryFile() as output:
            try:
                process = subprocess.Popen(
                    [self.executable, *arguments],
                    cwd=directory,
                    env=environment,
                    stdin=subprocess.DEVNULL,
                    stdout=output,
                    stderr=subprocess.STDOUT,
                )
            except OSError as error:
                raise UnsupportedFeature("Configured Lean executable could not be started") from error
            try:
                while True:
                    budget.tick()
                    if os.fstat(output.fileno()).st_size > MAX_OUTPUT:
                        raise ResourceLimit("Lean diagnostic output exceeds limit")
                    try:
                        process.wait(timeout=min(0.1, budget.remaining_seconds))
                        break
                    except subprocess.TimeoutExpired:
                        continue
                budget.tick()
                if os.fstat(output.fileno()).st_size > MAX_OUTPUT:
                    raise ResourceLimit("Lean diagnostic output exceeds limit")
                output.seek(0)
                return process.returncode, output.read(MAX_OUTPUT + 1).decode("utf-8", errors="replace")
            finally:
                if process.poll() is None:
                    process.kill()
                process.wait()

    def check(self, table, initial, invariant, *, budget):
        source = render_source(table, initial, invariant)
        with tempfile.TemporaryDirectory(prefix="adm-lean-") as directory:
            code, version = self._run(["--version"], directory, budget)
            if code != 0 or not version.startswith(f"Lean (version {LEAN_VERSION},"):
                raise UnsupportedFeature("Lean version is unsupported", required=LEAN_VERSION)
            path = Path(directory) / "Certificate.lean"
            path.write_bytes(source)
            code, output = self._run(["-j1", str(path)], directory, budget)
        if code != 0:
            if any(
                message in output.lower()
                for message in ("heartbeats", "maximum recursion", "out of memory", "memory limit")
            ):
                raise ResourceLimit("Lean proof checking exhausted its computation limits")
            raise Rejected("Lean did not verify the generated certificate", diagnostics=output[:4000])
        # Accept only the expected theorem's axiom audit and no warnings or
        # other messages. In particular sorryAx and native evaluation fail.
        audit = re.fullmatch(r"'ADM\.Instance\.certified' depends on axioms: \[([^\]]*)\]\s*", output)
        no_axioms = output.strip() == "'ADM.Instance.certified' does not depend on any axioms"
        axioms = (
            [] if no_axioms else ([a.strip() for a in audit[1].split(",") if a.strip()] if audit else None)
        )
        if axioms is None or not set(axioms) <= {"propext", "Quot.sound", "Classical.choice"}:
            raise Rejected("Lean output lacks a clean permitted-axiom audit", diagnostics=output[:4000])
        return {
            "identity": "adm-lean-invariant/0.1",
            "guarantee": "lean_kernel",
            "lean_version": LEAN_VERSION,
            "compiler": version.strip(),
            "source_digest": digest(source),
            "template_digest": digest(TEMPLATE_BYTES),
            "theorem": "ADM.Instance.certified",
            "axioms": axioms,
        }
