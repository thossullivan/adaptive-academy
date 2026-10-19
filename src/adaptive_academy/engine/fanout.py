"""Shared concurrent fan-out pass for researcher briefs.

One pass = one ThreadPoolExecutor sweep over briefs. Failures are captured per
brief as a legible "ExceptionType: message" string (the full traceback goes to
the server log — the trace events alone proved undiagnosable in live use).
"""

import contextvars
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed

from adaptive_academy.llm.researcher_types import RawSource, ResearcherClient, SearchBrief
from adaptive_academy.llm.usage import BudgetExceededError

logger = logging.getLogger(__name__)

_DETAIL_MAX = 300  # keep AgentEvent.detail legible, not a dumped payload


def fan_out_briefs(
    briefs: list[SearchBrief],
    researcher: ResearcherClient,
    max_workers: int,
) -> tuple[list[list[RawSource]], dict[int, str]]:
    """Run one concurrent search pass. Returns (per-brief sources, failures by index)."""
    per_brief: list[list[RawSource]] = [[] for _ in briefs]
    failures: dict[int, str] = {}
    if briefs:
        with ThreadPoolExecutor(max_workers=max(1, min(max_workers, len(briefs)))) as ex:
            # Each worker runs in a copy of the caller's context so the usage feature label
            # (a contextvar set per API request) follows the call onto the pool thread.
            futures = {
                ex.submit(contextvars.copy_context().run, researcher.search, b): i
                for i, b in enumerate(briefs)
            }
            for fut in as_completed(futures):
                idx = futures[fut]
                try:
                    per_brief[idx] = fut.result()
                except BudgetExceededError:
                    # The daily limit is a stop, not a per-angle failure to retry. Cancel
                    # the angles not yet started so they don't run (and bill) only to be
                    # discarded; calls already in flight can't be stopped and finish.
                    ex.shutdown(wait=False, cancel_futures=True)
                    raise
                except Exception as e:  # noqa: BLE001
                    logger.exception("research subagent failed: %s", briefs[idx].angle)
                    failures[idx] = f"{type(e).__name__}: {e}"[:_DETAIL_MAX]
    return per_brief, failures


def fan_out_with_retry(
    briefs: list[SearchBrief],
    researcher: ResearcherClient,
    max_workers: int,
) -> tuple[list[list[RawSource]], dict[int, str], dict[int, int]]:
    """Fan out, then give failed briefs ONE second-chance pass.

    The SDK's own retries burn out within seconds — inside the very transient
    window (a network blip at fan-out start) that killed the angle in the first
    place. A re-attempt after the first pass completes lands minutes later, when
    the blip has usually passed (observed live: 4/5 angles lost to a transient
    APIConnectionError that was unreproducible minutes later).

    Returns (per-brief sources, still-failed by index, recovered index -> source count).
    """
    per_brief, failures = fan_out_briefs(briefs, researcher, max_workers)
    recovered: dict[int, int] = {}
    if failures:
        retry_idx = sorted(failures)
        retry_per, retry_fail = fan_out_briefs(
            [briefs[i] for i in retry_idx], researcher, max_workers
        )
        for j, i in enumerate(retry_idx):
            if j in retry_fail:
                failures[i] = retry_fail[j]
            else:
                per_brief[i] = retry_per[j]
                recovered[i] = len(retry_per[j])
                del failures[i]
    return per_brief, failures, recovered
