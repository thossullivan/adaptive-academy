# Grading eval

Does the grader judge learner answers correctly? Above all, does it avoid the two errors that
cost a learner something? This eval answers that question on a frozen set of hand-written
answers, using the app's own grading code and whichever model the app is configured to use.

It is a manual tool. It never runs in CI, and it calls the model only when you add `--live`.

## The two costly errors

**False mastery.** A weak or wrong answer is recorded at 0.70 or more. The learner is told they
know something they don't. Precisely: the final score (after the app's caps) is at least 0.70
and above the highest score the case's truth allows. That ceiling is the top of the highest
acceptable band (low 0.3, medium 0.7, high 0.9), lowered to 0.70 when the truth says a required
element is missing and to 0.50 when it says a misconception is committed. A cap that brings the
score under 0.70 saves the case; a cap at exactly 0.70 does not.

**False cap.** The grader names a required element as missing when the answer covers it, or a
misconception as committed when the answer does not commit it (for example, when the answer
names it only to reject it). Each named item becomes a recorded gap and a 0.70 or 0.50 ceiling,
so the learner's record says they missed something they did not. It counts even when the score
was already below the ceiling. The report also gives the count on correct answers alone (truth
band high), which is the case the last review batch spent four rounds on.

Both are reported as a count, a rate, and the case ids. A case the model did not answer is never
charged with either; the cell says how many of its cases went unanswered instead.

## What else it measures

| Metric | What it is |
|---|---|
| band accuracy | the final score's band (the app's own mapping: 0.75 and up is high, 0.45 and up is medium, else low) is one of the case's acceptable bands |
| confusion table | truth band (rows) against the recorded band (columns) |
| required elements P/R | precision and recall of `missing_required` against the truth, counted per item over every graded case |
| misconceptions P/R | the same for `misconceptions_committed` |
| invalid output | grades that failed the output checks twice, or were refused or cut off, over all answered attempts. The app records nothing for these |
| cost and latency | per case and in total, from the usage rows the run recorded |

Precision is the false-cap side of the item lists (low precision means items named that were
covered), and recall is the missed-gap side (low recall means real gaps went unnamed).

## The baselines

Four rows use no model. They sit next to the model's row in the printed table and in the report,
so a number is never read alone:

| Row | What it does |
|---|---|
| `always_high_no_caps` | every answer at 0.9, nothing named |
| `always_medium` | every answer at 0.5, nothing named |
| `always_low` | every answer at 0.1, nothing named |
| `cap_everything` | every required element named missing and every misconception committed, then the app's ceilings |

On the frozen set they read as follows. `always_high_no_caps` scores 34 of 34 on false mastery and
0 on false caps. `cap_everything` is nearly the reverse: 52 of 52 false caps, 100% recall on both
item lists at 36% and 12% precision, and still 2 false masteries (two wrong source-quiz answers,
where no misconceptions are sent, so the cap stops at exactly 0.70). `always_medium` and
`always_low` score zero on both costly errors, because they never grade high and never name
anything; they pay for it with 0% recall and 36% and 53% band accuracy. So the costly-error
columns are never enough on their own: a grader that never names a gap and never grades high is
safe and useless. Read them together with item recall and band accuracy, and against these rows.
`always_low`'s 53% also shows that band accuracy alone says little, since many cases are low or
accept low.

## The cases

`cases.jsonl` holds 55 hand-written cases, one JSON object per line. It is frozen: the runner
never writes to it, and a change to it is a change to the eval, so runs before and after are not
comparable. The report records the file's SHA-256.

| Concept | Cases |
|---|---|
| gradient descent | 13 |
| backpropagation | 11 |
| Bayes' theorem | 11 |
| maximum likelihood estimation | 10 |
| L2 regularization | 10 |

| Category | Cases | Truth band |
|---|---|---|
| correct in other notation, wording or spelling (Unicode and ASCII formulas, British spelling, typos, GD/SGD/MLE/NLL, "backprop", a λ/2 convention, other variable names) | 13 | high |
| correct, plain | 3 | high |
| correct, naming a known misconception to reject it | 5 | high |
| fluent, missing a key idea | 5 | medium |
| commits a known misconception | 10 | medium or low |
| partial | 4 | medium |
| wrong but confident | 5 | low |
| very short | 6 | low (some also accept medium) |
| off topic | 2 | low |
| tries to instruct the grader | 2 | low |

45 cases are self-explanations and 10 are source quizzes. A source-quiz case is shaped the way
the app sends one: its key points are both the criteria and the required elements, it sends no
misconceptions, and it carries the reference answer. Its `question` field is for people only;
the app does not send the question to the grader, so the eval does not either.

Each case has `id`, `concept`, `kind`, `category`, `criteria`, `required`, `misconceptions`,
`reference`, `answer`, and `truth`: `band`, optional `also_acceptable` (an adjacent band that is
also defensible), `missing_required` and `misconceptions_committed` (each a subset of what the
case sends, copied exactly), and a one-line `rationale`. A case whose label is a judgement call
has an `unsure` note. `tests/test_grading_eval_cases.py` checks all of this.

### Labels to read with care

Eight cases carry an `unsure` note, and the report lists them in `meta.unsure_case_ids`:

* `gd-very-short-formula` and `mle-very-short`: an element is credited through notation alone
  (`η` in the update, `P(data | θ)`). The prompt says notation counts.
* `bp-very-short-label`, `l2-very-short`, `bayes-very-short`: an element is labelled missing
  although its name appears ("chain rule", "weight decay", "/ evidence"). A grader that credits
  the name loses a little recall and is never charged a false cap.
* `bayes-commits-inverse`: the answer's one error (the posterior is the test's accuracy) matches
  both known misconceptions, the inverse fallacy and dropping the prior, so both are labelled
  committed. The label was corrected after the first live run: it had credited the
  proportionality element because the formula is written out, and had not charged dropping the
  prior. The grader was right on both.
* `gd-quiz-partial-overshoot`: the first key point bundles overshoot with "along steep
  directions". The answer covers overshoot only, so it stays labelled covered, but a grader that
  names it missing for the absent qualifier is within its instructions.
* `bp-fluent-no-stored-activations`: the missing element (stored activations) is a rubric
  detail; whether it should cost the 0.70 cap is the rubric's choice, not the grader's.

### Label leak

The grader sees only what the app would send for a real learner: the concept, the probe kind,
the criteria, the required elements, the known misconceptions, the reference answer (source
quiz) and the answer. The id, category, question, truth and notes never reach the prompt, and a
test renders every frozen case twice (once with its id, truth and notes changed) and requires the
same prompt. Case ids describe their truth (`gd-commits-global-minimum`), which is why they must
never be sent.

Two leaks cannot be closed by a test. The same person wrote the rubric items and the answers, so
an answer may share wording with an item it covers, and a grader that matches words would score
well on those cases without judging meaning. Many correct answers use deliberately different
wording, notation or spelling for that reason, and the false-cap cases on them are the ones to
trust most. Second, the rubric items here are written by hand, while the app generates its own
per concept; a grader that does well on these items may do differently on generated ones.

## How to run it

```
just eval-grading            # prints the cost estimate, then stops
just eval-grading --live     # runs every case
just eval-grading --live --limit 5   # a smoke run on the first five cases
```

`just` loads `.env`, which is where the app's settings live. The eval uses the same ones:
`AA_LLM_BACKEND` (`anthropic`, `openrouter` or `agent_sdk`), `AA_MODEL_REASONING` (the grader
model; blank means the backend's default), the backend's key, `AA_DAILY_BUDGET_USD`, and
`AA_GRADING_STRICTNESS` (the grading level; see [setup](../../docs/SETUP.md#grading-strictness)).
To try another model for one run, set it on the command line:

```
AA_LLM_BACKEND=openrouter AA_MODEL_REASONING=deepseek/deepseek-v4.1-flash-1017 just eval-grading --live
```

To grade one run at another level without changing `.env`, pass `--strictness lenient`,
`--strictness standard` or `--strictness strict`. The runner prints the level it grades at and
where it came from (the option, or `AA_GRADING_STRICTNESS`) under the cost estimate.

Other options: `--cases PATH`, `--out-dir PATH`, and `--scratch-db PATH`.

What the runner does for each case: builds the prompt with the app's `assess.grade_request`,
makes the call through the app's grade gate (`assess.run_grader`: output checks, one
regeneration, rejection), and applies the app's caps (`assess.final_score`). None of that is
copied into the eval, so a change to the prompt or the checks shows up in the next run.

### Where things are written

* Usage rows go to the eval's own SQLite database, `results/usage.db` by default (the path is in
  the report). It is kept between runs, so the daily limit counts every eval run today, and it is
  ignored by git and separate from the app's data. Delete it to start the record over. The runner
  refuses a `--scratch-db` that holds anything but usage rows, so it can never write to the app's
  database.
* The report goes to `results/<timestamp>-<model>.json`. That directory is ignored by git.
* The runner must be its own process (`just eval-grading`): it points the app's database setting
  at the scratch file before it imports the app, and refuses to run if something imported the
  app first.

### The daily limit

With `AA_DAILY_BUDGET_USD` set, the runner refuses to start when the expected cost plus the
eval spend already recorded today in the scratch database is over the limit, and it checks the
limit again before every case, stopping the run (exit code 3) once the recorded spend reaches it.
The client checks it before every call too, so a run can also stop inside a case, on its
regeneration call; that case's first call still counts in the report's cost. Cases it did not
finish are reported as `not_run`. The limit counts the eval's own spend only (every run today on
the same scratch database), not what the app spent today.

## What it costs

The runner prints an estimate before anything else. It counts the prompt's characters (about 3.5
per token) and allows 1,500 output tokens per call for thinking plus the JSON grade, and it
ignores prompt caching, so the real input cost is usually lower. For the 55 cases:

| Model | Expected | At most (every grade regenerated once) |
|---|---|---|
| `claude-sonnet-5-5` | about $0.98 | about $2.14 |
| `deepseek/deepseek-v4.1-flash-1017` (OpenRouter) | price unknown | price unknown |

A model that is not in `llm/pricing.py` gets no dollar estimate, only token counts. On OpenRouter
each call reports what it actually cost, and the report adds those up.

## Latest results

Claude Sonnet 5.5, prompt `assess.grade@v7`, 2026-10-22, all 55 cases:

| Strictness | False mastery | False caps | Band accuracy |
|---|---|---|---|
| lenient | 0/34 | 0/52 | 85% |
| standard (default) | 0/34 | 1/52 | 80% |
| strict | 0/34 | 4/52 | 78% |

The run before the v7 tune (`assess.grade@v6`) had 5 false caps out of 52. DeepSeek V4.1 Flash
on v6, through OpenRouter: 0/34 false mastery, 2/53 false caps, 95% band accuracy, about 2 cents
for the run.

## How to read the report

The printed table puts the model's row above the four baselines. Read the two costly-error
columns first. `3/32 9% (2 unanswered)` means 3 of the 32 answered cases that could be falsely
mastered were, and 2 more cases in that group got no grade at all.

The JSON report has:

* `meta`: model, backend, prompt tag (which names the grading level, for example
  `assess.grade@v7:strict`), the grading level (`strictness`) and where it came from
  (`strictness_source`), the output-check rules, the case file's hash, whether the
  run stopped early and why, the scratch database, the daily limit, and the unsure case ids;
* `estimate`: what the runner printed before it started;
* `metrics`: every metric above for the model, with case ids for both costly errors and the
  items behind each false cap;
* `baselines` and `baseline_notes`: the same metrics for the four baselines;
* `cases`: one entry per case with the grader's raw score, `mechanism_present`, the final score
  and band, the named items, the verdict and gaps, how many calls it took, the output-check
  warnings and events, cost, latency, the truth, and whether it was a false mastery or false cap.

Before acting on a false mastery or false cap, read the case and its verdict. If the label is
wrong, fix the case (and say so in the commit), since the file is the eval.

## Tests

`tests/test_grading_eval_metrics.py` checks every metric on hand-built results, including that
the eval's thresholds match the app's. `tests/test_grading_eval_cases.py` validates the case file.
`tests/test_grading_eval_runner.py` runs the runner end to end with a scripted client: it refuses
without `--live`, sends exactly the app's prompt, applies the app's caps, records usage in the
scratch database only, honours the daily limit, grades at the level `--strictness` or the
setting names, and writes the report. None of them calls a model.
