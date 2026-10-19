"""Frontend constants that mirror backend rules must not drift apart."""

import re
from pathlib import Path

from adaptive_academy.engine.gates import ARTIFACT_THRESHOLD

COMPETENCE_TS = Path(__file__).resolve().parents[1] / "frontend/src/lib/competence.ts"


def test_milestone_artifact_threshold_matches_the_gate():
    match = re.search(r"export const MILESTONE_ARTIFACT = ([0-9.]+);", COMPETENCE_TS.read_text())
    assert match, "MILESTONE_ARTIFACT not found in competence.ts"
    assert float(match.group(1)) == ARTIFACT_THRESHOLD
