# Phase 2 GUI refinement

Continues `6f4f00641b` on `feature/separated-library-storage`. The starting
working tree was clean. Verified 2026-11-09.

## Toolbar

The normal toolbar implementation/defaults were intact. The disposable demo's
`/tmp/calibre-link-manager-demo/run_demo.py` was overwriting its toolbar preference
with four actions at every startup. Removed that override, backed up the launcher
and demo preferences, and repaired only the exact known four-action demo layout
using the user's saved full toolbar layout, appending Sync Komga Library once.
Production preferences were read only; their SHA-256 was unchanged. All other
demo preferences were retained. Saved custom plugin action names remain present;
the isolated demo continues using `--ignore-plugins`.

Sync uses the existing `sync.png` resource. Its tooltip remains exactly
“Sync Komga Library”; monitoring status goes in the status tip. The toolbar
applies icon-only styling to this marked action across rebuilds and style
changes, without changing the styling or saved layout of other actions. Existing
one-time installation preserves customized order and respects subsequent removal.

## Names and ordering

Series and Series Index determine grouping and numeric ordering. Output uses
`Iron Man/01 - Title.cbz`, without internal hashes or IDs. Integer padding grows
with the series. Fractions retain their significant digits, with a shared
fractional width where necessary for natural numeric sorting: `01`, `01.25`,
`01.50`, `02`. Small fractional values are not rounded or rendered in scientific
notation. Metadata rows also retain meaningful decimal precision.

Stable book IDs remain in the manifest. Previous names are previewed as
relocations/removals using those IDs. Sanitization, case folding or truncation
collisions now produce a metadata correction error before writes, instead of
merging series or adding opaque IDs. Empty old managed directories are retained
under the existing conservative cleanup policy.

## Verification

- Native build and RapydScript incremental compilation passed.
- All 21 focused reader-link regression tests passed, including clean names,
  fractions, width growth, collisions, migration, repeated synchronization,
  source relocation, ownership guards and failed manifest commits.
- Offscreen real-Qt GUI smoke passed: preview/apply/results/repeat on disposable
  fixtures, non-null icons, exact tooltip, icon-only styling under both text
  styles and toolbar rebuild, preservation of custom actions and separators,
  respect for user removal, and read-only monitoring.
- Focused formatting, Ruff checks, type checks and `git diff --check` passed.

## Visible demonstration

Started the existing isolated launcher, leaving the desktop application open.
The real dialog reports four series, 14 books, 14 links and 14 pending additions.
The preview opens on “Preview folders and links”; the sync icon and dialog are
visible, and Apply is enabled for the user. No synchronization was executed in
the live demo. `/tmp/calibre-link-manager-demo/output` remains empty.

The writable local database is
`/tmp/calibre-link-manager-demo/database/metadata.db`. Both configuration and
output remain disposable. Bubblewrap keeps original book storage read-only.
No production library, service, Komga, Kavita or Caddy configuration changed.
The live instance is intentionally left running.

## Dynamic Library presentation update

The later presentation request supersedes the icon-only Sync label described
above: the action now displays the supplied `resources/images/dynamic-library.png`
with the native “Dynamic Library” text below it, tooltip “Manage Dynamic Library”,
and dialog title “Dynamic Library Manager”. The internal action identifier remains
unchanged so existing toolbar layouts and shortcuts continue to work. Other
buttons keep their configured style and layout; synchronization is unchanged.

Focused real-Qt checks passed for the rendered icon, both action labels/tooltips,
text-under-icon styling across toolbar rebuilds/style changes, matching native
button fonts, dialog title, customized toolbar preservation and monitoring.
All 21 reader-link regressions, incremental native build, RapydScript, GUI icon
resource compilation, focused formatting, lint and type checks passed. GUI Apply
checks used temporary fixtures only; the live demo was not synchronized or restarted.
