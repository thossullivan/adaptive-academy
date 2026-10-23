"""Frontend constants that mirror backend rules must not drift apart."""

import re
from pathlib import Path

from adaptive_academy.engine.gates import ARTIFACT_THRESHOLD

COMPETENCE_TS = Path(__file__).resolve().parents[1] / "frontend/src/lib/competence.ts"


def test_milestone_artifact_threshold_matches_the_gate():
    match = re.search(r"export const MILESTONE_ARTIFACT = ([0-9.]+);", COMPETENCE_TS.read_text())
    assert match, "MILESTONE_ARTIFACT not found in competence.ts"
    assert float(match.group(1)) == ARTIFACT_THRESHOLD


def test_grading_strictness_levels_match_the_prompt_registry():
    from adaptive_academy.prompts import GRADING_STRICTNESS_LEVELS

    types_ts = COMPETENCE_TS.parent / "types.ts"
    match = re.search(r"export type GradingStrictness = ([^;]+);", types_ts.read_text())
    assert match, "GradingStrictness not found in types.ts"
    assert tuple(re.findall(r"'([a-z]+)'", match.group(1))) == GRADING_STRICTNESS_LEVELS


def test_note_size_cap_matches_the_notebook():
    from adaptive_academy.engine.notebook import NOTE_MAX_CHARS

    notebook_ts = COMPETENCE_TS.parent / "notebook.ts"
    match = re.search(r"export const NOTE_MAX_CHARS = (\d+);", notebook_ts.read_text())
    assert match, "NOTE_MAX_CHARS not found in notebook.ts"
    assert int(match.group(1)) == NOTE_MAX_CHARS
