"""Neutralize prompt-block delimiters in untrusted text (leaf module: no engine imports)."""


def escape_markers(text: str) -> str:
    """Rewrite `<<<`/`>>>` so learner or document text can never open or close a block."""
    return str(text).replace("<<<", "‹‹‹").replace(">>>", "›››")
