# Release notes

One file per released version, written by the `/deploy` skill and committed
alongside the `version.txt` bump. `release.yml` reads
`release_notes_v<VERSION>.md` to build the GitHub release body, so the file for
a version must be committed before its tag is pushed.

These used to live untracked under `internal_docs/`. They are tracked now
precisely so CI can read them.
