# Avis sync handoff

Updated 2026-09-26. See `docs/scraper-research-safety.md` for the Avis research
procedure and detailed findings. The Avis code and research changes are on the
task branch.

## Current result

- Avis regular sync still fails after native Chrome closes. A fresh Rewards
  load previously returned HTTP 401 from `/ido/api/v2/auth/assert`; the cause
  of that response is not proven.
- In a controlled test, 18 deleted session-storage entries from a signed-in
  Rewards tab were restored into a private copy of the Avis Chrome profile.
  The owner saw Rewards signed out or spinning. Chrome kept the recovered
  auth-context entries while open and deleted them again on clean exit.
  Restoration alone is **not** an established fix. The test did not verify
  whether the active tab used the restored storage namespace or record that
  test run's `/ido/api/v2/auth/assert` status.
- The original Avis profile was not modified by the restoration test. No new
  sign-in or MFA occurred during it. The owner reports deleting the private
  test copy.
- The task branch contains final error page capture (HTML and PNG when debug
  logging is enabled), DataDome cookie handling, native Chrome sign-in flow,
  session-loss guidance, and the research findings.

## Next step

Do not implement session-storage restoration from this result. Before another
live attempt, review `AGENTS.md` and the credentialed browser procedure in
`docs/scraper-research-safety.md`. A further sign-in needs the owner's explicit
direction. For that supervised test, keep one browser session open after the
owner completes any MFA, confirm the signed-in Rewards state, and determine
which session-storage namespace the active tab uses. On the subsequent fresh
Rewards load, record the `/ido/api/v2/auth/assert` status and final page
capture. Stop at any security challenge and ask the owner before proceeding.
Keep credentials, tokens, and browser captures out of Git.
