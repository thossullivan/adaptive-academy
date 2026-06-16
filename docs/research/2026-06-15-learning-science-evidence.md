---
title: Learning-Science Evidence Base for an Adaptive, Project-Based Learning Tool
created: 2026-06-15
status: living document
purpose: >
  Grounds the pedagogical design of the Adaptive Academy redesign (Assessor,
  CurriculumDirector, Tutor, build-in-public log) in verified evidence from
  adult-learning and science-of-learning research. Findings below were produced
  by an adversarial deep-research pass (fan-out search -> source fetch ->
  3-vote verification, 2/3 refutes to kill a claim) and hand-checked.
companion_to: ../superpowers/specs/2026-06-15-adaptive-academy-redesign.md
provenance:
  - pass 1 (complete): general learning science for advanced adult self-learners
  - pass 2 (complete, §8): 2023-2026 LLM-tutor risks & mitigations
---

# Learning-Science Evidence Base

Evidence grounding for the redesign. Each finding records the **claim**, an
**evidence-strength** rating, the **effect sizes / sources**, and the concrete
**design implications** for three components: the **Assessor**, the
**CurriculumDirector**, and the **reflection / build-in-public log**.

> **How to read strength ratings.** *Strong* = convergent meta-analytic evidence,
> direction and existence robust. *Context-dependent* = real effect, but magnitude
> swings with learner ability, outcome type (surface vs. transfer), or setting
> (lab vs. authentic course). *Contested* = the field actively disputes magnitude
> or operationalization (direction usually still agreed).

---

## TL;DR — the pedagogical spine

For an **advanced adult self-directed learner pursuing deep transfer** (the target
user: experienced engineer learning to build LLMs from scratch), the evidence
supports a **hybrid that leads with artifact-first, generative learning**
(self-explanation, learning-by-teaching, build-in-public) and uses **retrieval +
spacing as a thin, concept-targeted scaffold**, not the main engine.

The single most design-relevant finding is the **expertise-reversal effect**: the
high guidance that helps novices *actively harms experts*. So the core adaptive
variable is **assistance level keyed to estimated prior knowledge** — not
"difficulty." Default to **low-assistance, project-first**, fade scaffolds, and
re-estimate prior knowledge continuously.

---

## 1. Spacing & retrieval practice are the top broad techniques — but their edge attenuates for experts

**Strength: strong (existence/ranking) · context-dependent (magnitude for this learner)**

- Donoghue & Hattie (2021) meta-analysis — 242 studies, 1,619 effects, 169,179
  participants: **Distributed (spaced) practice d=0.85** and **Practice testing
  (retrieval) d=0.74** are the two most effective of ten techniques.
- Dunlosky et al. (2013, *Psychological Science in the Public Interest*) rate both
  **HIGH utility**, generalizing across ages, materials, formats, and long
  retention intervals.
- **Caveat flagged by the 2021 meta-analysis itself:** effects are largest for
  **lower-ability learners** and **surface/factual** outcomes, with explicit
  caution for deep/relational tasks — i.e., the advanced, deep-transfer profile
  here sits at the weak end of this evidence.

Sources: Donoghue & Hattie 2021 (frontiersin.org/.../feduc.2021.581216); Dunlosky
et al. 2013 (sagepub 10.1177/1529100612453266).

**Design implications**
- **Assessor** — schedule *lightweight, spaced* retrieval checks, but aim them at
  **load-bearing conceptual prerequisites** (attention math, backprop,
  tokenization invariants), not trivia.
- **CurriculumDirector** — embed **spaced revisiting** of foundational concepts
  across phases rather than massing them; do not over-index on spacing as the
  primary structuring principle.
- **Reflection log** — periodic **free-recall prompts** ("without looking, explain
  X") convert the log into retrieval practice.

## 2. In authentic STEM courses, spacing/retrieval benefits are small and inconsistent

**Strength: strong (this is the conservative, real-world end of the literature)**

- Murray, Horner & Göbel (2025, *Educational Psychology Review*) math meta-analysis:
  spaced vs. massed **g=0.28** overall (isolated material g=0.43 > course-embedded
  g=0.24); testing-vs-restudy in math **g=0.18 with a CI crossing zero** — not
  robust (7 studies).
- Bego et al. (2024, *Int. J. STEM Education*), nine real courses: significant
  spacing effect on the end-of-course test in **only 2 of 9 courses**; pooled
  effect **+2.06%** (95% CI 0.16–3.97, I²=89%), and **dropping one calculus course
  erased significance**. Cross-discipline generalizability "remains unclear."

Sources: Murray et al. 2025 (springer 10.1007/s10648-025-10035-1); Bego et al. 2024
(springer 10.1186/s40594-024-00468-5).

**Design implications**
- Treat spaced quizzes as **supplementary signal**; weight **authentic artifacts**
  (shippables, explanations) far more heavily in the Assessor's verdicts.
- Don't sell spacing as the product's headline mechanism for an applied build track.

## 3. Self-explanation is a robust, generalizable generative strategy (validates "Feynman")

**Strength: strong for moderate efficacy + generalizability; open on retention/experts**

- Two independent meta-analyses converge: Donoghue & Hattie (2021) **d=0.54**;
  Bisra et al. (2018, *Educational Psychology Review*, 69 effect sizes / 64 reports)
  **g=0.55** (random effects), holding across tasks, subjects, and education levels —
  "a potentially powerful intervention across a range of instructional conditions."
- Dunlosky et al. (2013) rate it **MODERATE** utility (qualified, partly because it
  was under-tested in authentic settings as of 2013).

Sources: Donoghue & Hattie 2021; Bisra et al. 2018 (springer 10.1007/s10648-018-9434-x);
Dunlosky et al. 2013.

**Design implications**
- **Assessor** — use **self-explanation prompts** ("explain *why* this design choice
  works / *why* this gradient flows this way") as a **primary comprehension probe**;
  favor concept-explanation prompts over generic metacognitive ones.
- **Reflection log** — structure build-in-public entries as **self-explanations of
  decisions**, not just status updates.

## 4. Learning-by-teaching (the protégé effect / Feynman) is mechanism-grounded — with a prior-knowledge boundary

**Strength: strong on mechanism + boundary conditions; relative magnitude of sub-parts debated**

- Fiorella (generative-learning theory; **SOI**: select / organize / integrate):
  teaching makes the learner select key info, organize it in working memory, and
  integrate it with prior knowledge. It decomposes into **preparing to teach**,
  **explaining/generating**, and **interacting** (answering questions, spotting
  gaps). The **explaining** and **interacting** parts drive durable gains (held at
  a 1-week delay); mere preparation is weaker.
- **Critical boundary condition:** "learners must have sufficient domain and
  strategic knowledge to make sense of the learning." Not uniformly beneficial —
  depends on prior expertise. **The target learner clears this bar.**

Source: Fiorella, "Learning by Teaching" (unh.edu .../itow-learning-by-teaching-fiorella.pdf).

**Design implications**
- **Reflection / build-in-public log is the highest-leverage feature** — it
  operationalizes *explaining to an audience* + *interaction* (public Q&A, feedback).
- **Assessor** — set a **teaching expectancy** ("you'll explain this publicly") and
  grade the explanation artifact.
- **CurriculumDirector** — schedule **one shippable teaching artifact per phase**
  (blog / repo / talk) — exactly the "🎯 Ship" pattern in the user's own trackers.

## 5. ⭐ Expertise-reversal effect — the cornerstone of adaptivity

**Strength: strong (robust, replicated; magnitude moderated, direction stable)**

- Endres et al. (2025, *Learning and Instruction*) meta-analysis — 176 effect sizes,
  60 studies, 5,924 participants: **low-prior-knowledge learners** learn better from
  **high-assistance (d=+0.505)**; **high-prior-knowledge learners** learn better from
  **low-assistance (d=−0.428)**. The negative sign means **guidance that helps novices
  actively harms experts.**
- **Asymmetry:** adding support for novices matters more than withholding it from
  experts → default to support **only when knowledge level is uncertain**. Grounded
  in cognitive load theory (Kalyuga); corroborated by adaptive-fading work
  (Renkl/Nückles).

Source: Endres et al. 2025 (sciencedirect S0959475225000660).

**Design implications (this is central)**
- **CurriculumDirector** — default to **low-assistance, problem/project-first** tasks
  for this learner; **continuously reassess** prior knowledge (dynamic assessment);
  **fade scaffolds** as expertise grows. Over-scaffolding will *measurably reduce*
  learning.
- **Assessor** — its **prior-knowledge estimate** should directly drive how much
  guidance every other agent surfaces. Resolves "structure vs. autonomy" for an
  expert: **lean autonomy, support on demand.**

## 6. Retrieval + spacing aid long-term retention in adults; calibrate to "desirable difficulty"

**Strength: strong for the effect; extrapolation to complex LLM concepts is an inference**

- Wahlheim et al. (2015, *Memory & Cognition*): repeated **spaced** testing beat a
  single spaced test in **both young and older adults**; retrieval-effort latencies
  matched the **desirable-difficulty** account (more effortful-but-successful
  retrieval → better retention). Caveat: lag alone is a poor proxy for difficulty;
  measure effort directly; older adults benefit somewhat less in absolute terms.

Source: Wahlheim et al. 2015 (PMC4480221).

**Design implications**
- **Assessor** — tune retrieval checks to the **effortful-but-successful** zone
  (not trivial, not impossible) and **space** them.
- **Reflection log** — **delayed** free-recall prompts exploit the same effect.

## 7. Deliberate practice matters — but is far less determinative than claimed

**Strength: contested magnitude; the "don't over-rely on it" prescription is well-supported**

- Macnamara, Hambrick & Oswald (2014, *Psychological Science*) meta-analysis —
  deliberate practice explained **26% of variance for games, 21% music, 18% sports,
  4% education, <1% professions** (last not significant). In education ~96% of
  variance is other factors.
- The 2016 reply to Ericsson reaffirms ~18% for sports (~1% among elite) and calls
  for **multi-factor** theories of expertise.
- **Genuinely contested:** Ericsson disputes the *operationalization* of "deliberate
  practice"; the dispute is about magnitude/definition, not direction.

Sources: Macnamara et al. 2014 (gwern.net/.../2014-macnamara.pdf); Macnamara et al.
2016 reply (purdue.edu .../macnamara-et-al-2016...).

**Design implications**
- **CurriculumDirector** — incorporate DP *principles* (focused, effortful,
  feedback-rich practice on weaknesses) but **don't make hour-counting or drills the
  primary path**; emphasize varied authentic project work + feedback + reflection.
- **Assessor** — deliver **specific, immediate, targeted feedback on identified
  weaknesses** (the mechanism DP shares with everything that works).

---

## Caveats & scope limits (carry these into design)

1. The strongest "high-utility" ratings for spacing/retrieval come overwhelmingly
   from **surface/factual outcomes and lower-ability learners** — the opposite of
   this user. Treat headline effect sizes as **upper bounds** that likely attenuate.
2. **Authentic course-embedded** STEM evidence (Bego 2024; Murray 2025) shows
   spacing/retrieval benefits are small and inconsistent — far weaker than lab.
3. Deliberate-practice variance figures are from a **contested** literature
   (Macnamara vs. Ericsson); reported here is the Macnamara side.
4. Desirable-difficulty/retrieval evidence (Wahlheim 2015) is **lab word-pair
   material**; applying it to complex LLM concepts is an extrapolation.
5. Self-explanation / learning-by-teaching meta-analyses note **open questions** on
   whether magnitudes hold for experts and over delays.

## Refuted / excluded (do NOT use)

- ❌ "High-ability learners show near-zero or negative effects (d=−0.11) from these
  techniques, so the effect sizes won't transfer to an expert." **Refuted 0–3** in
  verification — excluded. (Experts still benefit from generative techniques; the
  *expertise-reversal* nuance is specifically about **instructional guidance level**,
  not about generative strategies failing for experts.)
- For the record (not in scope but relevant): **learning styles** remain **debunked**;
  the **testing effect** remains **robust**.

## Open questions (still being researched)

- **AI tutoring (pass 2, pending):** rigorous 2023–2026 evidence on LLM-tutor /
  ITS effect sizes, **over-reliance / cognitive offloading**, and
  **illusion-of-competence** for adult learners. *Section below to be appended.*
- **Writing-to-learn for experts:** does build-in-public writing *measurably improve*
  expert understanding vs. merely documenting it? Thinly covered so far.
- **Transfer to open-ended engineering tasks:** how much do headline effect sizes for
  spacing/retrieval/self-explanation transfer to building LLMs vs. the factual/exam
  outcomes that dominate the evidence base? Repeatedly flagged as untested.
- **Interleaving:** how to interleave LLM subtopics (math / implementation / theory)
  for an expert is under-evidenced.

---

## 8. AI tutoring (2023–2026) — over-reliance, illusion of competence, mitigations (pass 2)

> **Headline:** the evidence converges on a sharp split between **assisted
> performance** and **durable learning**. LLM tutors reliably boost in-session
> performance but **collapse or reverse durable, unassisted learning when used as an
> answer-engine**. This is the central risk a dogfooded learning tool must design
> against — it is *the* argument for generation-first.
>
> **Population caveat (applies to all of §8):** nearly every primary RCT is K-12 or
> undergraduate; the few adult studies are crowdworkers, **not advanced engineers**.
> Treat the **directions as transferable, the magnitudes as indicative, not guaranteed.**

### 8.1 LLM tutors boost short-term performance — moderate, heterogeneous, not validated for durable transfer

**Strength: strong (short-term existence) · weak/absent (durable transfer, adult experts)**

- 2026 meta-analysis, 35 experimental studies (2022–24, N=4,193): **Hedges g=0.670**
  [0.495, 0.844] vs no-tutor controls ("moderately positive").
- 2025 PRISMA meta-analysis, 68 studies / 337 effects: **SMD=0.45** [0.43, 0.47].
- **Heterogeneity is enormous (I²=95%)** — the pooled number is a broad average, not
  a point prediction. A teacher-involvement moderator: **g=1.426 with** human
  involvement vs **g=0.077 without** — AI's benefit largely collapses when it's the
  sole "teacher." GenAI helps "when used as a cognitive aid, but negatively
  influences [outcomes] in case of over-reliance as a replacement."
- vs **human tutors** (Pardos & Bhandari, *PLOS ONE* 2024, N=274 adults): ChatGPT
  hints produced gains **statistically equivalent** to human-tutor hints — *not*
  superior — and ChatGPT **failed quality checks on 32% of problems.**

> ⚠️ **Integrity note:** a larger same-journal meta-analysis (Wang & Fan, g=0.867)
> was **RETRACTED April 2026** over data-validity concerns. **Do not cite it.** The
> surviving valid source is the g=0.670 article.

Sources: nature.com/s41599-026-07019-z; sciencedirect S1747938X2500051X; PLOS ONE
10.1371/journal.pone.0304013.

### 8.2 ⭐ Over-reliance harms independent performance once AI is removed (the most robust risk finding)

**Strength: strong (replicated across multiple RCTs and populations)**

- **Bastani et al., *PNAS* 2025** (Turkish high-school field RCT, ~1,000 students):
  GPT-4 access raised **practice** grades +48% (unguarded) / +127% (guardrailed), but
  on an **unassisted exam after AI removal, unguarded-GPT students scored 17% WORSE
  than never-access controls.** A crutch effect.
- **Three pooled RCTs** (N=1,222; 2026): independent solve-rate drops of **d=−0.42,
  −0.19, −0.42** once AI was withdrawn (all p≤0.02).
- Shen & Tamkin 2026 RCT: AI-assisted group faster but **worse on knowledge quizzes
  (d=1.7).**

Sources: hamsabastani.github.io/education_llm.pdf; arxiv 2604.04721; nature.com/s41599-026-07019-z.

### 8.3 Mechanism — cognitive offloading / "metacognitive laziness"

**Strength: strong**

- **Barcaui RCT** (*Computers & Education: AI* 2025, N=120): adults who studied with
  ChatGPT scored **57.5% vs 68.5%** (traditional) on a **surprise 45-day retention
  test** — ~11-point deficit, **d=0.68**, robust to ANCOVA on study time. ChatGPT users
  spent **~45% less effort** — and the **harm was worst for highly technical topics.**
- **Fan et al.** (*BJET* 2025, N=117): ChatGPT group improved essay scores but showed
  **no advantage in knowledge gain or transfer**; authors coin **"metacognitive
  laziness."**

Sources: sciencedirect S2590291125010186; arxiv 2412.09315.

### 8.4 Illusion of competence — AI inflates confidence while degrading understanding, and learners are blind to it

**Strength: strong (IOED mechanism robust) · context-transfer to flag**

- Aslanov et al. (PsyArXiv 2024, N=102): receiving ChatGPT explanations **magnified the
  illusion of explanatory depth** — the GPT group **most overestimated** understanding
  *and* produced **objectively worse** explanations than a no-GPT group given identical
  texts.
- In the Bastani field RCT, learners were **metacognitively miscalibrated**: worse-
  performing GPT students **did not perceive** they had learned less.
- Rozenblit & Keil (2002) IOED is well-replicated: self-rated understanding **drops
  significantly once a person is asked to explicate a mechanism.** Chromik et al.
  (ACM IUI 2021): probing collapsed perceived understanding for **63–72%** of users.
  **This drop is the lever the Assessor exploits.**
- Lee et al. (*PNAS Nexus* 2025): when an AI **reports high confidence, users over-trust
  it even when it's wrong** → the tutor must not emit unwarranted confidence.

Sources: osf.io/8psgf_v1; hamsabastani.github.io/education_llm.pdf; ACM 10.1145/3397481.3450644;
pubmed 40417078.

### 8.5 Validated mitigation — withholding answers eradicates harm (necessary, not sufficient)

**Strength: strong (direction) · with an important ceiling caveat**

- In the Bastani RCT, a **guardrailed "GPT Tutor"** (prompted to give step-by-step,
  teacher-designed **hints without revealing the answer**) was used **substantively**
  (attempt-first, ask-for-help) rather than as a crutch, and its negative exam effect
  was **−0.004 — "essentially eradicated."**
- **Critical bound:** the guardrail **only NEUTRALIZED harm; it produced no positive
  durable-learning gain.** → **Withholding answers is necessary to prevent de-skilling
  but not sufficient to produce learning.** It must be paired with mechanisms that
  *force generative effort* — retrieval practice, productive failure, self-explanation
  (see §1, §3, §6).

Source: hamsabastani.github.io/education_llm.pdf.

### 8.6 Design implications (synthesis)

**Tutor (generation-first) — strong direction, tune thresholds empirically:**
- **Default to withholding full solutions.** Require a logged **attempt or
  explanation before any substantive hint.** The crutch/copy mechanism drives the
  −17% / d=−0.42 harms.
- Provide **step-by-step, hint-style scaffolding**, not answers (the pattern that
  eradicated harm). **Gate hints** behind the logged attempt.
- **Fade assistance** across a session/topic — de-skilling surfaces precisely *at AI
  removal*, so build in graduated withdrawal + unassisted retrieval.
- **Optimize for unassisted, delayed performance**, not in-session success (a vanity
  metric). Never emit unwarranted high confidence.

**Assessor (illusion-of-competence detector) — strong direction:**
- **Do not trust self-reported confidence** — learners feel *more* competent while
  learning *less*, and are blind to it.
- Use **self-explanation / explication probes** (collapses IOED for 63–72%) and
  **calibration checks**: elicit a confidence prediction → probe → **surface the gap.**
- Use **delayed / surprise retention + transfer items**, not just immediate post-task
  scores (AI inflates the latter while harming the former).

### 8.7 Open questions (from pass 2)

- Does a *well-designed* generation-first tutor produce **positive** durable gains, or
  only neutralize harm? Best current evidence shows neutralization only.
- Effect sizes & over-reliance dynamics for **adult, advanced, self-directed technical
  learners** specifically — unstudied.
- Best **probe/calibration designs** to detect *and durably correct* IOED without
  adding so much friction it kills engagement.
- Transfer of these findings to **programming / build-from-scratch** learning — the
  corpus is dominated by math/writing/reading.

---

## Source index (pass 1)

| Source | Type | Used for |
|---|---|---|
| Donoghue & Hattie 2021, *Frontiers in Education* | meta-analysis | §1, §3 |
| Dunlosky et al. 2013, *PSPI* | synthesis | §1, §3 |
| Murray, Horner & Göbel 2025, *Educ. Psych. Review* | meta-analysis | §2 |
| Bego et al. 2024, *Int. J. STEM Education* | multi-course meta | §2 |
| Bisra et al. 2018, *Educ. Psych. Review* | meta-analysis | §3 |
| Fiorella (Learning by Teaching), UNH ITOW | theory/synthesis | §4 |
| Endres et al. 2025, *Learning and Instruction* | meta-analysis | §5 |
| Wahlheim et al. 2015, *Memory & Cognition* | RCT (adults) | §6 |
| Macnamara et al. 2014, *Psychological Science* | meta-analysis | §7 |
| Macnamara et al. 2016 (reply to Ericsson) | commentary | §7 |

## Source index (pass 2 — AI tutoring)

| Source | Type | Used for |
|---|---|---|
| 2026 meta-analysis, *Humanities & Social Sci. Comms* (s41599-026-07019-z) | meta-analysis | §8.1, §8.2 |
| 2025 PRISMA meta-analysis (Studies in Educ. Eval., S1747938X2500051X) | meta-analysis | §8.1 |
| Pardos & Bhandari 2024, *PLOS ONE* | RCT (adults) | §8.1 |
| Bastani et al. 2025, *PNAS* (GPT in high school) | field RCT | §8.2, §8.4, §8.5 |
| Pooled RCTs 2026 (arXiv 2604.04721) | RCTs (N=1,222) | §8.2 |
| Barcaui 2025, *Computers & Education: AI* | RCT (45-day retention) | §8.3 |
| Fan et al. 2025, *BJET* ("metacognitive laziness") | RCT | §8.3 |
| Aslanov et al. 2024 (PsyArXiv, IOED-with-AI) | experiment (preprint) | §8.4 |
| Chromik et al. 2021, ACM IUI | experiment | §8.4 |
| Lee et al. 2025, *PNAS Nexus* | experiment | §8.4 |

> **Excluded after verification (do not use):** Wang & Fan g=0.867 meta-analysis
> (RETRACTED Apr 2026); "ChatGPT beats human tutors" (it was equivalence); a specific
> 48% self-explanation-deflation figure from Chromik; a SHAP/Sinha-Kapur IOED
> restatement (refuted 0–3).
