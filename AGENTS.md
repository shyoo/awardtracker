# 🤖 AI Agent Developer Guidelines (AGENTS.md)

Welcome! This document outlines the mandatory development workflows, branching strategies, and release procedures that all AI coding agents (such as Google Antigravity, OpenCode, Claude Code, etc.) must follow when pair-programming on the **Award Tracker** project.

---

## 1. Git Branching Rule

* **Branching Strategy**: For any new feature development, bug fix, or visual polish, you **must** create a new git branch from `main`.
* **No Direct Commits**: Never commit directly to `main` branch.
* **Creating a Branch**:
  ```bash
  git checkout -b feat-name-here
  ```

---

## 2. Remote Pushing Policy

* **No Premature Pushing**: Do **not** push any commits or branches to the remote repository (`origin`) until the user explicitly requests it.
* **Keep Changes Local**: Keep all code modifications, test executions, and commits entirely local during active development and iteration.

---

## 3. Mandatory "Push to Remote" Workflow

When the user explicitly asks to **"push to remote"** or **"push the branch"**, you must execute the following sequence precisely:

### Step A: Prompt for Version Bump
1. Ask the user: *"Would you like to bump the version number? (yes/no)"*
2. If the user answers **yes**:
   * Read the current version string from [version.txt](version.txt) (e.g. `1.2.9`).
   * Perform an automatic semantic version patch increment (e.g., increment the last digit: `1.2.9` -> `1.2.10`).
   * Write the new version string back to [version.txt](version.txt).
   * Stage the file: `git add version.txt`
   * Commit the version change: `git commit -m "bump: version to v<VERSION>"`

### Step B: Squash Branch Commits
To keep the commit history clean on the main branch, squash all changes in the current feature branch into a single commit before pushing:
1. Find the branching point from `main` using:
   ```bash
   git merge-base main HEAD
   ```
2. Soft reset to that commit hash to stage all work:
   ```bash
   git reset --soft <HASH>
   ```
3. Commit all staged modifications as a single, consolidated commit with a descriptive message (e.g., `feat(jal): add support for JAL Mileage Bank auto-sync and interactive login`).

### Step C: Generate Release Notes (Only if Version Bumped)
> [!IMPORTANT]
> This step is ONLY executed if the user answered **yes** to the version bump in Step A. If the user answered **no**, completely skip this step. Do not modify or create any release notes under `internal_docs`, and do not include or commit any files under `internal_docs` (as they are ignored by `.gitignore`).

1. Create a markdown release note file under the [internal_docs](internal_docs) directory.
2. Name the file exactly `release_notes_v<VERSION>.md` (e.g., `release_notes_v1.2.10.md`).
3. Use the following structured format for the release notes:
   ```markdown
   # Award Tracker v<VERSION>

   Short summary of what this release introduces or fixes.

   ---

   ## 🚀 New Features & Fixes
   - **Feature/Fix Name**: Detail explanation of the change.
   - **Another Update**: More details.

   ---

   ## 📁 Commits in this Release
   * `<COMMIT_HASH>` `<COMMIT_TITLE>`
   ```
4. Stage the release notes:
   ```bash
   git add internal_docs/release_notes_v<VERSION>.md
   ```
5. Amend the commit to bundle the release notes into the single squashed commit:
   ```bash
   git commit --amend --no-edit
   ```

### Step D: Run Release Script Asynchronously
Execute the compilation build script as a background asynchronous process:
* **On Windows**:
  ```powershell
  powershell -ExecutionPolicy Bypass -File release-win.ps1
  ```
* **On macOS**:
  ```bash
  ./release-macos.sh --universal --codesign
  ```
* **Asynchronous Execution**: Launch the command and monitor its status in the background. Do not block the interface synchronously. Provide the user with progress updates.

### Step E: Push to Remote
Once the release script runs successfully, force push the squashed branch to remote:
```bash
git push origin <BRANCH_NAME> --force
```

---

## 🧭 Summary Checklist for Agent
- [ ] Staging and checking out a new branch
- [ ] No remote pushes during coding
- [ ] User requests push -> Ask about version bump
- [ ] Update [version.txt](version.txt) and commit if yes
- [ ] Find merge-base with `main` and squash branch
- [ ] Create `release_notes_v<VERSION>.md` under [internal_docs](internal_docs) and amend it if version was bumped (otherwise skip)
- [ ] Run release script asynchronously based on OS
- [ ] Force push to remote
