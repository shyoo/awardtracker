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
* **Local Selenium Scrapers**: Scraper tasks run directly on your own computer using standard local network addresses, mirroring normal browser navigation to avoid account lockouts.

---

## 🚀 Core Features

* **Vibrant Dashboard Portfolio**: Summarizes point balances, USD values, membership tiers, and upcoming expiration dates under beautiful card grids.
* **Unified Family Groupings**: Group and organize your reward portfolios cleanly by **Owner/Person** (complete with custom badge colors) or by **Program**.
* **Automated Background Syncing**: Quiety executes in the background at custom intervals (e.g. *Every Day*, *Every Week*), cleanly skipping offline or manually-managed portfolios.
* **Guided Interactive Sign-in (Unified Overlay)**: If a loyalty program prompts you for a Multi-Factor Authentication (MFA) passcode or a captcha screening, Award Tracker opens a headed browser window and injects a custom floating guide card (`awardtracker-guide-modal`) in the corner, guiding you step-by-step to complete the verification manually!
* **Cross-Platform Native OS Notifications**: Dispatches native notifications locally through the Windows Action Center, macOS Notification Center, or Linux notify-send on app startup, sync start, sync success/failures, and points-expiry warnings.
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

---

## ✈️ Supported Loyalty Programs

### 💳 Credit Cards & Manual Programs
* **Offline/Manual Tracking**: Chase Ultimate Rewards, American Express Membership Rewards, Citi ThankYou, Capital One Miles, Wells Fargo Rewards, and any custom manuals.

### 🛩️ Airlines
* **United Airlines** (MileagePlus)
* **American Airlines** (AAdvantage)
* **Delta Air Lines** (SkyMiles)
* **Southwest Airlines** (Rapid Rewards)
* **Alaska Airlines** (Mileage Plan)
* **Korean Air** (SKYPASS)
* **Asiana Airlines** (Asiana Club)
* **Virgin Atlantic** (Flying Club)
* **Avianca** (LifeMiles)

### 🏨 Hotels
* **Marriott Bonvoy**
* **Hilton Honors**
* **World of Hyatt**
* **IHG One Rewards**

---

## 🛠️ Developer Compilation Guide (macOS & Windows)

If you are a developer and want to clone and compile the application standalone binary:

### 1. Prerequisites
* **Python 3.14+** (Ensure Python is added to your system `PATH`)
* **Git**
* **Google Chrome** (Required for SeleniumBase web scrapers)

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
     venv\Scripts\python.exe tray.py
     ```
     *(Or simply double-click the `run.bat` file in the root folder!)*
   * **macOS/Linux**:
     ```bash
     ./run.sh
     ```

### 3. Standalone Compilation & Release Packaging
We have provided streamlined build and release tools that compile the Flask app, database migrations, static assets, and the tray daemon into standalone binaries and native setup installers:

#### Standalone Binary Compilation
* **Windows**:
  ```powershell
  powershell -ExecutionPolicy Bypass -File build-win.ps1
  ```
  Generates a standalone binary at `dist/awardtracker.exe` (~42 MB).
* **macOS**:
  ```bash
  ./build-macos.sh
  ```
  Generates a native app bundle at `dist/AwardTracker.app` (~54 MB) and standalone binary at `dist/awardtracker`.

#### Complete Release Packaging (Setup Installer & Portable Zip)
* **Windows (Setup Wizard)**:
  ```powershell
  powershell -ExecutionPolicy Bypass -File release-win.ps1
  ```
  Generates a Setup Wizard installer (`dist/awardtracker-setup.exe`) and portable zip (`dist/awardtracker-portable.zip`).
* **macOS (Disk Image DMG)**:
  ```bash
  ./release-macos.sh
  ```
  Generates a native Drag-and-Drop Disk Image installer (`dist/awardtracker-MacOs-Setup.dmg`) and portable zip (`dist/awardtracker-macos-portable.zip`).

### 4. Running the Tests
To verify all APIs, naming overrides, settings parameters, and plugin infrastructure are fully functional, execute our premium color-coded test runners:
* **Windows**:
  ```powershell
  powershell -ExecutionPolicy Bypass -File run_tests.ps1
  ```
* **macOS/Linux**:
  ```bash
  ./run_tests.sh
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
2. Click **Manage People & Colors** to add family profiles (e.g. "John", "Sarah") and choose distinct colors for them.
3. Click **Add Account**:
   * **Automated Scrapers**: Select a provider (e.g. *United Airlines*), enter your username, password, select the profile owner, and click **Save**.
   * **Manually-Tracked Programs**: Select *Manual Tracking* as the provider, enter your *Custom Program Name* (e.g. *Best Buy points*), and save.
4. Click the **Sync Now** button (🔄) on the card to run a background sync and pull your balances automatically!
