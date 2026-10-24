# 🤖 Award Tracker

**Award Tracker** is a secure, private, and 100% local reward portfolio management application. It runs locally as a background tray service on your computer, automatically or interactively synchronizing your point/mile balances, membership tiers, and reward certificate details from major airline, hotel, and credit card loyalty programs.

Unlike traditional cloud-based reward tracking portals that require you to upload your sensitive master credentials to their servers, Award Tracker operates under a **Zero-Knowledge Privacy model**. Your passwords are encrypted locally on your system and never traverse the cloud.

---

## 💡 The Problem Award Tracker Solves

Cloud-based rewards aggregators request your loyalty account login credentials and store them on centralized servers to scan balances. This design presents severe security concerns:
1. **Centralized Data Breach Risks**: If the aggregator is hacked, all your accounts, passwords, and personal details are compromised.
2. **Account Closures**: Automated cloud logins can flag accounts for suspicious IP activity, occasionally leading to account suspensions by major airlines.

### 🛡️ The Local, Free, and Secure Solution
Award Tracker runs entirely on your local machine:
* **AES-256 Local Cryptography**: All passwords and account identifiers are encrypted locally inside a SQLite database using Fernet symmetric encryption.
* **Master Password Unlock Key**: The encryption key is derived directly from a master password *only you* know. We store no cloud backups and have no password recovery option—meaning your data is completely secure and fully under your control.
* **Local Selenium Engines**: Automation tasks run directly on your own computer using standard local network addresses, mirroring normal browser navigation to avoid account lockouts.

---

## 🚀 Core Features

* **Vibrant Dashboard Portfolio**: Summarizes point balances, USD values, membership tiers, and upcoming expiration dates under beautiful card grids.
* **Unified Family Groupings & Categorized View**: Group and organize your reward portfolios cleanly by **Category** (Airlines, Hotels, Credit Cards, Car Rentals), by **Owner/Person** (complete with custom badge colors), or by **Program**. Includes one-click category filter tabs and collapsible sections to declutter large portfolios.
* **Automated Background Syncing**: Quietly executes in the background at custom intervals (e.g. *Every Day*, *Every Week*), cleanly skipping offline or manually-managed portfolios.
* **Guided Interactive Sign-in (4-Step Overlay)**: When a loyalty program requires MFA or a captcha, Award Tracker opens a headed browser window, **pre-fills your ID and password automatically**, and injects a custom floating guide card (`awardtracker-guide-modal`) in the corner. The card walks you through four steps: (1) credentials are pre-filled — don't touch them, (2) click **Sign In / Submit / Continue** yourself, (3) complete any MFA code manually, and (4) once signed in, the tool auto-navigates to your mileage overview and closes the window — hands off!
* **Automatic Daily Database Backup**: Backs up your `awardtracker.db` file automatically at 3:00 AM daily (and on startup if yesterday's backup is missing). Retention window is user-configurable — **Never**, **3**, **7** (default), or **30** days — from the Settings page. Backup files are stored as `awardtracker_backup_YYYYMMDD.db` inside an `AwardTracker/backups/` folder in your OS application data directory.
* **Cross-Platform Native OS Notifications**: Dispatches native notifications locally through the Windows Action Center, macOS Notification Center, or Linux notify-send on app startup, sync start, sync success/failures, and points-expiry warnings.
* **In-App AI Assistant ("Ask AI")**: An interactive chat tab right inside Award Tracker to plan trips, compare redemptions, and ask about balances, certificates, and expirations. Use your own API key (OpenAI, Anthropic, Gemini, or local OpenAI-compatible endpoints) for autonomous tool-driven answers in the app, or use **Free Mode** with ChatGPT, Claude, or Gemini in your browser with zero configuration. Person names are pseudonymized by default, and credentials never leave your device.
* **AI Assistant Access (MCP)**: A read-only Model Context Protocol server lets desktop assistants such as Claude Desktop answer questions about your balances and expirations without ever seeing your credentials. Off by default; turn it on in Settings. See *External AI Assistant Access (MCP)* below.
* **Custom Manual Tracking**: Easily track points from credit cards (Chase, Amex, Citi, Capital One, Wells Fargo) or offline store programs (e.g. "Best Buy points", "Panera rewards"), complete with custom name overrides.

---

## 🎨 Visual Preview

### 1. Main Dashboard
Summarizes balances, equivalent USD valuations, and displays prominent rose warning badges if any account has points expiring within your warning threshold.
![Dashboard Overview By Program](static/screenshots/dashboard_by_program.png)
![Dashboard Overview By Person](static/screenshots/dashboard_by_person.png)

### 2. Guided Interactive Sign-In Overlay
When executing an Interactive Login, Award Tracker launches a visible browser window and injects a helpful assistant overlay directly in the viewport to guide you through MFA or captchas.

### 3. Tracking of points history
Provides a tracking chart that shows points history over the times.
![Account Details](static/screenshots/account_details.png)

### 4. In-App AI Assistant ("Ask AI")
Ask questions in plain English to plan trips, compare redemptions, and receive tailored hotel or flight recommendations based on your actual point balances and elite status tiers.
![Ask AI Assistant](static/screenshots/ask_ai.png)

---

## ✈️ Supported Loyalty Programs

### 💳 Credit Cards & Manual Programs
* American Express Membership Rewards
* Bilt Rewards
* Capital One Miles
* Chase Ultimate Rewards
* Citi ThankYou
* Wells Fargo Rewards
* Any other custom manually-tracked programs

### 🛩️ Airlines
* **Air Canada** (Aeroplan)
* **Alaska Airlines** (Mileage Plan)
* **All Nippon Airways** (ANA Mileage Club)
* **American Airlines** (AAdvantage)
* **Asiana Airlines** (Asiana Club)
* **Avianca** (LifeMiles)
* **British Airways** (Avios)
* **Delta Air Lines** (SkyMiles)
* **EVA Air** (Infinity Mileagelands)
* **Japan Airlines** (JAL Mileage Bank)
* **JetBlue** (TrueBlue)
* **Korean Air** (SKYPASS) — *includes automatic Mileage Validity Batch & Certificate recognition*
* **Southwest Airlines** (Rapid Rewards)
* **United Airlines** (MileagePlus) — *includes automatic United Club One-time pass certificate recognition*
* **Virgin Atlantic** (Flying Club)

> ⚠️ **Voucher & Certificate Support**: Automatic scraping of vouchers, coupons, and certificates is currently supported for **Korean Air SKYPASS** and **United Airlines MileagePlus** (United Club One-time passes). Other programs display an informational notice on their account detail page.

### 🏨 Hotels
* **Caesars Rewards**
* **Hilton Honors**
* **IHG One Rewards**
* **Marriott Bonvoy**
* **World of Hyatt**

### 🚗 Car Rentals
* **Avis Preferred** — points, status, and membership number; interactive sign-in may require a verification code
* **Hertz Gold+ Rewards**

---

## 🛠️ Developer Compilation Guide (macOS & Windows)

If you are a developer and want to clone and compile the application standalone binary:

### 1. Prerequisites
* **Python 3.14+** (Ensure Python is added to your system `PATH`)
* **Git**
* **Google Chrome** (Required for SeleniumBase web automation)

### 2. Local Installation Steps
1. Clone this repository:
   ```bash
   git clone https://github.com/your-username/awardtracker.git
   cd awardtracker
   ```
2. Create and activate a Python virtual environment:
   * **Windows**:
     ```powershell
     python -m venv venv
     .\venv\Scripts\Activate.ps1
     ```
   * **macOS/Linux**:
     ```bash
     python3 -m venv venv
     source venv/bin/activate
     ```
3. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```
4. Perform database migrations and set up the SQLite schema:
   * **Windows**:
     ```powershell
     venv\Scripts\python.exe -m flask db upgrade
     ```
   * **macOS/Linux**:
     ```bash
     python3 -m flask db upgrade
     ```
5. Run the dev server manually:
   * **Windows**:
     ```powershell
     venv\Scripts\python.exe main.py
     ```
     *(Or simply double-click `scripts\run-win.bat`!)*
   * **macOS/Linux**:
     ```bash
     ./scripts/run-macos.sh
     ```

### 3. Standalone Compilation & Release Packaging
We have provided streamlined build and release tools that compile the Flask app, database migrations, static assets, and the tray daemon into standalone binaries and native setup installers:

#### Standalone Binary Compilation
* **Windows**:
  ```powershell
  powershell -ExecutionPolicy Bypass -File scripts\build-win.ps1
  ```
  Generates a standalone binary at `dist/awardtracker.exe` (~42 MB).
* **macOS**:
  ```bash
  ./scripts/build-macos.sh
  ```
  Generates a native app bundle at `dist/AwardTracker.app` (~54 MB) and standalone binary at `dist/awardtracker`.

#### Complete Local Packaging (Setup Installer & Portable Zip)
* **Windows (Setup Wizard)**:
  ```powershell
  powershell -ExecutionPolicy Bypass -File scripts\release-win.ps1
  ```
  Generates a Setup Wizard installer (`dist/awardtracker-win64-setup-v<VERSION>.exe`) and portable zip (`dist/awardtracker-win64-portable-v<VERSION>.zip`).
* **macOS (Disk Image DMG)**:
  By default, this compiles the application bundle for the **local architecture** of the build machine:
  ```bash
  ./scripts/release-macos.sh
  ```
  A Universal 2 package can still be built locally with:
  ```bash
  ./scripts/release-macos.sh --universal
  ```
  > [!IMPORTANT]
  > To package a **Universal 2** release, you **must** use the official Python installer from [Python.org](https://www.python.org/downloads/mac-osx/). The default Python installed via Homebrew lacks Universal2 architecture support and will fail compatibility verification.
  > 
  > The script will automatically locate your official Python installation, set up a dedicated `venv-universal` environment, compile C extensions for both architectures, and merge libraries like `Pillow` into a unified binary.

  Both commands generate a native Drag-and-Drop Disk Image installer (`dist/awardtracker-macos-setup-v<VERSION>.dmg`) and portable zip (`dist/awardtracker-macos-portable-v<VERSION>.zip`).

  Published releases are built by GitHub Actions rather than on a maintainer's
  computer. Each release contains separate `x86_64` (Intel) and `arm64` (Apple
  Silicon) DMG and ZIP assets, so Apple Silicon users do not need Rosetta.

### 4. Running the Tests
To verify all APIs, naming overrides, settings parameters, and plugin infrastructure are fully functional, execute our premium color-coded test runners:
* **Windows**:
  ```powershell
  powershell -ExecutionPolicy Bypass -File scripts\run_tests.ps1
  ```
* **macOS/Linux**:
  ```bash
  ./scripts/run_tests.sh
  ```

---

## 🧭 Beginner's Onboarding Guide

Welcome to Award Tracker! Follow these steps to get started:

### 1. The Taskbar Tray Icon
* When you launch the application, it starts silently in the background. Look for the **Award Tracker Tray Icon** (🤖) in the bottom-right corner of your taskbar (system tray).
* **Right-click the icon** to access controls:
  * **Open Dashboard**: Launches the main web interface in your default browser.
  * **Sync All Now**: Immediately triggers background synchronization.
  * **Exit**: Fully closes the background tray service.

### 2. Master Password Setup
* On your very first launch, the application will guide you through an onboarding slider and prompt you to set a **Master Password**. 
* Choose a strong password. This password will encrypt all your loyalty passwords locally. You will need to type this password to unlock the app when it restarts.

### 3. Adding Your First Account
1. Open the dashboard (via tray menu).
2. Click **Manage People Profiles** to add family profiles (e.g. "John", "Sarah") and choose distinct colors for them.
3. Click **Add Account**:
   * **Automated Sync**: Select a provider (e.g. *United Airlines*), enter your username, password, select the profile owner, and click **Save**.
   * **Manually-Tracked Programs**: Select *Manual Tracking* as the provider, enter your *Custom Program Name* (e.g. *Best Buy points*), and save.
4. Click the **Sync Now** button (🔄) on the card to run a background sync and pull your balances automatically!

### 4. Interactive Login (MFA / Captcha)
If automated sync fails due to MFA, click the **Interactive Login** button (🔒) on the account card or detail page. A Chrome window will open:
1. The tool **pre-fills your ID and password** automatically — do not modify them.
2. Click **Sign In**, **Submit**, or **Continue** yourself.
3. Complete any MFA code or captcha manually.
4. Once signed in, the tool navigates automatically and closes the window — do not interact at that point.

After a successful interactive login, click **Sync Now** to refresh your balance.

### 5. Database Backup
Award Tracker automatically backs up your database daily. To configure the retention window, go to **Settings → Data & Backup** and choose between **Never**, **3**, **7** (default), or **30** days. Backup files are stored in:
* **Windows**: `%APPDATA%/AwardTracker/backups/`
* **macOS**: `~/Library/Application Support/AwardTracker/backups/`

### 6. Debug Mode & Diagnostic Bug Reports

If you experience synchronization issues or sync tasks fail repeatedly due to structural updates on loyalty sites, you can activate **Debug Mode** to gather details for troubleshooting:
* **Enable Debug Mode**: Navigate to **Settings → Diagnostics & Debugging** and check **Enable Diagnostic Debug Mode**. 
* **Privacy Masking (Enabled by default)**: Toggling **Mask Sensitive Information** automatically intercepts and replaces your usernames, passwords, and points balances with `***` across all screenshots, rendered HTML source files, and text logs.
* **Granular Logs & Snapshots**: When Debug Mode is active, Award Tracker creates run-specific folders under `%APPDATA%/AwardTracker/logs/{YYYY-MM-DD}/{timestamp}-{account_id}-{provider}/` containing:
  - `run.log`: A granular step-by-step trace of SeleniumBase actions, including the current browser URL for each step.
  - Sequential screenshots (`.png`) and HTML source dumps (`.html`) of the browser window.
* **Exporting Bug Reports**: Scroll down to **Export Diagnostic Bug Report** in Settings. Select a time window (e.g. *Last attempted sync*, *Last 1 hour*, or *All time*) and export categories:
  - **Include general debug logs**: Packages `awardtracker_debug.log` and all run-specific `run.log` files.
  - **Include HTML source code & page screenshots**: Packages all page screenshots and markup dumps (only available if Debug Mode was enabled, unchecked by default to save bandwidth).
  - Click **Download Diagnostic Zip** to download a compressed report that you can upload directly to GitHub issues for easier developer debugging.

### 7. In-App AI Assistant ("Ask AI")
Award Tracker features a built-in AI assistant accessible from the **Ask AI** navigation tab. Ask questions in natural language like *"I plan to visit Tokyo next week. Please recommend hotels I can stay at with my points, and how many nights they would cover."* or *"What points or certificates expire in the next 90 days?"*.

* **Bring Your Own Key**: Connect OpenAI, Anthropic (Claude), Google Gemini, or an OpenAI-compatible local server (e.g. Ollama, LM Studio, OpenRouter) in the assistant settings panel. The model receives read-only tool calls (`accounts`, `portfolio summary`, `expiring items`) to look up your balances and status tiers and deliver complete, calculated answers right in the chat.
* **Free Mode (Zero Configuration)**: No API key needed. Pick **ChatGPT (free)**, **Claude (free)**, or **Gemini (free)** from the picker. Award Tracker prepares a privacy-safe snapshot of your relevant portfolio data along with your question and opens the web chat with your prompt pre-filled (or copied to your clipboard).
* **Privacy & Pseudonymization**: Data sent to providers is limited strictly to read-only point balances, status tiers, certificates, and expirations. Passwords, usernames, and account numbers are **never** shared. By default, **Pseudonymize names before sending** replaces person names with *Person A*, *Person B*, etc., and restores them automatically when rendering the reply. API keys are encrypted with your master password and never leave your machine.

### 8. External AI Assistant Access (MCP)
Award Tracker includes a read-only [Model Context Protocol](https://modelcontextprotocol.io) server, so desktop AI assistants such as Claude Desktop or Claude Code can answer questions like *"Which of my miles expire in the next 90 days?"* or *"What is Alice's portfolio worth?"*.

* **Tools**: `get_portfolio_summary`, `list_accounts` (filter by person, category or program), `get_account` (certificates, expiration rule, balance history), and `list_expiring`.
* **Read-only and private**: The server opens your database read-only. It never decrypts passwords, starts a sync or opens a browser. Usernames, membership numbers, certificate codes and sync error text are never sent to the assistant. Balances are as fresh as each account's last sync.
* **Off by default**: Open **Settings → AI Assistant Access (MCP)**, check **Allow AI assistants to read my portfolio**, and save. Until you do, every tool call is refused with a message telling the assistant how to enable it. Unchecking it cuts access from the assistant's next request; you do not need to restart the assistant.
* **Setup** (from a source checkout, see the Developer Guide above): add this to your assistant's MCP configuration, e.g. `claude_desktop_config.json`, using absolute paths. When running from a checkout, the Settings card shows this entry with your own paths filled in:
  ```json
  {
    "mcpServers": {
      "awardtracker": {
        "command": "C:/path/to/awardtracker/venv/Scripts/python.exe",
        "args": ["-m", "agent_api"],
        "cwd": "C:/path/to/awardtracker"
      }
    }
  }
  ```
  On macOS, use `venv/bin/python` as the command. If your assistant does not support `cwd`, set `PYTHONPATH` to the repository folder instead. To point at a different database file, add `"--db", "/path/to/awardtracker.db"` to `args`. The packaged installers do not include the MCP server yet.

---

## 🩺 Troubleshooting

### Award Tracker will not start on an Apple Silicon Mac (M1/M2/M3/M4 or newer)

Symptoms include the app quitting immediately, the tray icon never appearing,
or macOS reporting that the application is damaged or cannot be opened. First
confirm that you installed the release asset containing **`macos-arm64`**. It
runs natively on Apple Silicon and does not require Rosetta 2.

Older releases and assets containing **`macos-x86_64`** are Intel builds. They
can run on Apple Silicon only when Rosetta 2 is installed:

Install Rosetta 2 from Terminal, then relaunch Award Tracker:

```bash
softwareupdate --install-rosetta
```

Add `--agree-to-license` to skip the interactive license prompt:

```bash
softwareupdate --install-rosetta --agree-to-license
```

The installation only has to be done once per Mac. Prefer the native `arm64`
asset for current releases; use Rosetta only for a legacy Intel-only release.
If Award Tracker still does not start, check the log file listed under *A
provider keeps failing to sync* below.

### Sync fails on a Mac with "Bad CPU type in executable"

On Apple Silicon, SeleniumBase normally drives Chrome with an Intel build of
chromedriver that runs through Rosetta 2. If Rosetta is not installed, or a
macOS upgrade removed it, every sync fails with `[Errno 86] Bad CPU type in
executable: '.../seleniumbase/drivers/uc_driver'`.

Current releases detect this and install a native Apple Silicon driver that
matches your Chrome version, so the next sync should work without extra
steps. The first sync after starting Award Tracker or updating Chrome
downloads the matching driver, so it needs an internet connection. If the error persists, install Rosetta 2
(`softwareupdate --install-rosetta --agree-to-license`) and check the log file
listed under *A provider keeps failing to sync* below for a line starting
with `Could not install a native uc_driver`.

### Google Chrome cannot be found or a browser window will not open

Award Tracker uses Google Chrome for account synchronization and interactive
login. Install the current version of [Google Chrome](https://www.google.com/chrome/)
and restart Award Tracker. If Chrome is already installed, close all Chrome
windows and start Award Tracker again. Be sure to run Award Tracker from the
same Windows or macOS user account where Chrome is installed.

### A sync fails because the provider requires MFA, a captcha, or another login step

Use **Interactive Login** (the 🔒 button) for the affected account. Let Award
Tracker fill in the credentials, then submit the login form and complete any MFA
or captcha yourself. After the site finishes signing you in, Award Tracker
captures the session for later automated syncs. If the session expires or the
provider asks you to sign in again, repeat Interactive Login.

### A provider keeps failing to sync

Loyalty-program websites can change without notice. Enable **Diagnostic Debug
Mode** under **Settings → Diagnostics & Debugging**, reproduce the problem, and
then use **Export Diagnostic Bug Report** to download a zip file for a GitHub
issue. Leave **Mask Sensitive Information** enabled unless a maintainer asks
otherwise.

For manual inspection, the application log is located at:

* **Windows**: `%APPDATA%\AwardTracker\logs\awardtracker_debug.log`
* **macOS**: `~/Library/Application Support/AwardTracker/logs/awardtracker_debug.log`

When Diagnostic Debug Mode is enabled, the same log directory also contains a
dated folder for each browser run with step-by-step logs, screenshots, and HTML
snapshots. Include the relevant diagnostic zip or log details when reporting an
issue.

---

## 📄 License

Award Tracker is licensed under the [Apache License, Version 2.0](LICENSE).
See [NOTICE](NOTICE) for attribution. Unless you state otherwise, any
contribution you submit for inclusion in this project is licensed under the
same terms, as described in section 5 of the license.
