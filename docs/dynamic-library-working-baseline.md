# Dynamic Library working baseline and production preparation

Verified 2026-11-09 on `feature/separated-library-storage`, continuing
`ca6c462f63`. The starting working tree was clean. Recent commits include the
metadata/link preview, clean naming, toolbar restoration, supplied Dynamic
Library icon/native label, and output-folder fix. All are included in this
checkpoint. No new synchronization architecture is introduced here.

## Architecture

There is ONE Dynamic Library output directory. The manager creates and maintains
its folders, symlinks and ownership manifest. Komga and Kavita may independently
use that same directory as their source; no second link tree, duplicate book,
or separate synchronization engine is needed. Actual Kavita scanning has not
been verified by this milestone. Existing internal Komga action/config/manifest
identifiers stay unchanged to preserve working synchronization state.

Original Calibre formats remain authoritative and are never copied, moved,
modified or deleted by synchronization. Calibre Series and Series Index define
grouping and ordering. Explicit preview precedes user-initiated Apply.

## Regression verification

- Real-Qt isolated GUI smoke passed: preview/apply/results/repeat on temporary
  fixtures; toolbar customizations; native label, icon and tooltip; dialog title;
  read-only monitoring; folder button validation, URL encoding and launch errors.
- All 21 focused reader-link regression tests passed, including interrupted-run
  recovery, manifest preservation, ownership protection, numeric/fractional
  naming, migrations, source relocation and repeated synchronization.
- The previous milestone records native build and focused quality results.
- Existing demonstration manifest still holds 14 links; its output/configuration
  and original test books were not altered for this checkpoint.

## Actual configuration inspected read-only

| Item | Current value |
| --- | --- |
| Saved production library | `/mnt/mediapool/Media/Comics/Calibre-Comics` |
| Production metadata | `metadata.db` directly in that books root |
| Production library ID | `4dd463b0-2081-4acc-a8ae-7b019d0f1cd6` |
| Database inventory | 14 books, 14 CBZ formats, four series |
| Production separated-storage marker/registry | Not present in inspected production root/configuration |
| NAS share | `//openmediavault.local/mediapool` mounted at `/mnt/mediapool` |
| Current mount | CIFS, **read-only**, SMB 3.0, `nounix`, `symlink=native`, `reparse=nfs` |
| Alternative desktop path | `/run/user/1000/gvfs/smb-share:server=openmediavault.local,share=mediapool/Media/Comics/Calibre-Comics` |
| Disposable books root | `/tmp/calibre-link-manager-demo/library` |
| Disposable local DB | `/tmp/calibre-link-manager-demo/database/metadata.db` |
| Disposable output | `/tmp/calibre-link-manager-demo/output` |
| Disposable configuration | `/tmp/calibre-link-manager-demo/config` |

The production DB was inspected with SQLite URI `mode=ro&immutable=1`; the
Calibre backend was not opened against it. Immutable access assumes an inactive
DB and is only an inventory observation, not a live transactional preview.
Production preferences were read, not changed. The NAS comics parent currently
contains `Calibre-Comics` and `Komga-Comics`; neither was changed.

The demo has matching initialized separated-storage identity markers in its
books and local-database roots. Its metadata library ID matches the real DB,
so KEEP ITS CONFIGURATION ISOLATED: destination settings are keyed by library
ID. Reusing its config for the real collection could select the demo output.
Local `Documents/Calibre-Databases` also contains small Test/New Test/Temp DBs
and a four-book legacy indexed DB; these are not the saved active collection.
No production separated-storage migration is inferred or performed.

## Safe real-world configuration, pending approval

1. Confirm which Calibre library is the real collection. The currently selected
   NAS DB contains the same 14-book inventory as the demo, not a larger catalog.
   Supply the actual managed books root/local DB if a larger collection exists.
2. Approve ONE dedicated, initially empty output directory outside the Calibre
   books and metadata roots. A candidate is
   `/mnt/mediapool/Media/Comics/Dynamic-Library` (not created). Do not reuse the
   existing production `Komga-Comics` directory or disposable demo output.
3. Keep originals mounted read-only where possible. Provide a separately writable
   mount/export for the approved output. The current read-only CIFS mount cannot
   create links/manifests. Any mount/service changes need separate approval.
4. On an approved disposable child of that output storage, verify actual NAS
   support for native symlinks/readlink, descriptor-relative no-follow access,
   advisory locking, atomic manifest replacement and fsync. Existing CIFS flags
   do not prove these operations work or that symlinks survive other clients.
   GVfs support must not be assumed. No NAS write probe has been performed.
5. Approve stable source paths and consumer visibility. Current links have
   absolute targets: both the output and original book paths must resolve in
   each reader's runtime. For containers, read-only bind mounts must preserve
   those exact target paths (or the same stable path must be used consistently
   when creating links). A NAS-hosted reader cannot resolve a Linux desktop's
   `/mnt/...` or session-specific GVfs targets unless its own namespace provides
   them. Exposing just the output tree is insufficient. No reader/container or
   production mapping change has been made.
6. Use a separate real-use fork config, keeping the demo untouched. Existing
   separated-storage resolution is supported: the managed books root supplies
   formats, while its explicitly configured local DB supplies metadata. The
   present conventional library does not need to be converted merely to create
   a Dynamic Library. Any conversion would be separate approved work.
7. Generate the full preview against the chosen library and approved destination;
   review all additions, repairs, relocations, removals and naming collisions.
   Stop for explicit approval of that preview before Apply. Sources must remain
   available throughout verification; only owned links/state can be changed.

The Linux synchronization prototype requires POSIX descriptor-relative and
no-follow filesystem operations; cross-platform folder opening does not imply
that the synchronization engine is production-validated on Windows/macOS or
arbitrary NAS exports. NAS filesystem behavior and shared runtime paths are the
remaining practical prerequisites, not additional synchronization engines.

No production destination was configured, created or synchronized. No book,
production service, mount, Komga/Kavita mapping or Caddy setting was changed.
