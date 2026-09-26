# Researching a provider login safely

Live research can trigger account lockouts or repeated MFA messages. Use this
procedure whenever a provider requires credentials, including Avis.

1. Read existing issue screenshots, saved HTML, logs, and plugin code first.
   Keep credentials out of command output, source files, screenshots, and git.
2. Plan a single browser session and the exact next action before launching it.
   For each page, capture its URL and HTML in a private, ignored location,
   inspect the form and visible text, then decide whether to advance. Mask
   credentials and one-time codes in anything shared or committed.
3. Submit the username and password at most once during initial research.
   Never refresh, reopen the login URL, start a second browser, or retry after
   an uncertain result. A changed URL is not proof of successful sign-in.
4. When an MFA, captcha, verification, or account-lock page appears, capture
   that state once and **stop browser actions**. Ask the account owner for the
   current code or for them to complete the challenge. Do not request another
   code or repeat login while waiting. If the code expires, let the owner
   decide whether another attempt is acceptable.
5. After the owner completes the challenge, inspect the same browser session.
   Navigate to the rewards page only after the site shows clear signed-in
   evidence. If it returns to login or MFA, stop and report what happened.
6. Build and test parsers from saved, sanitized HTML. Background sync must
   fail with an interactive-login message when its session expires; it must
   not try to solve MFA or repeatedly submit credentials.

Avis sync reads only the signed-in Rewards dashboard. Its interactive window
lets the user advance the staged login and enter any verification code. The
plugin does not click sign-in, send a code, or retry a failed challenge.
