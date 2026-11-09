# Dynamic Library Link Manager — Komga prototype

Branch: `feature/separated-library-storage`. Builds on
`phase1-separated-storage-baseline`; no Indexed Library behavior is restored.

## Using the prototype

The dedicated **Sync Komga Library** toolbar action opens the sync dialog.
Existing profiles receive the action once; afterwards normal toolbar
customization applies. It is separate from the library-management control.

1. Create an empty disposable output folder outside both managed books and the
   database folder. Select it in the dialog. Selection is remembered per library
   UUID in the local `komga-link-manager` application preferences.
2. Review the preview: each proposed addition, repair, relocation and removal
   shows its relative output path and absolute source target. Preview performs
   no output writes. A successful preview enables **Apply previewed changes**.
3. Apply explicitly. Metadata and output are rechecked; a changed plan requires
   another preview. Results report changes and verified links, or the error.
4. After closing the dialog, read-only monitoring runs approximately every 30
   seconds. Pending counts/errors appear in the action tooltip and dialog.
   Monitoring never applies changes. Use Preview to refresh an open dialog.

No production Komga/Kavita directory has been changed or configured by this
milestone. Output paths are selected explicitly; there is no production default.

## Architecture and naming

`calibre.db.reader_links.read_books()` snapshots the current cache under its
read lock, including IDs, titles, authors, series, numeric indexes and resolved
format paths. Separated storage is checked before reading; any unavailable
registered supported format blocks the entire preview/apply, including cleanup.
The adapter uses `backend.library_path`, not the local SQLite directory, for
managed books. Author/title edits that move Calibre's files change resolved targets.

`komga_layout()` is independent of database access and filesystem mutation.
`LinkManager` consumes its link records, so another reader layout can later be
added without duplicating synchronization or adding dependencies on Kavita.

Supported formats in this prototype: CBZ, CBR, EPUB, PDF. Every supported format
gets its own link; a multi-format book therefore appears more than once to the
reader. Other formats are omitted. No covers, OPFs, ComicInfo or embedded book
metadata are changed or exported.

```text
Chosen output/
  Invincible Iron Man (2008-2012) [series hash]/
    0000001.0000 - Title [calibre ID].cbz -> /absolute/managed/book.cbz
  .calibre-komga-manifest.json
  .calibre-komga-pending.json          only during/recovering an operation
  .calibre-komga-lock
```

Series hashes prevent sanitized/truncated/case-only series names from merging.
IDs prevent title collisions. Decimal indexes use four decimal places and
padded numeric prefixes for common positive volume ordering. Books without a
series have individual title/ID series folders. Components have a UTF-8 byte
limit. Embedded metadata can affect how Komga displays ordering; no actual
Komga scan/render or container path mapping has been qualified here.

## Ownership, transactions and failure handling

Manifest version 1 records library UUID, output path and each book ID/format,
relative link name and absolute target. The manifest is the last committed
successful link set. It is replaced atomically only after links verify.

Apply takes an exclusive, nonblocking output lock and saves/fsyncs an ownership
journal before changing links. The journal retains old and newly proposed
ownership across partial failures. Before commit, errors leave the previous
manifest untouched. Link changes may already have partially completed; the next
explicit preview/apply reconciles journal-owned links against current metadata,
including abandoned additions from an earlier failed plan. A first failed sync
can have a journal without a successful manifest. Keep this journal for retry.

Atomic manifest replacement is the commit point. If directory flushing or journal
cleanup fails after that point, the result reports a committed synchronization
with warnings, rather than claiming the published manifest was rolled back.
Filesystem power-loss durability still depends on the storage implementation.

Only exact recorded symlink/target pairs are owned. A regular file, an unowned
symlink, a changed recorded target, corrupt state, a different library identity
or conflicting output causes an error. Externally retargeted links require manual
inspection; the manager will not adopt or overwrite them. Missing owned links and
outdated links to an old managed location are repairable. Removing a database
record removes only its owned output links, never the source book.

Descriptor-relative operations with `O_NOFOLLOW` reject symlinks in output
ancestors and series folders. Cleanup unlinks the symlink itself, never its target.
There is no recursive cleanup and no directory deletion: empty series directories
remain. Original book files are only probed/read; the manager never copies,
writes, moves, overwrites or deletes them. No hard links are used.

## Scope and operating limits

- Linux/POSIX prototype; Windows refuses unsafe unsupported IO. macOS is not
  qualified (symlinked ancestors such as `/tmp` require a real directory path).
- Use a local filesystem supporting symlinks, flock, atomic replacement and
  directory fsync. GVfs/SMB output support is not claimed. Sources may use the
  Phase 1 separated-storage paths; unavailable sources abort synchronization.
- Links contain absolute desktop paths. Komga must be able to traverse those
  same paths and have read permissions. A container mount with different paths
  needs a future explicit mapping feature. This does not deploy/configure Komga.
- State and directories are trusted, single-owner configuration, not a defense
  against malicious concurrent filesystem rearrangement. Concurrent plugin
  writers cooperate through flock; unrelated tools must not rearrange the output
  during synchronization. Kernel/NAS calls may block; no IO timeout is added.
- The journal provides restart recovery, not atomic visibility of the whole tree
  to a concurrently scanning reader. Process-kill/power-loss and real NAS outage
  tests remain unperformed; interruption/IO failures are injected in tests.
- There is one configured output per library. Reconfiguration leaves the old
  output and manifest intact; automatic migration/decommissioning is not provided.
- Monitoring is polling while the GUI runs, not a background service. Kavita and
  Tidebound layouts, remote scanners and automatic apply are not implemented.

## Verification

Automated tests cover the complete lifecycle, split-database API integration,
source relocation through author changes, missing sources, changed series/index/
title, removed records, missing/broken links, repeated sync, collisions, foreign
files/symlinks, traversal, missing/symlinked output, concurrent writers, corrupt
state, stale previews, interrupted link creation, failed manifest replacement,
changed desired metadata during recovery and post-commit cleanup warnings.

Tests use disposable source and output folders. Database test configuration,
cache, temporary files and XDG data/Trash are isolated under `/tmp`.

The existing Iron Man fixture was read from the documented MediaPool
`Media/Comics/Calibre-Comics` library via SQLite read-only queries; no Calibre
writer was opened against it. Eleven Iron Man records (IDs 4–14) produced eleven
symlinks in `/tmp/calibre-phase2-test/iron-man-output`, grouped by their existing
`Invincible Iron Man (2008-2012)` series. Initial preview wrote nothing; repeat
preview reported zero changes. Every linked file and original was SHA-256
checked, and all original hashes remained unchanged. Metadata mutation scenarios
ran against disposable fixtures, never this existing library.

A separate offscreen GUI process exercised preview, explicit apply, verified
results and repeat preview. Preview/result screenshots were visually inspected.
Production reader directories and original library metadata were untouched.

Final verification (2026-11-08):

| Check | Result |
| --- | --- |
| Complete database suite | 228 tests; passed, 3 existing skips |
| Complete database CLI suite | 37 tests; passed |
| Link-manager regressions (included above) | 17 tests; passed, including a final rerun |
| Iron Man read-only source smoke | 11 links verified; no duplicate changes; original hashes unchanged |
| Offscreen GUI smoke | Preview, explicit apply, results, repeat preview, toolbar migration and read-only polling |
| RapydScript build | Passed using installed Calibre Python 3.14 runtime |
| Python source parsing and diff whitespace | Passed |
| Native build | Blocked: no `qmake` |
| Formatter, lint and type-check setup commands | Blocked: no `uv` / development environment |

The shell has no `python` command and system Python is 3.12; the project needs
3.14. Setup commands were therefore also attempted using
`/opt/calibre/calibre-debug -e setup.py -- COMMAND`. The setup test runner cannot
launch its worker arguments through that executable (`--worker`/`--pipe-worker`
are rejected), so database/CLI suites used the Phase 1 documented in-process
`find_tests()` runtime invocation. RapydScript required execution outside the
sandbox after Qt WebEngine was denied there. No missing native/toolchain check
is represented as passing.

To repeat the standalone GUI smoke, create a fresh `/tmp` configuration/cache/
XDG data directory and run with `QT_QPA_PLATFORM=offscreen`,
`CALIBRE_DEVELOP_FROM="$PWD/src"`, and
`/opt/calibre/calibre-debug -e tests/reader_links_gui_smoke.py`. It constructs and
removes its own disposable library/output. Do not run it with production
application preferences: toolbar migration is deliberately exercised.

## Follow-up native build and desktop verification

See [Linux Mint build and desktop verification](phase2-linux-mint-verification.md)
for the isolated dependency setup, native build, standard 265-test runner,
quality-check results, actual Iron Man desktop synchronization and original hash
verification. The earlier qmake/uv blockers are resolved for this checkout.
Repository-wide legacy lint/type failures and container path visibility remain
separate recorded limitations.

## Actual Komga scanner/read verification

[Isolated Komga scan verification](phase2-komga-scan-verification.md) records
successful discovery of 14 linked books in four series, cover and comic-page
retrieval, complete-book hash matches and a duplicate-free deep rescan. Original
before/after hashes match. Remote production-container inspection and browser
reader UI testing remain explicitly unverified; no production mappings changed.
