# Separated Library Storage and Reader Link Views

Status: separated-storage implementation with automated regression coverage; reader link views pending
Branch: `feature/separated-library-storage`
Base: `feature/indexed-library`

## Product contract

This fork retains **normal Calibre library behavior**: native imports, file naming,
metadata editing, covers, format conversion, and library switching. It must not
silently substitute the Indexed Library semantics for normal library management.

Two locations are selected **at library creation**:
1. Database/state directory on a local disk.
2. Calibre-managed book directory, potentially on a persistently mounted NAS.

No post-creation manual relocation of `metadata.db` is required. A successful
manual relocation experiment is evidence of feasibility on one installation,
not proof that the core supports the split across all operations and platforms.

## Architecture constraint to resolve first

Calibre historically derives `metadata.db`, book directories, and sidecar paths
from a single library root. Before exposing a creation wizard, audit the actual
paths in `calibre.db.backend.DB`, cache/legacy wrappers, library switching,
database backups, restores, moves, trash, and maintenance. Introduce an explicit
database-root versus books-root contract at the lowest shared layer that can
support all those operations; do not implement a GUI-only path redirection.

Existing Indexed Library modules are reference implementations, not a basis for
the new library's metadata or file-management semantics. Retire the Indexed
Library entry points only after the normal-library path is validated.

## Reader link views

The original Calibre-managed book files are authoritative. A separate output
directory is a disposable, rebuildable view for Komga or Kavita, grouped by
series/collection metadata. No file copying and no writes to source books.

Initial link operations are explicit preview and sync. A later close prompt
must only report pending changes; it must not silently mutate source media.

Link reconciliation must:
- Detect missing/unmounted source storage and **refuse destructive cleanup**.
- Never follow a link when deleting an obsolete generated link.
- Never overwrite user-created files or directories in output.
- Record ownership of generated links in a manifest and use atomic updates.
- Handle name collisions, invalid characters, series order, and multiple formats.
- Validate actual symlink visibility inside Komga/Kavita mount namespaces before
  claiming either reader is supported.
- Document Linux/macOS symlinks and Windows link privileges separately.

## Implementation order and acceptance gates

1. **Core audit:** map database-root and books-root assumptions; write regression
   tests proving normal library creation and reopen with split paths.
2. **Normal operations:** add/import, metadata edit, cover/sidecars, conversion,
   rename/move, delete/trash, backup/restore, library switch; verify against
   a temporary local directory and an independently mounted book directory.
3. **GUI:** creation dialog accepts both paths, validates writable mounts and
   explains offline/missing storage without initializing a broken library.
4. **Link engine:** dry-run manifest, safe create/update/remove, deterministic
   series and collection paths, tests for conflicts and missing mounts.
5. **Reader integration:** manually confirm Komga then Kavita scanner behavior.
6. **UX:** toolbar, configuration, manual sync, change tracking and close prompt.

## Non-goals

- A second Indexed Library mode.
- Rewriting Calibre metadata management.
- Automatically importing arbitrary NAS files without normal Calibre import.
- Duplicating ebook/comic files for readers.
- Assuming stable mount paths guarantee SQLite network-locking safety.

## Separated-storage milestone implementation

The normal backend now resolves `metadata.db` independently of its managed
`library_path`. Creation is available in the first-run wizard and in
**Switch/create library → Create an empty library**: select the books folder,
enable separate local database storage, and select an empty local folder.
Choose genuinely local storage for SQLite; the picker does not establish the
locking reliability of a network filesystem. Existing libraries are not
converted by this flow. Both folders must be empty, writable, and non-nested.
Ordinary libraries retain their existing layout.

The books folder contains `.calibre-separated-storage.json`, including a unique
storage identity and an initialized flag. The local database folder has a matching ownership marker,
`.calibre-separated-database.json`, to prevent sharing a database directory
between different libraries. Select the books folder when reopening.
Calibre's local configuration also
records this identity in `separated-library-storage.json`. Preserve this local
record: it identifies a previously configured library when the books mount and
its marker are absent. A missing database after initialization is an error,
including on a fresh installation that still has the books marker. Reconnect
storage at its original path before reopening. Do not delete these records to
work around a storage error.

### Path audit and coordinated behavior

- `db.backend.DB.dbpath`: local SQLite database, SQLite temporary rebuilds,
  notes database/resources, and full-text search state.
- `DB.library_path`: managed author/title folders, formats, covers,
  `metadata.opf`, preference backups, extra files, and Calibre trash.
- Backend and legacy `exists_at()` discover separated libraries using the same
  resolver. Startup and quick switching explain known unavailable storage.
- Cache write APIs check storage before changing cached metadata. Format import
  has its own lock and checks separately. Backend file operations check the
  marker before writing, renaming, backing up sidecars, or deleting files.
- Rebuilding from sidecars replaces the local database and preserves a local
  pre-restore database. Notes are restored from the local notes directory.
- Whole-library relocation moves the books root and its marker while keeping
  SQLite local. Book copies/moves between libraries retain normal Calibre
  behavior. The former location stays registered as unavailable, preventing
  accidental recreation there.
- Experimental Indexed Library creation/inspection menu actions and its built-in
  toolbar plugin registration are retired. Historical modules remain for
  reference and existing startup checks; separated storage never enables them.

### Verification and remaining acceptance gates

Automated regression coverage uses temporary directories exclusively. It covers
creation and reopen through the offscreen Qt creation dialog, first-run wizard,
normal imports, title/author path changes, series/collection metadata, covers,
OPF backups, deletes, copies between libraries, books-root relocation, database
backup, notes-aware recovery, missing local databases, and simulated
disconnection of either storage root. Disconnection tests rename a temporary
root and, for books, expose an empty replacement mountpoint, then verify that
writes fail without populating it. Ordinary library operations and the broader
database suite are also exercised.

Actual NAS mount failures, abrupt disconnection during an in-flight filesystem
operation, Windows/macOS behavior, and GUI usability on a visible desktop still
require manual validation. Marker checks reject unavailable storage before an
operation; they cannot make an entire network filesystem operation atomic.
SQL dump/rebuild tests require `apsw.shell` and are skipped when the installed
runtime omits it; backup and OPF-based recovery have separate tests.
No real MediaPool data is used by these tests.

The Komga/Kavita link engine, preview/sync UI, manifest reconciliation, and reader
container namespace/scanner validation remain subsequent milestones. No reader
compatibility is claimed by this storage implementation.

Run the regression suite against the installed Calibre runtime from this checkout:

```sh
CALIBRE_DEVELOP_FROM="$PWD/src" QT_QPA_PLATFORM=offscreen \
  /opt/calibre/calibre-debug -c 'from calibre.db.tests.main import find_tests; import unittest; r = unittest.TextTestRunner().run(find_tests()); raise SystemExit(not r.wasSuccessful())'
```

To run just the storage regression module, use:

```sh
CALIBRE_DEVELOP_FROM="$PWD/src" QT_QPA_PLATFORM=offscreen \
  /opt/calibre/calibre-debug -c 'import unittest; from calibre.db.tests import test_separated_storage; unittest.main(test_separated_storage)'
```

Verification on 2026-11-08 with `/opt/calibre/calibre-debug`: the final complete
`calibre.db.tests` suite ran **165 tests with zero failures/errors and 3 skips**
(two SQL dump/rebuild cases requiring the unavailable APSW shell and one
Windows-only filesystem case). All modified Python files parsed successfully,
and `git diff --check` passed. An earlier date-search test failure was corrected
by constructing its calendar-date fixtures in the local timezone. One
intermediate suite rerun exceeded its diagnostic timeout; the final rerun
completed in 93.946 seconds. These results do not establish real NAS or reader
scanner compatibility.
