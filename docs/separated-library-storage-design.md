# Separated Library Storage and Reader Link Views

Status: implementation design, not yet implemented
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
