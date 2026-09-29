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

- Live test 2026-09-28 (owner signed in with MFA, closed Chrome): plain Chrome
  restored Rewards still signed in; the automated sync then read signed-in
  Rewards in the restored tab, no DataDome block. An earlier attempt that
  was closed before the code was entered stayed signed out, as expected.
- The owner's membership earns United MileagePlus miles, so Rewards shows no
  points gauge. The parser now records 0 Avis points with the partner in
  the status (owner's choice).

## Next step

A sync one hour after the successful one was scheduled to test whether
Avis's server expires an idle session between hourly syncs. If it does,
consider a shorter Avis keep-alive or report the limit in the UI. The full
in-app Interactive Login (native sign-in followed by the automatic read) has
not been repeated live since the fix; confirm it once the branch is in the
installed app.
