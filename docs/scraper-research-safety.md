# Researching a provider login safely

Live research can trigger account lockouts or repeated MFA messages. Use this
procedure whenever a provider requires credentials.

1. Read the issue, screenshots, existing plugin, and any previously sanitized
   fixtures before opening a browser. The owner can provide credentials in a
   temporary file outside the repository, or in an ignored file under
   `internal_docs/` (for example, `internal_docs/provider.env`). If it is inside
   the repository, verify that git ignores it. Read it only in the research
   process; do not print the values, put them in shell arguments, paste them
   into chat, or copy them into tracked files.
2. Use one browser session for the whole login. Before each action, save that
   page's URL, HTML, and a screenshot when useful in a private, ignored
   location. Inspect the form, visible text, and authentication state; choose
   the exact field or button and expected next page before acting. Raw captures
   can contain names, account numbers, tokens, or autofilled credentials. Keep
   them out of git, PRs, shared logs, and chat. Share only sanitized excerpts.
3. Submit each login stage at most once. A username page may lead to a
   password page or directly to verification. After each submission, capture
   and inspect the new page before doing anything else. Do not refresh, reopen
   the login URL, start another browser, or retry after an uncertain result.
   A changed URL alone does not prove sign-in succeeded.
4. At MFA, captcha, verification, or an account-lock page, capture its state
   once and **stop browser actions**. Ask the owner for the current code or to
   complete the challenge. If they provide a code, enter it once in the same
   session and inspect the resulting page. Do not request or trigger another
   code while waiting. If it expires or fails, ask before attempting again.
5. Once the site clearly shows a signed-in state, continue in the same
   session to the rewards page and inspect its HTML. If it returns to login
   or verification, stop and report what happened. Build parsers and tests
   from sanitized fixtures with invented names and account numbers; remove
   private captures when research is done.
6. Background sync must fail with an interactive-login message when its
   session expires; it must not try to solve MFA or repeatedly submit
   credentials. Before committing or updating a PR, inspect the diff and PR
   text for raw captures, personal details, credentials, codes, local paths,
   and temporary research notes.

Avis sync reads only the signed-in Rewards dashboard. Its interactive window
lets the user advance the staged login and enter any verification code. The
plugin does not click sign-in, send a code, or retry a failed challenge.
