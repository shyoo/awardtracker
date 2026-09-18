# Release Pipeline

Award Tracker separates **release candidates** from the **latest release** and
builds every downloadable file in GitHub Actions.

## Commands and responsibilities

| Command | Local work | GitHub Actions |
| --- | --- | --- |
| `/push` | Runs all tests and pushes the feature branch | `ci.yml` repeats tests on Windows and macOS |
| `/release rc` | Creates and pushes an annotated `vX.Y.Z-rc.N` tag on `origin/main` | Tests, builds, signs, notarizes, and publishes a prerelease |
| `/release promote` | Creates `vX.Y.Z` on the verified RC commit | Rebuilds that commit and publishes it as the latest release |

No release command builds or uploads files locally. `release-win.ps1` and
`release-macos.sh` remain available for development, but shipped assets always
come from `.github/workflows/release.yml`.

The tag is the version and its annotated message is the release notes. Cutting
an RC or promoting it does not edit `version.txt`, add a notes file, or create a
release-only commit. During an Actions build, the workflow writes the tag's
version into `version.txt` before packaging so the installed app and its asset
filenames carry the right RC or final version.

## RC and promotion flow

1. Land and push the changes to `main`; its CI run must pass.
2. `/release rc` plans the next version. By default it starts the next patch
   line (`v1.3.10` → `v1.3.11-rc.1`) or continues its RC counter.
3. The release workflow validates that the tag is annotated and points to a
   commit on `origin/main`, reruns the test suite, then builds all platforms.
4. GitHub publishes an RC tag as a **prerelease**. Installed apps use
   `/releases/latest`, which excludes prereleases, so normal users cannot see
   the RC.
5. A person installs the appropriate asset and verifies it.
6. `/release promote` creates the bare final tag on that RC's exact commit.
   The workflow rebuilds it and publishes a normal release, which becomes
   `/releases/latest` and is offered by the updater.

If an RC needs a fix, land the fix and run `/release rc` again. This creates the
next RC in the same series. Do not move or delete a published tag.

## Build outputs

The workflow produces two Windows x64 files and two files for each Mac
architecture:

```text
awardtracker-win64-setup-v1.4.0-rc.1.exe
awardtracker-win64-portable-v1.4.0-rc.1.zip
awardtracker-macos-x86_64-setup-v1.4.0-rc.1.dmg
awardtracker-macos-x86_64-portable-v1.4.0-rc.1.zip
awardtracker-macos-arm64-setup-v1.4.0-rc.1.dmg
awardtracker-macos-arm64-portable-v1.4.0-rc.1.zip
SHA256SUMS.txt
```

- `macos-15-intel` builds and runs the Intel (`x86_64`) package.
- `macos-15` builds and runs the Apple Silicon (`arm64`) package.
- The updater chooses the native architecture. Historical untagged Universal 2
  assets still work, and an Intel package remains a last-resort Rosetta fallback
  on Apple Silicon. Intel Macs are never offered an arm64 package.
- Intel assets are staged before arm64 assets so versions of Award Tracker from
  before the architecture-aware updater still choose a runnable file.

Every GitHub release includes `SHA256SUMS.txt`. Windows packages remain
unsigned, so Windows may show a SmartScreen warning. macOS packages are signed
and notarized.

## Required GitHub Actions secrets

The existing Award Tracker secret names are retained; they do not need to match
Warmstart's names. Configure these under **Settings → Secrets and variables →
Actions**:

| Secret | Value |
| --- | --- |
| `MACOS_CERTIFICATE_P12` | Base64-encoded Developer ID Application `.p12` certificate |
| `MACOS_CERTIFICATE_PASSWORD` | Password used when exporting the `.p12` |
| `MACOS_SIGNING_IDENTITY` | Exact Developer ID identity, including Team ID |
| `AC_API_KEY_ID` | App Store Connect API key ID used for notarization |
| `AC_API_ISSUER_ID` | App Store Connect API issuer ID |
| `AC_API_KEY_P8` | The API key's `.p8` contents (PEM text or base64) |

`release-macos.sh` also accepts Apple ID notarization through
`AT_NOTARY_APPLE_ID`, `AT_NOTARY_TEAM_ID` and `AT_NOTARY_PASSWORD` when the
API-key variables are unset.

The workflow fails instead of publishing an unsigned or unnotarized macOS
release when these values are missing. Windows and release publication use the
automatic `GITHUB_TOKEN` and need no extra secret.

## Local packaging

Local architecture builds still work:

```powershell
./release-win.ps1
```

```bash
./release-macos.sh --codesign
```

The optional Universal 2 path is retained for local experiments:

```bash
./release-macos.sh --universal --codesign
```

It is not used for GitHub releases; separate native Intel and Apple Silicon
packages make the architecture visible and avoid requiring Rosetta on Apple
Silicon.
