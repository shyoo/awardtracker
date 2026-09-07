# Release Pipeline

How Award Tracker gets tested, built and shipped, and what has to be configured
for it to work.

## Who does what

| | Local (agent skill) | GitHub Actions |
| --- | --- | --- |
| `/push` | run tests, push branch | `ci.yml` reruns tests on Windows + macOS |
| `/deploy` | bump `version.txt`, write release notes, tag | `release.yml` tests, builds, signs, publishes a prerelease |

Neither skill builds binaries locally. `release-win.ps1` and `release-macos.sh`
still work by hand for local testing, but a shipped release always comes out of
CI.

Landing/branching policy is **not** described here or in `AGENTS.md` — that comes
from whatever agent runner is driving the work.

The skills live in `.claude/skills`. Antigravity reads the same files through
`.agents/skills`, a junction/symlink recreated by
`scripts/link-antigravity-skills.ps1` (Windows) or
`scripts/link-antigravity-skills.sh` (macOS). It is gitignored, so re-run the
script after a fresh clone.

## The release flow

1. `/deploy` bumps `version.txt`, writes
   `docs/release_notes/release_notes_v<V>.md`, commits both as
   `chore(release): v<V>`, and pushes `main` plus the tag `v<V>`.
2. The tag triggers `release.yml`:
   - **test** — full suite on `windows-latest` and `macos-latest`. Everything
     downstream is gated on this.
   - **build-windows** — `release-win.ps1` under `windows-latest`, with Inno
     Setup installed via Chocolatey. Produces the portable ZIP and setup EXE.
     **These are unsigned**, as they have always been; users see a SmartScreen
     warning. Adding a certificate is a later, self-contained change.
   - **build-macos** — a `macos-13` (Intel) + `macos-14` (Apple Silicon) matrix.
     Each leg imports the Developer ID certificate into a throwaway keychain,
     runs `release-macos.sh --codesign`, and notarizes with `notarytool`.
   - **release** — creates the tag's GitHub release as a **prerelease** with the
     notes file as the body and all six assets attached.
3. A human downloads a build, verifies it, and unchecks "This is a pre-release".

Step 3 is the point of the prerelease: `updater.py` queries
`/releases/latest`, which GitHub excludes prereleases from, so no existing
install is offered the new version until a person promotes it.

## macOS architectures and asset naming

CI builds Intel and Apple Silicon on separate runners, so mac assets carry an
architecture tag:

```
awardtracker-macos-x86_64-setup-v1.4.0.dmg
awardtracker-macos-x86_64-portable-v1.4.0.zip
awardtracker-macos-arm64-setup-v1.4.0.dmg
awardtracker-macos-arm64-portable-v1.4.0.zip
```

The tag comes from `AT_ASSET_ARCH`. Local builds leave it unset and keep the
historical untagged names.

Two compatibility details are load-bearing:

- `updater.py:_rank_macos_assets` picks the asset matching the running machine.
  Untagged assets from releases before this change are universal2, so they stay
  valid for either architecture. Apple Silicon accepts an x86_64 build as a last
  resort (Rosetta 2); an Intel Mac never accepts arm64 and reports "no asset"
  instead.
- The release job uploads the **x86_64 assets first**. Clients still running a
  version older than this change use the pre-arch-aware selector, which takes the
  first matching macOS asset — and x86_64 is the one that runs on both
  architectures.

## Required repository secrets

The macOS jobs fail at the signing step without these. Set them under
*Settings → Secrets and variables → Actions*.

| Secret | What it is |
| --- | --- |
| `MACOS_CERT_P12` | Developer ID Application certificate exported as `.p12`, base64-encoded: `base64 -i cert.p12 \| pbcopy` |
| `MACOS_CERT_PASSWORD` | The password set when exporting that `.p12` |
| `MACOS_SIGN_IDENTITY` | The identity string, e.g. `Developer ID Application: Your Name (TEAMID)` — must match the imported certificate exactly |
| `MACOS_NOTARY_APPLE_ID` | Apple ID used for notarization |
| `MACOS_NOTARY_TEAM_ID` | Apple Developer team ID |
| `MACOS_NOTARY_PASSWORD` | An **app-specific password** for that Apple ID (not the account password) |

No secrets are needed for the Windows or Linux jobs; `release` uses the
automatic `GITHUB_TOKEN`.

## Local builds still work

`release-macos.sh` reads signing config from `codesign_keys.json`
(`identity` + `keychain_profile`) when `AT_SIGN_IDENTITY` is unset, so the
existing local flow is unchanged:

```bash
./release-macos.sh --universal --codesign
```

Two environment variables exist purely for CI:

- `AT_ASSUME_YES=1` — answers the universal2 compatibility prompt, which would
  otherwise block on stdin.
- `AT_ASSET_ARCH` — adds the architecture tag to asset filenames.
