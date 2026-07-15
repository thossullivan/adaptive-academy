# Security Policy

Adaptive Academy is a **local-first, bring-your-own-key** application: your learning records and
your `ANTHROPIC_API_KEY` stay on your machine. (Each AI call still sends its content to Anthropic's
API — "local-first" refers to *records*, not offline inference.) There is no hosted service and no
telemetry.

## Reporting a vulnerability

Please **do not open a public issue** for security vulnerabilities.

Instead, report privately via GitHub's **[Report a vulnerability](../../security/advisories/new)**
(the "Security" tab → "Report a vulnerability"). This opens a private advisory visible only to you
and the maintainer.

Please include:

- A description of the issue and its impact
- Steps to reproduce (a minimal proof of concept if possible)
- The affected version / commit

You can expect an initial acknowledgment within a few days. Because this is a small,
volunteer-run project, please allow reasonable time for a fix before any public disclosure.

## Scope & good-to-know

- **Secrets:** never commit your `.env` or API key. If you believe a key was exposed in a commit,
  rotate it immediately at the Anthropic console.
- **Artifact fetching** (e.g. shipped-deliverable URLs, arXiv paper ingestion) is deliberately
  SSRF-guarded: https-only, a host allowlist, and public-IP resolution checks. Reports that
  strengthen or bypass these guards are especially welcome.
- **Prompt-injection surfaces:** ingested papers, artifacts, and vault notes are treated as
  untrusted content in the prompts. Findings that defeat those boundaries are in scope.
