# Security Policy

Adaptive Academy runs on your own machine with your own API key. Your learning records and your
key stay on your computer. Each AI request still sends its content to Anthropic's API, or through
OpenRouter if you use it. There's no hosted service. There's no telemetry either.

## Reporting a vulnerability

Please **do not open a public issue** for security vulnerabilities.

Report it privately with GitHub's **[Report a vulnerability](../../security/advisories/new)**
button, on the repo's "Security" tab. Only you and the maintainer can see the advisory it opens.

Please include:

- what the issue is and what an attacker could do with it
- how to reproduce it, with a small proof of concept if you have one
- the version or commit you tested

Expect a reply within a few days. This is a one-person project, so please allow time for a fix
before you disclose anything publicly.

## Good to know

Never commit your `.env` or your API key. If a key ends up in a commit, rotate it at once in
your provider's console.

The app fetches links you give it, such as a URL for something you built or an arXiv paper. Those
fetches are guarded against SSRF. Only https is allowed, the host must be on an allowlist, and it
must resolve to a public address. A way around any of these checks is a very useful report.

Papers, fetched pages and your vault notes go into prompts as untrusted content. A prompt
injection that gets past that boundary is in scope.
