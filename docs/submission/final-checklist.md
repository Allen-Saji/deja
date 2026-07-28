# Deja submission checklist

Official deadline: August 18, 2026 at 5:00 PM EDT.

India time: August 19, 2026 at 2:30 AM IST.

Official challenge page: https://cockroachdb-ai.devpost.com/

## Eligibility and repository

- [x] Public repository: https://github.com/Allen-Saji/deja
- [x] MIT license detected by GitHub.
- [x] Source, dependency locks, configuration examples, setup, test, and deployment instructions.
- [x] Public commit history.
- [x] Repository description, homepage, and topics set.
- [x] README links to live app and architecture.
- [x] CI passes on `main`.
- [x] No credential found in tracked files or Git history.

## Required technology

- [x] CockroachDB is the persistent memory system.
- [x] CockroachDB Distributed Vector Indexing is implemented with C-SPANN.
- [x] CockroachDB Cloud Managed MCP Server is verified with read-only access.
- [x] AWS Lambda runs the HTTP and asynchronous agent workload.
- [x] Devpost draft explains what the agent does with each required tool.

## Functional demo

- [x] Public app: https://deja-khaki.vercel.app
- [x] Desktop and 375 px mobile layouts pass visual QA.
- [x] Refresh, run selection, and navigation anchors pass browser QA.
- [x] Public API and rendered HTML contain no internal release shorthand.
- [x] Public responses contain no database or provider credential fields.
- [x] Open Graph image, canonical URL, and security headers are live.

## Verification

- [x] Backend lint passes.
- [x] Backend tests pass: 50.
- [x] Dashboard lint, type check, tests, and production build pass.
- [x] Dashboard tests pass: 5.
- [x] Python dependency audit has no known vulnerability.
- [x] Runtime npm dependency audit has no known vulnerability.
- [x] Bandit reports no application finding.
- [x] Gitleaks reports no tracked or historical secret.
- [x] Normal production alert completed.
- [x] Memory replay cited a prior incident.
- [x] Controlled Lambda timeout resumed from `triage`.
- [x] Three-node CockroachDB acceptance completed after one node stopped.
- [x] Managed MCP read-only query verified.

## Known disclosure

- [ ] Recheck the ECR image scan before final submission. The current Amazon Linux base reports
  two High package findings with no fixed package version. Application dependencies are clean.
- [ ] Rebuild on the newest AWS Lambda Python 3.12 base if Amazon publishes fixed packages.

## Video

- [ ] Record from `video-script.md` using `demo-runbook.md`.
- [ ] Keep final duration below 3:00.
- [ ] Name C-SPANN, Managed MCP, and AWS Lambda.
- [ ] Show memory-assisted evidence and timeout recovery.
- [ ] Confirm no credential or local environment detail appears.
- [ ] Upload publicly to YouTube or Vimeo.
- [ ] Test the video URL in a private browser window.

## Devpost form

- [ ] Paste and tighten `devpost.md` for the form fields.
- [ ] Add the public video URL.
- [ ] Add the live app URL.
- [ ] Add the public repository URL.
- [ ] Select Distributed Vector Indexing and Managed MCP Server.
- [ ] Select AWS Lambda.
- [ ] Upload the architecture diagram if the form supports an image.
- [ ] Review the official rules again on submission day.
- [ ] Preview every link while signed out.
- [ ] Submit before August 18, 2026 at 5:00 PM EDT.
- [ ] Save the confirmation page and submission URL.

## Related

- [Devpost draft](devpost.md)
- [Video script](video-script.md)
- [Demo recording runbook](demo-runbook.md)
- [Judging map](judging-map.md)
