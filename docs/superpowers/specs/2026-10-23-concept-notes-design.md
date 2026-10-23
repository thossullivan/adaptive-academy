# Concept notes in one place, synced to Obsidian: design

Status: approved by Tom, 2026-10-23. Builds on the Attempt button (it reads `Attempt` rows).

## Why

The learner's own work is scattered: attempts in tutor transcripts, explanations and teach-backs
in assessment rows, worked solutions in tutor replies. The Obsidian export writes one note per
concept, but only its verdict and a summary. Tom wants the notes to surface in one place, in
the app and in the vault.

## What changes

1. **A notebook per concept.** One view that shows, newest first:
   - **My notes**: free text the learner writes, saved per concept.
   - **My attempts**: accepted attempts (and, marked as such, ones that weren't accepted).
   - **My explanations**: self-explanations, calibration answers, teach-backs, decay recalls,
     with their score and the gaps the grader named.
   - **Worked solutions**: solutions the tutor revealed after an attempt.
   Each item shows its date and where it came from, and links to the place it was made.
2. **Where it shows in the app.** A notes panel on the Tutor page for the current concept, and
   a Notebook page (under Library) listing the topic's concepts that have any notes or work.
   Final placement may change after the design pass.
3. **Synced to the vault.** When a vault is configured, each concept's Markdown note gets a
   managed section between fixed markers:
   `<!-- adaptive-academy:notebook:start -->` and `<!-- adaptive-academy:notebook:end -->`.
   - Anything outside the markers is the learner's and is never changed.
   - The section is rewritten when the learner saves notes, an attempt is accepted, or a graded
     item is recorded, and on the existing export. Writing never blocks or fails the action
     that triggered it: a vault error is logged and shown on the vault status.
   - The existing frontmatter and verdict lines stay. Links use the existing `[[wikilinks]]`.
   - The existing path-safety checks apply.
4. **My notes are the learner's data.** Included in the JSON export and backups. Never sent to
   a model unless the learner asks for it (not in this change).

## Data

- New table `concept_note`: concept_id (PK/FK), body (text), updated_at. Migration with a
  populated-DB test.
- `GET /api/concepts/{id}/notebook` (notes plus work, newest first) and
  `PUT /api/concepts/{id}/note` (save the body; size-capped).

## Tests

Notebook assembly from each source (attempts, assessments by kind, revealed solutions), the
size cap, vault section rewrite preserving outside content (including notes the learner edited
in Obsidian), marker handling when the markers are missing or duplicated, write triggers,
vault errors not failing the action, export/backup. Frontend unit and e2e tests for editing and
viewing; axe with zero violations; no horizontal scroll at 390px.
