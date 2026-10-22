"""House style for the public docs, and what may be published under docs/.

The style rules keep reader-facing prose plain: no em or en dashes, no exclamation marks, and
none of the stock words that make text read as generated. Code (fenced blocks and `inline`) is
exempt, since it is quoted, not prose. CODE_OF_CONDUCT.md is the standard Contributor Covenant
text and stays verbatim; the build log under docs/superpowers/ and the evidence base under
docs/research/ are records, not reader-facing prose.
"""

import re
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]

PUBLIC_DOCS = [
    ROOT / name for name in ("README.md", "CONTRIBUTING.md", "SECURITY.md", "ROADMAP.md")
] + sorted((ROOT / "docs").glob("*.md"))

RULES = [
    ("em or en dash", re.compile(r"[—–]")),
    ("exclamation mark", re.compile(r"!(?!\[)")),  # `![alt](img)` is image syntax
    (
        "stock wording",
        re.compile(
            r"\b(delve[sd]?|seamless(ly)?|leverag\w*|cutting-edge|game-?changer|robust|elevate[sd]?"
            r"|tapestry|unleash\w*|empower\w*|supercharg\w*|effortless(ly)?|revolutioni[sz]\w*)\b",
            re.IGNORECASE,
        ),
    ),
]

# Top-level entries allowed under docs/. Anything else is assumed to be working material
# that belongs outside the public repo; add it here on purpose if it is meant to ship.
DOCS_ALLOWLIST = {
    "BACKUP.md",
    "COSTS.md",
    "FIRST_HOUR.md",
    "OVERVIEW.md",
    "RELEASING.md",
    "SETUP.md",
    "images",
    "research",
    "superpowers",
}


def _prose_lines(text: str) -> list[str]:
    """The file's lines with code blanked out, so line numbers still match the file."""
    fenced = re.sub(r"```.*?```", lambda m: "\n" * m.group(0).count("\n"), text, flags=re.S)
    return [re.sub(r"`[^`]*`", "", line) for line in fenced.splitlines()]


@pytest.mark.parametrize("path", PUBLIC_DOCS, ids=lambda p: str(p.relative_to(ROOT)))
def test_public_docs_follow_house_style(path):
    hits = [
        f"{path.relative_to(ROOT)}:{n} [{name}] {line.strip()[:80]}"
        for n, line in enumerate(_prose_lines(path.read_text()), start=1)
        for name, rule in RULES
        if rule.search(line)
    ]
    assert not hits, "house style:\n" + "\n".join(hits)


def test_prose_lines_blank_code_but_keep_line_numbers():
    text = "a — b\n```\nx — y\n```\n`p — q` and r — s\n"
    lines = _prose_lines(text)
    assert len(lines) == len(text.splitlines())
    assert [bool(RULES[0][1].search(line)) for line in lines] == [True, False, False, False, True]


@pytest.mark.skipif(shutil.which("git") is None, reason="needs git")
def test_only_allowlisted_entries_are_tracked_under_docs():
    out = subprocess.run(
        ["git", "ls-files", "docs"], cwd=ROOT, capture_output=True, text=True, check=False
    )
    if out.returncode != 0:
        pytest.skip("not a git checkout")
    tracked = {line.split("/")[1] for line in out.stdout.splitlines() if line.count("/") >= 1}
    unexpected = sorted(tracked - DOCS_ALLOWLIST)
    assert not unexpected, (
        f"docs/{unexpected[0]} is not on the public docs allowlist in tests/test_docs_style.py. "
        "Keep private notes out of the repo, or add it to the list if it is meant to ship."
    )
