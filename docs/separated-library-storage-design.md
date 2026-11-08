# Separated library storage — Phase 1 baseline

Branch: `feature/separated-library-storage`

Local annotated baseline tag: `phase1-separated-storage-baseline`

Configuration version: **1**

Phase 1 retains normal Calibre library management with SQLite on a local disk
and managed books in a separately selected filesystem folder, including a
connected SMB share. User GUI testing passed PDF, EPUB and CBZ import, metadata
updates, and persistence across restarts over Linux SMB/GVfs. Automated review
uses disposable data only. Actual network-disconnection testing is not performed.

Phase 2, the reader link manager, is **not implemented** by this baseline.

## Architecture and directory structure

The shared resolver is `calibre.db.separated_storage.resolve_database_path()`.
`calibre.db.backend.DB.library_path` is always the **managed books root**;
`DB.dbpath` is the independently resolved SQLite file. Modern GUI, library
broker, `calibredb`, cache and legacy-compatibility APIs use this backend. A
library without a marker or remembered split identity retains the ordinary
Calibre layout and behavior.

```text
Local database folder/                 Selected local filesystem folder
  .calibre-separated-database.json      Ownership marker
  metadata.db                          Book metadata, IDs and library preferences
  full-text-search.db                  Optional full-text search database
  .calnotes/
    notes.db                           Author/series/tag notes database
    resources/                         Note resources
    backup/                            Note recovery data
    retired/                           Retired note data
  metadata_pre_restore.db               Created when rebuilding from sidecars
  ...                                  SQLite journals and temporary state

Managed books folder/                  Selected local or connected SMB folder
  .calibre-separated-storage.json       Split configuration and storage identity
  Author/
    Title (id)/
      Title - Author.epub               Normal Calibre-managed formats/names
      Title - Author.cbz
      cover.jpg
      metadata.opf
      data/                            Optional extra files
  .caltrash/                           Normal Calibre trash, on the books storage
  metadata_db_prefs_backup.json         Library preference recovery sidecar

Calibre configuration folder/          Separate, per-user local application config
  global.py.json
  gui.json
  separated-library-storage.json        Remembered books-root identities
  ...
```

The selected database folder holds library databases/state, not all application
settings. Library preference backups, OPF files, covers, formats, extra files,
and trash remain associated with the managed books filesystem. SQLite rebuilds,
notes and search state follow `dbpath`; they are not redirected to the NAS.

### Configuration contract

New libraries have a version-1 books marker with an absolute
`database_directory`, unique `storage_id`, and, after database creation, boolean
`initialized: true`. The local ownership marker must match the storage ID.
The per-user registry remembers the same configuration under the books path,
so a disconnected share cannot masquerade as a new empty ordinary library.

Configuration validation rejects JSON `null`, unsupported/incorrectly typed
versions, nonabsolute database paths, malformed IDs/initialization flags,
nested/equal roots, conflicting databases in the books folder, and mismatched
ownership. Windows comparisons account for case-insensitive path spelling;
different drives or a UNC books root plus a local database drive are allowed.
Legacy version-1 resolver configurations without optional ID/initialized fields
remain readable for compatibility; GUI creation always writes ownership IDs.

A missing initialized database fails closed. Corrupt or mismatched markers do
not trigger ordinary-library initialization. Preserve both markers and the
per-user registry when backing up a split installation. If the registry is
lost **and** the remote marker is inaccessible, the application cannot infer the
intended library type from an otherwise empty path.

## Creation, reopening and switching

1. Connect the books storage through the operating system's normal file access.
2. In the first-run wizard, or **Switch/create library → Create an empty
   library**, choose an empty books folder and enable separate local database
   storage. Select a separate empty, writable local database folder.
3. Creation reserves the local folder, creates the books marker exclusively,
   initializes normal Calibre SQLite metadata locally, and records completion.
   It does not relocate an existing `metadata.db` or create an Indexed Library.
4. Import through normal Calibre commands. Books receive Calibre's usual
   author/title directories, format names, covers and OPF sidecars. Existing
   arbitrary NAS folders are not indexed in place.
5. To reopen or switch, select the **books folder**, not the database folder.
   Discovery resolves its local database. Selecting the ownership-marked local
   database folder as an ordinary library is rejected.

Existing ordinary libraries are not converted by this creation flow. To adopt
separated storage, create a new split library and use Calibre's normal copy/move
between libraries. Whole-library relocation moves the books root and marker
while retaining the local database; the former path stays remembered as
unavailable. Automatic relocation of the local database directory or migration
between operating systems is not a Phase 1 workflow.

The obsolete `calibre.library.database2.LibraryDatabase2` implementation rejects
split roots before creating files. Plugins must use the current
`calibre.db.legacy.LibraryDatabase` compatibility API or the cache API. Indexed
Library GUI actions are retired; historical modules are not this architecture.
Conflicting `CALIBRE_OVERRIDE_DATABASE_PATH` overrides are rejected for split
libraries rather than silently selecting another database.

## SMB/GVfs compatibility and platforms

Calibre file management consumes **filesystem paths**, not SMB URLs. Select a
connected share through the desktop folder picker. Pasted `smb://`, `file://`,
or web URLs are rejected before they can become accidental local directories.
No automatic share connection, remapping, or substitution of a permanent mount
is performed.

| Platform | Books path | Phase 1 evidence and caveats |
| --- | --- | --- |
| Linux | Desktop-connected GVfs SMB path, commonly below `/run/user/<uid>/gvfs/`, or another accessible filesystem path | User GUI integration passed. No kernel CIFS/fstab mount is required. GVfs paths are tied to the user session and may change. |
| macOS | Finder-connected SMB volume exposed as a filesystem path, commonly under `/Volumes/` | Path/IO code remains portable; no macOS GUI or actual SMB outage testing was performed. Volume naming, permissions and case behavior need manual qualification. |
| Windows | UNC share path or accessible drive path, with SQLite on a local drive | Windows drive/UNC/case validation is covered by portable path tests. Actual Windows SMB behavior is untested. Existing Calibre path-length and file-sharing restrictions still apply. |

The local database folder must genuinely be local; the picker does not prove
filesystem locality or network SQLite-locking reliability. Choose the share as
books storage only. No `/mnt/mediapool` fallback or other fixed mount is required.

Marker creation uses exclusive direct creation, retaining collision protection.
Completion uses a direct, existing-file-only write with flush/fsync. This avoids
hard links and temporary-file replacement renames that were rejected with
`EPERM` on GVfs SMB. The design follows normal Calibre cover/OPF direct-write
behavior; it does not rewrite normal book management or restore Indexed mode.
Marker writes are not atomic. Interrupted writes fail closed; recovery may
require restoring the marker configuration after checking the local database.

## Operations and integrity safeguards

- Imports and cache write APIs validate storage before modifying managed data.
  Format import also checks under its own write lock.
- Title/author changes retain normal file moves. Local metadata and author-note
  transactions roll back failed changes when no filesystem change completed;
  caches and pending backup state are restored from the already-open local DB.
- An internal, thread-local recovery context permits local cache reload while
  books storage is unavailable. It does not open a replacement database or
  bypass guards in another thread. It is not an offline-write API for plugins.
- Completed moves/cover writes retain corresponding local paths/flags if a
  later storage probe fails. Bulk requests can partially complete and report
  failure without rolling successful mappings back to nonexistent paths.
- Strict book/format probes propagate permission, stale-path and I/O failures.
  Missing-looking storage does not authorize deletion of registered formats or
  book records. Explicit database-only format removal remains a repair action.
- Existing-format replacement in a split library must stage and replace safely;
  denied staging/unsafe replacement does not fall back to truncating a good
  original. Ordinary libraries retain their existing replacement policy.
- Library maintenance ignores the books marker, checks storage before scanning,
  and reports unavailable registered book folders as errors rather than offering
  missing-format repairs for those folders.
- Startup, including `--with-library`, does not recreate known disconnected
  roots. An outage during opening a known split library aborts instead of
  offering a new empty library. Closing remains possible during an outage.
- Pending OPF backups survive failures and their worker retries after recovery.
  Transient storage read errors do not persist false failed page counts; scans
  remain pending for a subsequent scan/restart.

When the same path and identity are accessible again, API operations can resume
without reopening. Clean close/reopen retains existing books and metadata. A
changed path/identity is not guessed, auto-remounted or silently substituted.

## Backup, restore and maintenance

Back up the local databases/notes and managed books as one logical library,
including their markers and the local application registry. For filesystem
backups, use a consistent snapshot or close Calibre; independently timed copies
of live SQLite and remote files are not a consistent distributed snapshot.

Normal database backup and rebuild-from-OPF use the local database location;
rebuild preserves a local pre-restore database and recovers local note data.
The SQLite SQL dump/rebuild feature requires a runtime providing `apsw.shell`.

Whole-application export discovery includes separated and ordinary libraries
and deduplicates resolved databases. Unavailable libraries are omitted, as for
ordinary libraries: verify the exported library selection before relying on a
backup. Portable archive export includes book data, covers, metadata and notes.
Archive import restores an **ordinary combined library**, not machine-specific
split markers. Configuration restoration updates current/legacy preferences and
removes stale split mappings for imported ordinary destinations, preserving
unselected mappings. Create a new split library and copy/move books if a
separated layout is required after archive import.

## Security and known limitations

Markers and storage are trusted configuration, not a signed manifest or a
sandbox. A marker supplies a local database path. Do not open split libraries
from untrusted shares or permit untrusted edits to markers/databases. Legacy
markers without IDs offer weaker ownership checks. Normal plugin/raw-SQL/file
access outside managed APIs is outside these safeguards.

Only one active writer should manage a library. Independent local SQLite copies
on different computers do not coordinate simultaneous writes to shared books.
Sharing one NAS books tree between independent databases/writers is unsupported.

The NAS and local SQLite are not a distributed atomic transaction. An interrupted
move/delete can leave partial filesystem work requiring inspection. Bulk
requests can retain completed metadata/file changes while reporting a later
failure. A new import can retain an incomplete newly created record for retry.
Direct cover/OPF/marker writes are not guaranteed atomic. OS/GVfs calls can block
until their own timeouts; Phase 1 adds no timeout/watchdog or automatic remount.

Untested scenarios include actual network-disconnection/power-loss behavior,
concurrent multi-client access, broad third-party plugin compatibility, and
actual macOS/Windows GUI/SMB qualification. Conversion pipelines and every
maintenance/plugin workflow have not been individually exercised on real SMB.
Automated outage injection is not evidence that all physical failure modes are
atomic or recoverable without manual inspection.

## Verification and local baseline

The relevant regression suites are the complete database and database CLI
suites. Coverage includes ordinary-library compatibility, creation/reopen,
imports, metadata/notes, covers, moves/trash, backup/export/restore, configuration
validation, local auxiliary DB placement, SQLite integrity/foreign-key checks,
and missing/permission/stale/disconnected storage simulations.

Run from this checkout using the existing runtime, with a **fresh disposable**
configuration, cache, data/Trash, and temporary directories. This example uses
Linux and the installed development runtime; recycler isolation on other
platforms requires separate qualification:

```sh
phase1_test_root=$(mktemp -d /tmp/calibre-phase1.XXXXXX)
export CALIBRE_CONFIG_DIRECTORY="$phase1_test_root/config"
export CALIBRE_CACHE_DIRECTORY="$phase1_test_root/cache"
export CALIBRE_TEMP_DIR="$phase1_test_root"
export XDG_DATA_HOME="$phase1_test_root/data"
export XDG_CACHE_HOME="$phase1_test_root/xdg-cache"
export QT_QPA_PLATFORM=offscreen
CALIBRE_DEVELOP_FROM="$PWD/src" /opt/calibre/calibre-debug -c \
  'import unittest; from calibre.db.tests.main import find_tests; r = unittest.TextTestRunner().run(find_tests()); raise SystemExit(not r.wasSuccessful())'
CALIBRE_DEVELOP_FROM="$PWD/src" /opt/calibre/calibre-debug -c \
  'import unittest; from calibre.db.cli.tests import find_tests; r = unittest.TextTestRunner().run(find_tests()); raise SystemExit(not r.wasSuccessful())'
```

Final verification on 2026-11-08:

| Suite/check | Result |
| --- | --- |
| Complete database suite | 211 tests, zero failures/errors, three skips |
| Complete database CLI suite | 37 tests, zero failures/errors, no skips |
| Final-review regressions (included in database suite) | 16 tests passed |
| Outage/recovery regressions (included in database suite) | 24 tests passed |
| Metadata, notes and FTS SQLite databases | Integrity and foreign-key checks passed on disposable libraries |
| Source verification | Changed Python files parsed; `git diff --check` passed |

The three skips are one Windows-only filesystem test and two SQL dump/rebuild
tests requiring `apsw.shell`, which the installed runtime omits. Initial review
regressions demonstrated the null-marker, maintenance, export discovery,
obsolete-backend and case-sensitive Windows nesting defects before the fixes.
The first CLI run exposed its use of the OS Trash; the successful final run
isolated XDG data/Trash as well as configuration/cache/temp storage.

The annotated tag identifies the reviewed source and documentation together.
It is suitable as the Phase 2 foundation subject to the limits above; it is not
universal filesystem/platform certification. No production library, existing
GUI test library, mount or service was changed or disconnected. No real outage
was induced. The tag is local; nothing is pushed without user approval.

## Phase 2 boundary

Phase 2 may build disposable Komga/Kavita views using the normal metadata and
resolved managed-book paths. It must leave source books authoritative and must
not reintroduce Indexed Library semantics. Preview and explicit sync come
before automatic behavior. Missing/unavailable sources must refuse destructive
cleanup. Output ownership manifests, atomic manifest updates, collision handling,
series/collection ordering, user-file protection and deletion without following
links are required. Actual reader/container path visibility and Linux/macOS/
Windows link permissions must be validated before claiming reader support.
No reader link tree, sync UI or reader integration is implemented in Phase 1.
