# Avis sync handoff

Updated 2026-09-28. See `docs/scraper-research-safety.md` for the Avis research
procedure and detailed findings.

## Current result

- Cause found (locally, not yet on Avis): Chrome ignores the profile's
  "Continue where you left off" preference written by
  `configure_session_restore`, so a clean close drops session cookies and a
  new tab gets empty sessionStorage. The earlier restoration test put back
  sessionStorage but never the session cookies.
- Fix built: `BrowserPlugin.restore_browser_session` (on for Avis only) passes
  Chrome's `--restore-last-session` to the native sign-in launch and to every
  SeleniumBase launch, and the sync switches to the restored site tab before
  navigating (`select_restored_tab`).
- Verified against a localhost site (session cookie + sessionStorage sign-in):
  the real native Interactive Login flow followed by two chained background
  syncs all stay signed in; with the flag off the same run fails with the
  Avis symptom. Probe scripts live in ignored `scratch/`.
- Earlier work (on main): final error page capture, `datadome` never restored
  from the jar, DataDome block reported as such, native Chrome sign-in.

## Next step

One supervised live test, with the owner's direction: owner runs the native
sign-in from this branch (including MFA) and closes Chrome; immediately run a
background sync; run another sync about an hour later to learn whether Avis's
server expires the session between scheduled syncs. Stop at any security
challenge and ask the owner. Keep credentials, tokens and captures out of Git.
