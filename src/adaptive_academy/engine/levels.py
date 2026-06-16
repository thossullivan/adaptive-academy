from dataclasses import dataclass

from adaptive_academy.models import KnowledgeEstimate

# knowledge level -> (assistance, challenge). Expertise-reversal + ZPD:
# more prior knowledge => LESS assistance and MORE challenge.
_MAP = {
    "low": ("high", "low"),
    "medium": ("medium", "medium"),
    "high": ("low", "high"),
}


@dataclass(frozen=True)
class Levels:
    assistance: str  # "low" | "medium" | "high"
    challenge: str  # "low" | "medium" | "high"


def compute_levels(estimate: KnowledgeEstimate | None) -> Levels:
    # Default (no estimate): assume the expert case — do no harm via over-assistance.
    level = estimate.level if estimate is not None else "high"
    assistance, challenge = _MAP.get(level, ("low", "high"))
    return Levels(assistance=assistance, challenge=challenge)
