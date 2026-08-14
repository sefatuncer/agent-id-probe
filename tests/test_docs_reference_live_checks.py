"""Every check identifier printed in the documentation must still exist.

This guard is here because the project has now written a check that does not exist into four
separate documents, and every one of them was read by a human afterwards without the error
being seen:

    28 July   the R1 consequence list named C10, deleted that day, and omitted C16-C18 --
              the three checks the first, second and fifth headline candidates rest on
    29 July   the README's check table listed C06 and C10
    29 July   the paper's Table 1 named two deleted checks and omitted three live ones
     5 Aug    `spec-mapping.md` still explained "why C09 and C10 count as opinion"

The last one is the worst of the four. It sits in the document a reviewer opens to audit the
specification anchors, and it presents a check with no anchor -- the reason C10 was deleted --
as evidence that the anchor catalogue is sound.

A prose sentence cannot be held to the code by review, because a stale identifier reads exactly
like a live one. So it is held here instead. The rule is not "never name a deleted check": the
amendment log has to name them, that is what a changelog is for. The rule is that naming one
obliges the same line to say it is gone.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from agentidprobe.models import CheckId

ROOT = Path(__file__).resolve().parents[1]

# Anywhere a reader looks for what the instrument measures. `docs/check-catalogue.md` is
# generated and `docs/decision-rules.md` is frozen, and both are included: generated files have
# been wrong before, and a frozen file is exactly the one nobody re-reads.
DOCUMENTS = sorted((ROOT / "docs").glob("*.md")) + [ROOT / "README.md"]

CHECK_TOKEN = re.compile(r"\bC(\d{2})\b")

# Words that turn a mention into a statement about the past. A line carrying one of these is
# talking about the instrument's history, which the amendment log must be free to do.
#
# English only, as of 13 August 2026. `phase0-findings.md` was the one Turkish document under
# `docs/` and was translated on that date, so the Turkish retirement words this tuple used to
# carry now match nothing. They are removed rather than left as decoration: a guard listing
# tokens that cannot occur reads as though it is checking something it is not.
RETIREMENT_WORDS = ("delete", "deleted", "removed", "remove", "withdrawn", "retired",
                    "no longer", "dropped", "cut")

LIVE = {check.value for check in CheckId}


def _offending_lines(path: Path) -> list[tuple[int, str, str]]:
    """Check identifiers named without their retirement being stated in the same paragraph.

    The window is the paragraph, not the line. Prose here wraps at 100 columns, so a sentence
    reading "It listed C06 and C10, both of which had been deleted" puts the identifier and the
    word that excuses it on different lines, and a line-sized window rejects the correct text.
    A table row is its own paragraph for this purpose, which is what the amendment log needs:
    each row has to carry its own justification rather than inherit one from the row above.
    """
    found: list[tuple[int, str, str]] = []
    lines = path.read_text(encoding="utf-8").splitlines()
    start = 0
    while start < len(lines):
        if not lines[start].strip():
            start += 1
            continue
        end = start
        while (end + 1 < len(lines) and lines[end + 1].strip()
               and not lines[end].lstrip().startswith("|")):
            end += 1
        paragraph = "\n".join(lines[start:end + 1])
        lowered = paragraph.lower()
        if not any(word in lowered for word in RETIREMENT_WORDS):
            for offset, line in enumerate(lines[start:end + 1]):
                for match in CHECK_TOKEN.finditer(line):
                    if match.group(0) not in LIVE:
                        found.append((start + offset + 1, match.group(0), line.strip()))
        start = end + 1
    return found


@pytest.mark.parametrize("path", DOCUMENTS, ids=lambda p: p.name)
def test_documentation_names_no_check_the_instrument_does_not_run(path: Path) -> None:
    offending = _offending_lines(path)
    assert not offending, "\n".join(
        f"{path.relative_to(ROOT).as_posix()}:{number} names {token}, which is not a check the "
        f"instrument runs, without saying it was removed:\n    {text[:160]}"
        for number, token, text in offending
    )


def test_the_guard_would_actually_fire() -> None:
    """A guard nobody has seen fail is a guard nobody knows is connected.

    The fixture pack learned this the hard way on 29 July: its coverage assertion passed
    because the set it compared was empty at both ends.
    """
    scratch = ROOT / "docs" / "check-catalogue.md"
    original = scratch.read_text(encoding="utf-8")
    try:
        scratch.write_text(original + "\nC10 measures document freshness.\n", encoding="utf-8")
        assert _offending_lines(scratch), "the guard did not fire on a planted stale reference"
        scratch.write_text(
            original + "\nC10 was deleted on 28 July 2026; it had no anchor.\n",
            encoding="utf-8",
        )
        assert not _offending_lines(scratch), "the guard fired on a correct historical mention"
    finally:
        scratch.write_text(original, encoding="utf-8")


def test_every_live_check_is_documented_somewhere() -> None:
    """The other direction: a check that runs and is written down nowhere.

    This is the half that actually bit the project -- C16, C17 and C18 were added to the
    instrument and left out of the R1 consequence list, and they carry three of the five
    ranked headline candidates.
    """
    prose = "\n".join(path.read_text(encoding="utf-8") for path in DOCUMENTS)
    missing = sorted(value for value in LIVE if not re.search(rf"\b{value}\b", prose))
    assert not missing, f"checks the instrument runs but no document names: {missing}"
