# 🤖 AI Agent Developer Guidelines (AGENTS.md)

Welcome! This document collects the domain knowledge AI coding agents (Google
Antigravity, OpenCode, Claude Code, etc.) need when pair-programming on the
**Award Tracker** project: the scraper session-persistence recipe and the
debugging/log layout.

It deliberately does **not** describe how work gets committed, branched, or
landed. That is the harness's job — follow whatever landing instructions your
agent runner gives you.

---

## 1. Push & Release Workflows

Pushing and releasing are defined as skills under [.claude/skills](.claude/skills),
not as prose here. Do not improvise an ad-hoc release procedure.

| Skill | What it does |
| --- | --- |
| [`/push`](.claude/skills/push/SKILL.md) | Runs the full test suite, then pushes the current branch to `origin`. Never bumps the version, never cuts a release. |
| [`/release`](.claude/skills/release/SKILL.md) | Tags an RC for Actions to build as a prerelease, or promotes the verified RC commit with a final tag that becomes **latest**. |

The same skills are available to Antigravity: `.agents/skills` is a directory
junction pointing at `.claude/skills`, so both agents read one source. The link
is not tracked by git — recreate it after a fresh clone with
`scripts/link-antigravity-skills.ps1` (Windows) or
`scripts/link-antigravity-skills.sh` (macOS).

See [docs/release-pipeline.md](docs/release-pipeline.md) for the CI details and
the repository secrets the release workflow needs.

### Pull request write-ups and privacy

Write PR titles and descriptions from a short, sanitized change summary. Never
paste a user request, handoff, log, or browser capture into them. Keep personal
names and email addresses, home or AppData paths, account and membership IDs,
profile or process IDs, credentials, cookies, tokens, and verification codes out
of PR text, branch names, commit messages, and tracked research notes. Use
repository-relative paths and generic descriptions instead.

Before a tool publishes a PR, review its **exact** proposed title and body,
the branch name, the diff (including force-added ignored files), and commit
messages and author metadata. Check how automation derives PR text: a task
title or handoff is not a safe default. If the tool cannot publish sanitized
text at creation, use a supported safe route or surface that limitation before
publishing. Editing a PR or force-pushing later may leave the earlier text or
commits visible in GitHub history. If sensitive details were already published,
remove them from the current PR and report any history that still needs cleanup.

---

## 2. Code Layout

```
app.py                 Flask factory (create_app) + dev-server entry point
main.py                Tray-icon launcher used by the packaged binaries
core/
  config.py            Config, write_dir (user data) and basedir (repo or bundle root)
  versioning.py        App version from AT_RELEASE_VERSION, git describe, or version.txt
  extensions.py        Flask-SQLAlchemy db + Flask-Migrate instances
  models.py            SQLAlchemy models
  security.py          Master-password key derivation + Fernet encryption
  applog.py            Application-wide rotating log (app_log)
  debug_logger.py      Debug-mode run folders, step logs, snapshots, privacy masking
  bootstrap.py         Schema creation, self-healing migrations, provider registration
web/                   HTTP layer: one module per area, each with register(app)
  dashboard.py, accounts.py, sync.py, settings.py, db_admin.py,
  diagnostics.py, certificates.py, auth.py, template_context.py, helpers.py
services/
  sync_service.py      THE sync path: run_plugin -> persist_result, used by the
                       Sync Now form + JSON API, Interactive Login, scheduler, tray
  settings_store.py    Typed access to the key/value Settings table
  scheduler.py         APScheduler jobs (sync-all, daily backup)
  expiration.py        Expiry calculation + expired/critical/warning/safe/at_risk classification
  notifier.py          Native desktop notifications
  updater.py           GitHub release check, download and self-update
  db_manager.py        Database validation, conflict checks, emergency backup, merge-import
scripts/               Build, release, run and test scripts (they cd to the repo root)
packaging/             PyInstaller spec, Inno Setup installer script, app icon
plugins/
  base.py              ProviderPlugin contract, safe_call_plugin_method runner, re-exports
  browser_plugin.py    BrowserPlugin template: shared fetch_data / interactive_login flows
  browser.py           Chrome binary lookup, driver registry + cancel, SeleniumBase patches,
                       guide modal, wait_for_chrome_exit, configure_session_restore
  session.py           Cookie jar, Chrome-locked User-Agent, ResultCache, native Chrome launch
  parsing.py           extract_latest_date, parse_int
  context.py           RunContext (account, plugin, mode, trigger) for the current run
  errors.py            PluginError, InteractionRequiredError
  <provider>.py        One plugin per program
```

Routes use plain `@app.route` inside `register(app)` functions rather than
Blueprints on purpose: endpoint names (`url_for('index')`, ...) stay exactly
as the templates use them.

Every sync -- whichever button or job started it -- goes through
`services.sync_service`. Do not add a second copy of the "apply result to
account" logic in a route or job; extend `persist_result` instead.

---

## 3. Writing a Provider Plugin

Subclass `plugins.browser_plugin.BrowserPlugin` and describe the site; the
base runs both flows and finishes them with the same `scrape()`:

```python
class ExamplePlugin(BrowserPlugin):
    login_url = "https://www.example.com/account"      # form, or dashboard that redirects to it
    username_selector = "input[name='username']"
    page_settle_seconds = 8

    name / plugin_id / default_cpp / homepage_url / logo_domain   # metadata properties

    def is_logged_in(self, sb) -> bool: ...              # strong check: balance or greeting visible
    def fill_login_form(self, sb, username, password, auto_submit=True): ...
    def is_mfa(self, sb) -> bool: ...                     # optional; raises InteractionRequiredError
    def scrape(self, sb) -> dict: ...                     # balance/status/last_activity_date/certificates
    def extract_membership_id(self, sb) -> str | None: ...  # optional; shown + copyable in the UI
```

Attributes select the archetype instead of re-implementing flows:

| Situation | Set |
| --- | --- |
| Anti-bot rejects WebDriver on login (Akamai, hCaptcha) | `interactive_mode = "native"` -- the user's own Chrome is launched on the profile, then a headless session reads the page |
| Auth0-style checks tie the session to the UA | `lock_user_agent = True` |
| Session cookies must survive between SB launches | `use_cookie_jar = True`, `cookie_jar_name = "<id>_cookies.json"` |
| Native sign-in lives in session cookies / the tab's sessionStorage, lost when Chrome closes | `restore_browser_session = True` -- every launch passes `--restore-last-session` and the sync reads the restored tab |
| Site is flaky; scheduled syncs should not flap | `cache_max_age_seconds = 900` (`cache_fallback_on_manual = True` to also serve Sync Now) |

Read `plugins.context.current_run_context()` when behaviour must depend on
*how* the run started (`mode` fetch/interactive, `trigger` manual/scheduled);
never inspect the call stack.

Hilton, United, British Airways and Korean Air are the reference
implementations (assisted, assisted with session-expiry handling, native, and
cache-fallback respectively). Plugins not yet migrated still implement
`fetch_data`/`interactive_login` directly but must use the helpers in
`plugins.session` rather than local copies.

### Session persistence rationale

* **User-Agent lock** (`session.get_consistent_user_agent`): Auth0 and
  similar invalidate a session when the UA differs between the interactive
  login and the later automated sync, so it is pinned to the installed Chrome.
* **JSON cookie jar** (`session.save_cookies_to_json` / `load_cookies_from_json`):
  Chrome automation profiles do not flush session-only cookies to SQLite on
  exit. WebDriver only accepts a cookie for the domain currently loaded, so
  the loader visits each domain (via `/robots.txt` for the domains in
  `cookie_jar_robots_domains`) before injecting.
* **Preferences fix** (`browser.configure_session_restore`, applied to every
  run by `safe_call_plugin_method`): clears Chrome's crashed-exit flags so the
  "didn't shut down correctly" bar does not cover the login form.
* **Process shutdown** (`browser.wait_for_chrome_exit`): waits up to 5 s for
  Chrome on the profile to exit on its own, then kills it and removes the
  `Singleton*` lock files.
* **Native Chrome** (`session.launch_native_chrome`): a normal Chrome process
  with no automation flags or debug port, for sites that flag WebDriver.
  `before_native_login` wipes stale cookies/session-restore first because
  corrupt cookies from a failed attempt are a common cause of captcha loops.

---

## 4. Debugging Guide & Log Locations

For troubleshooting scraper issues, SeleniumBase step-by-step debug outputs, screenshots, and application log files are stored under the user AppData directory:
* **Log Directory**: `%APPDATA%\AwardTracker\logs\` (usually maps to `C:\Users\<Username>\AppData\Roaming\AwardTracker\logs\`).
* **Main Application Log**: `%APPDATA%\AwardTracker\logs\awardtracker_debug.log`.
* **Step-by-step Browser Logs**: Under the daily directory structure, e.g., `%APPDATA%\AwardTracker\logs\YYYY-MM-DD\YYYYMMDD_HHMMSS-<ID>-<Provider_Name>\`.
  * These directories contain sequential HTML page source files (`001_open.html`, etc.) and visual screenshots (`001_open.png`, etc.) for every WebDriver action, which are invaluable for debugging CAPTCHA lockouts, layout shifts, or modal prompt blockers.

### Credentialed browser research

Follow [the provider login research procedure](docs/scraper-research-safety.md)
before using a real account. The owner may supply credentials in a temporary
file outside the repository or in ignored `internal_docs/`. Read that file
privately at runtime; never print its contents, copy it into code, or commit it.
The owner's request to research a provider authorizes one careful login
attempt: inspect each page's HTML before choosing and taking the next action,
including staged username and password pages. Keep captures private and out
of git. At MFA or any verification challenge, stop and ask the owner for the
current code, then continue in the **same** browser session after they respond.
Never refresh, reopen the login URL, resend a code, or retry a failed step
without their direction. Finish by inspecting the authenticated rewards page
and building tests from sanitized fixtures.

---
