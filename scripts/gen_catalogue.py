"""Generate `docs/check-catalogue.md` from the code that actually emits the checks.

Why this script exists
----------------------
The hand-written check table drifted once already. `README.md` listed C06 and C10 -- two
checks that had been deleted from `CheckId` -- and omitted eight that were really running.
A paper that names a check it does not run claims a measurement it did not make, which is
the cheapest possible way to lose a reviewer, and the failure is silent: prose does not
raise when the code beneath it changes.

So the catalogue is derived rather than written:

  * `CheckId`, `FUNNELS` and `DESCRIPTIVE_ONLY` are imported from `agentidprobe.models`,
    so the document is built from the same objects the instrument itself scores with;
  * every emission site is recovered from the abstract syntax tree of `checks_oauth.py`
    and `checks_signed.py`, so a check that is declared but never emitted -- exactly the
    C06/C10 defect -- shows up as such instead of quietly agreeing with a stale paragraph.

Regex was considered and rejected. The `add(...)` calls span lines, sit inside
`for cid in (CheckId.A, CheckId.B): add(cid, ...)` loops that emit several checks at once,
reach the constructor through a `_descriptive(...)` wrapper, and cite `spec_url` through
module-level constants such as `SPEC_MCP`. Each of those is an ordinary question to ask an
AST and each of them defeats a pattern match.

Usage
-----
    python scripts/gen_catalogue.py            # write docs/check-catalogue.md
    python scripts/gen_catalogue.py --check    # print a diff to stderr, exit 1 on drift

Nothing in the output is time-, host- or commit-dependent. That is deliberate: the only
thing that may make `--check` fail is a real change to the instrument, so a red build is
always a fact about the code and never about when it ran.
"""

from __future__ import annotations

import argparse
import ast
import difflib
import sys
from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from agentidprobe.models import (  # noqa: E402
    DESCRIPTIVE_ONLY,
    FUNNELS,
    CheckId,
    NormativeStrength,
)

CATALOGUE = ROOT / "docs" / "check-catalogue.md"

# The modules that construct CheckResult. Anything added here is picked up automatically;
# the emitter *functions* inside them are discovered rather than named (see below).
SOURCES: tuple[Path, ...] = (
    ROOT / "src" / "agentidprobe" / "checks_oauth.py",
    ROOT / "src" / "agentidprobe" / "checks_signed.py",
)

# Bound to names so that `isinstance(node, _FUNCTION_DEFS)` stays a plain tuple test; the
# inline tuple form attracts lint rules that would rewrite it into a PEP 604 union, which
# `isinstance` does not accept for every Python this project supports.
_FUNCTION_DEFS = (ast.FunctionDef, ast.AsyncFunctionDef)
_SEQUENCE_LITERALS = (ast.Tuple, ast.List, ast.Set)

# Strongest first, so a check emitted at several strengths reads in a stable order.
_STRENGTH_ORDER: dict[str, int] = {
    member.value: index for index, member in enumerate(NormativeStrength)
}


@dataclass(frozen=True)
class Emission:
    """One resolved `add(CheckId.X, ..., NormativeStrength.Y, spec_ref=..., ...)` site."""

    check: str          # CheckId member *name*, e.g. PRM_PRESENT
    module: str         # source file basename
    lineno: int
    strength: str       # NormativeStrength value, e.g. "must"
    spec_ref: str
    spec_url: str


def _called_name(func: ast.expr) -> str | None:
    if isinstance(func, ast.Name):
        return func.id
    if isinstance(func, ast.Attribute):
        return func.attr
    return None


def _module_constants(tree: ast.Module) -> dict[str, str]:
    """Module-level `NAME = "literal"` bindings.

    `spec_url=SPEC_RFC9728` is the usual form in the check modules, so without this every
    anchor URL would come out blank.
    """
    constants: dict[str, str] = {}
    for node in tree.body:
        if not isinstance(node, ast.Assign):
            continue
        if not (isinstance(node.value, ast.Constant) and isinstance(node.value.value, str)):
            continue
        for target in node.targets:
            if isinstance(target, ast.Name):
                constants[target.id] = node.value.value
    return constants


def _emitter_functions(tree: ast.Module) -> set[str]:
    """Names of the functions that end up constructing a `CheckResult`.

    Discovered by fixed point rather than hard-coded: `add` builds the result directly and
    `_descriptive` reaches it one hop away, and a future third wrapper would otherwise emit
    checks this catalogue never saw -- the same class of silent omission the script exists
    to prevent.
    """
    definitions = {node.name: node for node in ast.walk(tree)
                   if isinstance(node, _FUNCTION_DEFS)}
    emitters: set[str] = set()
    changed = True
    while changed:
        changed = False
        for name, node in definitions.items():
            if name in emitters:
                continue
            for call in ast.walk(node):
                if not isinstance(call, ast.Call):
                    continue
                target = _called_name(call.func)
                if target == "CheckResult" or (target in emitters and target != name):
                    emitters.add(name)
                    changed = True
                    break
    return emitters


def _checkids(node: ast.expr, env: dict[str, tuple[str, ...]]) -> tuple[str, ...]:
    """Resolve an expression to the `CheckId` members it stands for.

    Three forms occur: the literal `CheckId.X`, a loop variable bound by
    `for cid in (CheckId.A, CheckId.B)`, and the sequence literal itself.
    """
    if (isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name)
            and node.value.id == "CheckId"):
        return (node.attr,)
    if isinstance(node, ast.Name):
        return env.get(node.id, ())
    if isinstance(node, _SEQUENCE_LITERALS):
        return tuple(name for element in node.elts for name in _checkids(element, env))
    return ()


def _enum_member(node: ast.AST, enum_name: str) -> str | None:
    """First `EnumName.MEMBER` attribute anywhere under `node`.

    A subtree search rather than a positional read, because the strength is passed
    positionally by `add(...)` and by `_descriptive(...)` at different indices.
    """
    for sub in ast.walk(node):
        if (isinstance(sub, ast.Attribute) and isinstance(sub.value, ast.Name)
                and sub.value.id == enum_name):
            return sub.attr
    return None


def _string(node: ast.expr | None, constants: dict[str, str]) -> str:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.Name):
        return constants.get(node.id, "")
    return ""


def _emissions(path: Path) -> list[Emission]:
    """Every check emission in one module, with the spec anchor it cites."""
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    constants = _module_constants(tree)
    emitters = _emitter_functions(tree)
    found: list[Emission] = []

    def record(call: ast.Call, env: dict[str, tuple[str, ...]]) -> None:
        if _called_name(call.func) not in emitters or not call.args:
            return
        checks = _checkids(call.args[0], env)
        if not checks:
            # A call inside the emitter itself, where the check id is a parameter. The
            # real site is the caller, which is resolved on its own.
            return

        strength = ""
        for candidate in [*call.args[1:], *(kw.value for kw in call.keywords)]:
            member = _enum_member(candidate, "NormativeStrength")
            if member is not None:
                resolved = NormativeStrength.__members__.get(member)
                strength = resolved.value if resolved is not None else member
                break

        spec_ref = spec_url = ""
        for keyword in call.keywords:
            if keyword.arg == "spec_ref":
                spec_ref = _string(keyword.value, constants)
            elif keyword.arg == "spec_url":
                spec_url = _string(keyword.value, constants)

        for check in checks:
            found.append(
                Emission(check, path.name, call.lineno, strength, spec_ref, spec_url)
            )

    def visit(node: ast.AST, env: dict[str, tuple[str, ...]]) -> None:
        if isinstance(node, ast.Call):
            record(node, env)
        if isinstance(node, ast.For):
            bound = dict(env)
            if isinstance(node.target, ast.Name):
                loop_checks = _checkids(node.iter, env)
                if loop_checks:
                    bound[node.target.id] = loop_checks
            visit(node.iter, env)
            for child in node.body:
                visit(child, bound)
            for child in node.orelse:
                visit(child, env)
            return
        for child in ast.iter_child_nodes(node):
            visit(child, env)

    visit(tree, {})
    return found


def _distinct(values: Iterable[str]) -> list[str]:
    """Non-empty values, deduplicated, first occurrence wins."""
    seen: dict[str, None] = {}
    for value in values:
        if value and value not in seen:
            seen[value] = None
    return list(seen)


def _cell(values: list[str]) -> str:
    if not values:
        return "-"
    return "<br>".join(v.replace("|", r"\|").replace("\n", " ").strip() for v in values)


def _funnel_of(check: CheckId) -> str:
    for modality, stages in FUNNELS.items():
        if any(stage_check is check for _, stage_check in stages):
            return modality.value
    return ""


def render() -> str:
    """The whole document, as a single deterministic string."""
    emissions = [e for path in SOURCES for e in _emissions(path)]
    by_check: dict[str, list[Emission]] = {}
    for emission in emissions:
        by_check.setdefault(emission.check, []).append(emission)

    declared = list(CheckId)
    never_emitted = [c for c in declared if c.name not in by_check]
    undeclared = sorted(n for n in by_check if n not in CheckId.__members__)

    out: list[str] = [
        "<!-- GENERATED - do not edit by hand, run scripts/gen_catalogue.py -->",
        "",
        "# Check catalogue",
        "",
        "**GENERATED - do not edit by hand, run `scripts/gen_catalogue.py`.**",
        "CI runs `python scripts/gen_catalogue.py --check` and fails the build if this file",
        "and the code disagree.",
        "",
        "Every row is recovered from the instrument itself: `CheckId`, `FUNNELS` and",
        "`DESCRIPTIVE_ONLY` from `src/agentidprobe/models.py`, and every emission site from",
        "the abstract syntax tree of the check modules. Nothing here is maintained by hand,",
        "because the hand-maintained version drifted: it once listed two checks that had been",
        "deleted from the code and omitted eight that were running.",
        "",
        "Reading the columns:",
        "",
        "- **Funnel** - the funnel this check is a stage of (`models.FUNNELS`). A check with",
        "  no funnel is still measured and reported; it is simply not a funnel stage.",
        "- **Strength** - every `NormativeStrength` the check is emitted with. More than one",
        "  means different code paths cite different clauses. Decision rule R1 constrains only",
        "  the paths that report a failure, so an `error` or `not_applicable` path may carry a",
        "  strength it never uses.",
        "- **Descriptive-only** - membership of `models.DESCRIPTIVE_ONLY`. These can never",
        "  report a failure: `CheckResult.model_post_init` raises if one tries.",
        "- **Spec anchor** - the `spec_ref` text passed at the call site, verbatim. A blank",
        "  cell means no code path cites a clause, which for a check that can fail is a defect.",
        "- **Emitted in** - source file and number of call sites.",
        "",
        "| ID | Enum member | Funnel | Strength | Descriptive-only | Spec anchor | Spec URL "
        "| Emitted in |",
        "|---|---|---|---|---|---|---|---|",
    ]

    for check in declared:
        sites = by_check.get(check.name, [])
        strengths = sorted(
            _distinct(s.strength for s in sites),
            key=lambda value: _STRENGTH_ORDER.get(value, len(_STRENGTH_ORDER)),
        )
        modality = _funnel_of(check)
        counts = Counter(site.module for site in sites)
        emitted_in = [f"`{module}` x{count}" for module, count in sorted(counts.items())]
        if not sites:
            emitted_in = ["**NOT EMITTED BY ANY CODE PATH**"]
        out.append(
            "| {id} | `{name}` | {funnel} | {strength} | {descriptive} | {ref} | {url} "
            "| {where} |".format(
                id=check.value,
                name=check.name,
                funnel=f"`{modality}`" if modality else "-",
                strength=_cell([f"`{s}`" for s in strengths]),
                descriptive="yes" if check in DESCRIPTIVE_ONLY else "no",
                ref=_cell(_distinct(site.spec_ref for site in sites)),
                url=_cell(_distinct(site.spec_url for site in sites)),
                where=_cell(emitted_in),
            )
        )

    out += ["", "## Funnel order", ""]
    out += [
        "Two funnels scored over disjoint denominators (`models.FUNNELS`). An endpoint using",
        "OAuth-only identity must not be counted as failing a signature check it was never",
        "required to satisfy, so the two are never merged into one rate.",
        "",
    ]
    for modality, stages in FUNNELS.items():
        out += [f"**`{modality.value}`**", ""]
        for position, (label, stage_check) in enumerate(stages, start=1):
            marker = f"`{stage_check.value}`" if stage_check is not None else "(no check)"
            out.append(f"{position}. {marker} - {label}")
        out.append("")

    out += ["## Integrity", ""]
    out.append(
        f"- {len(declared)} checks declared in `CheckId`; "
        f"{len(declared) - len(never_emitted)} emitted by at least one code path."
    )
    out.append(f"- {len(emissions)} emission sites across {len(SOURCES)} modules.")
    if never_emitted:
        out.append(
            "- **Declared but never emitted: "
            + ", ".join(f"{c.value} (`{c.name}`)" for c in never_emitted)
            + ".** This is the C06/C10 defect recurring: delete the enum member or emit it."
        )
    else:
        out.append("- No check is declared without being emitted.")
    if undeclared:
        out.append(
            "- **Emitted but not declared in `CheckId`: " + ", ".join(undeclared) + ".**"
        )
    out.append("")

    return "\n".join(out)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="gen_catalogue.py",
        description="Generate docs/check-catalogue.md from CheckId and the check modules.",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="do not write; print a diff to stderr and exit 1 if the catalogue has drifted",
    )
    args = parser.parse_args(argv)

    # A drift diff must survive being written to a redirected Windows pipe, which defaults
    # to the ANSI code page. Losing the report to a UnicodeEncodeError would hide exactly
    # the failure this script exists to surface.
    for stream in (sys.stdout, sys.stderr):
        stream.reconfigure(errors="backslashreplace")

    generated = render()
    relative = CATALOGUE.relative_to(ROOT).as_posix()

    if not args.check:
        CATALOGUE.parent.mkdir(parents=True, exist_ok=True)
        CATALOGUE.write_text(generated, encoding="utf-8", newline="\n")
        print(f"wrote {relative} ({len(generated.splitlines())} lines)")
        return 0

    if not CATALOGUE.exists():
        print(f"{relative} is missing; run `python scripts/gen_catalogue.py`", file=sys.stderr)
        return 1

    committed = CATALOGUE.read_text(encoding="utf-8").replace("\r\n", "\n")
    if committed == generated:
        print(f"{relative} is in step with the code.")
        return 0

    sys.stderr.writelines(
        difflib.unified_diff(
            committed.splitlines(keepends=True),
            generated.splitlines(keepends=True),
            fromfile=f"{relative} (committed)",
            tofile=f"{relative} (generated from code)",
        )
    )
    print(
        f"\n{relative} has drifted from the code. "
        f"Run `python scripts/gen_catalogue.py` and commit the result.",
        file=sys.stderr,
    )
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
