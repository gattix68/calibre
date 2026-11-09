# Phase 2 — Linux Mint build and desktop verification

Continues commit `a62d780a4a`, on `feature/separated-library-storage`.
Verified on Linux Mint 22.3 / Ubuntu Noble, 2026-11-08.

## Dependency findings and safe configuration

The missing tools were symptoms of an incomplete development environment:

- This checkout requires Python >= 3.14. Mint's system Python is 3.12.3.
- Mint offers `qmake6` / `qt6-base-dev` 6.4.2. The installed Calibre runtime and
  checkout use Qt 6.10; installing only Mint's qmake is not a matching toolchain.
- `/opt/calibre` supplies a runtime, not its development headers/build tools.
- A full native build also needs Python headers/libpython, Qt private headers,
  SIP/PyQt-builder, CMake, FreeType headers, and the libraries enumerated in
  `setup/extensions.json`. These include ICU, FFmpeg, PoDoFo, ONNX Runtime,
  eSpeak, libusb/libmtp, image codecs and spelling/hyphenation libraries.
- Existing GCC/G++, GNU make, pkg-config and libc development tools were reused.
- Quality commands use uv to construct `.venv` from the declared project and
  dev requirements. The dev group includes Ruff, ty, type stubs, RapydScript
  and clang-format. No system Python package installation is required.

For Python-only development, upstream recommends using the installed binary as
runtime with `CALIBRE_DEVELOP_FROM`; full native builds require more dependencies.
See the [Calibre development guide](https://manual.calibre-ebook.com/develop.html).
For this requested native build, the safest practical matching stack was the
same SDK archive used by `setup/unix-ci.py`, extracted privately, with a small
private overlay of Mint development files. No `/sw` directory, apt installation,
PPA, global qmake symlink, system Python replacement or service change was used.

Installed/configured only within the checkout:

| Location | Contents |
| --- | --- |
| `.build-cache/tools/bin` | uv 0.13.7 / uvx; installer used `UV_UNMANAGED_INSTALL` |
| `.build-cache/python` | uv-managed CPython 3.14.10 for the tooling venv |
| `.build-cache/sdk` | Official Calibre CI SDK; Python 3.14.10, Qt 6.10.1, native headers/libs, SIP/PyQt tools |
| `.build-cache/mint-overlay` | Extracted Mint packages; no dpkg installation or maintainer scripts |
| `.build-cache/uv-cache` | Python package downloads/build cache |
| `.venv` | 65 resolved Python packages; Ruff 0.17.4 and ty 0.0.99 |
| `.build-cache/dev-env.sh` | Session-local environment selecting this private stack |

The uv unmanaged installer avoids shell-profile modifications; see
[uv installer options](https://docs.astral.sh/uv/reference/installer/).

SDK URL:
`https://download.calibre-ebook.com/ci/calibre7/linux-64.tar.xz`

Downloaded SDK SHA-256:
`f3069b2872a3773997492efdddd6ef271a8049ce203d26a4cb0e77fa6eaddc2a`

The SDK was 365,972,236 compressed bytes, about 1.7 GiB extracted. Total ignored
build/tool/download cache is about 4 GiB. The archive is a rolling CI resource;
record/check its hash before reusing these exact results with a later download.
SDK pkg-config files were relocated from `/sw/sw` to the private SDK prefix.
Qt's existing `qt.conf` already uses a relative prefix.

The overlay was made using `apt-get download` followed by `dpkg-deb -x`, for:

```text
libfreetype-dev libpng-dev libbrotli-dev libbz2-dev
libgl-dev libglx-dev libegl-dev libopengl-dev
libxkbcommon-dev libxkbcommon-x11-dev libxcb-xkb-dev libx11-xcb-dev
cmake cmake-data librhash0 libjsoncpp25
```

These cover the host dependencies omitted from the SDK. Overlay pkg-config
prefixes point inside the overlay, and development linker symlinks resolve to
existing host runtime libraries where appropriate. Additional existing host
runtime dependencies were not reinstalled.

Generated development resources absent from the checkout were copied **read
only from** `/opt/calibre/resources` into ignored checkout resource locations:
localization, MathJax, hyphenation/fonts, CA certificates, recipes and generated
resource indexes. Production resources were not edited. An initial interrupted
parallel compile left zero-byte object files; those generated artifacts were
removed and rebuilt before validating module imports.

To reuse the configured environment in a new shell:

```sh
cd /home/bill/Development/calibre
. .build-cache/dev-env.sh
./setup.py build
QT_QPA_PLATFORM=offscreen ./setup.py rapydscript
QT_QPA_PLATFORM=offscreen ./setup.py test --test-module db --test-module dbcli
```

The environment script selects SDK Python, qmake, CMake and library/pkg-config
paths only for that shell. Keep it out of production launchers. Preferences,
cache, temp and XDG data/Trash are isolated below
`/tmp/calibre-phase2-verification`; use a **different** config/cache for desktop
GUI testing than for concurrently running unit tests.

## Build, tests and quality results

| Check | Result |
| --- | --- |
| Native build | Passed: 34 extensions plus the headless Qt plugin |
| Native import verification | 33 Python extensions imported outside sandbox; SQLite and QPA plugins are not Python modules |
| RapydScript build | Passed |
| Standard setup database + CLI test runner | 265 tests: 264 passed, 1 Windows-only skip, no failures/errors |
| Phase 2 formatting, lint, type checks | Passed, including both sync modules and link-manager/GUI smoke tests |
| Desktop main GUI verification | Passed with local metadata snapshot and original book paths |
| Standalone offscreen GUI smoke | Passed, including startup guard, toolbar migration and read-only monitoring |
| Original book hashes / link verification | All 14 unchanged and verified; 11 are Iron Man volumes |
| Repository-wide lint | Completed, not globally green: 535 diagnostics in older files; no Phase 2 module diagnostics |
| Repository-wide type check | Completed, not globally green: 17 existing diagnostics in retired Indexed Library modules |

Full-check logs are under `/tmp/calibre-phase2-verification`. Global failures are
not missing dependencies anymore. No blanket lint suppression or unrelated
Indexed Library rewrite was added to hide them. Phase 2 source checks used the
normal `setup.py check --fix --no-editor`, `type_check` and `fmt --check-only`
commands with explicit affected-file arguments.

Quality fixes add missing annotations, validate numeric series indexes, and
handle a missing title. Desktop testing also exposed a startup race: the sync
monitor could run before `Main.current_db` existed after failed/slow startup.
Monitoring now starts at `initialization_complete` and safely ignores a GUI
without an initialized database. The smoke test exercises that guard.

The standard test runner found four existing Phase 1 GUI tests creating
`QApplication` in its own worker. They now run their GUI portions in child
processes using Calibre's `fork_job`, retaining their setup/assertions/cleanup.
That made the standard runner usable without the earlier direct-unittest
workaround. The SDK supplies `apsw.shell`, so the earlier dump/rebuild skips no
longer apply.

## Desktop Iron Man workflow and source protection

The existing test library is:

```text
/run/user/1000/gvfs/smb-share:server=openmediavault.local,share=mediapool/Media/Comics/Calibre-Comics
```

It contains 14 CBZ records: 11 Iron Man volumes (IDs 4–14) and 3 Green Arrow
books. Before launching the GUI, all 14 originals were SHA-256 hashed. The
source SQLite integrity check returned `ok`.

Direct Calibre opening of that existing NAS database fails with
`apsw.ReadOnlyError: attempt to write a readonly database`. It was not repaired,
replaced or made writable. Instead, SQLite's read-only backup API made a
consistent disposable **metadata-only** snapshot at:

```text
/tmp/calibre-phase2-verification/local-test-db-reset/metadata.db
```

The desktop test used `CALIBRE_OVERRIDE_DATABASE_PATH` for that local snapshot
only. The GUI still opened the original managed books path and resolved the
original files. This is a test harness arrangement, not conversion of the
original library into Phase 1 separated storage or approval of an override for
production. No ebook files were copied.

A fresh profile initially triggered Calibre's automatic Quick Start Guide
import. Only that newly generated sample was moved into
`/tmp/calibre-phase2-verification/auto-imported-quick-start-guide`, and its empty
new author folder was removed. The local metadata snapshot was recreated from
the original 14-record database and `quick_start_guide_added` was set in the
isolated profile before the successful rerun. The original database still has
14 records and all 14 original ebook hashes are unchanged.

The successful run used the **actual X11 main Calibre GUI**, not a dialog stub:

1. Opened the original test-library book paths using the local snapshot.
2. Located and clicked the dedicated **Sync Komga Library** toolbar button.
3. Selected the fresh disposable output below. The automated driver supplied
   this path at the folder-picker boundary; sync dialog/buttons/engine were real.
4. Displayed 14 proposed additions. The output remained empty during preview.
5. Clicked **Apply previewed changes**. Reported 14 changes and 14 verified links.
6. Repeated preview: zero pending changes. Automatic monitoring also reported
   zero pending changes without applying another synchronization.
7. Shut down the GUI cleanly, closed the local database and stopped its workers.

Only link output:

```text
/tmp/calibre-phase2-verification/iron-man-gui-output
```

All 14 symlinks point to their exact original targets, resolve to the same files,
and were read through to compare SHA-256 with the before hashes. There are no
duplicate CBZ links and no pending recovery journal. Source record count and
removal of the auto-imported guide were checked afterwards.

Artifacts under `/tmp/calibre-phase2-verification` include:
`main-gui.png`, `actual-preview.png`, `actual-sync-result.png`,
`actual-gui-results.json`, `original-hashes-before.json`, and
`hash-verification-results.json`. Screenshots were visually inspected.
The temporary GUI driver and hash scripts are retained alongside the results.

## What still prevents a real Komga scan

This milestone does **not** claim a successful container scan:

- Output is deliberately local `/tmp` test output, not a directory mounted into
  the Komga container/LXC. No production reader directory was configured.
- Absolute symlinks target desktop GVfs session paths under `/run/user/1000`.
  Those paths have not been shown to exist inside the Komga environment.
  Mounting only the output directory will not make those targets resolvable.
- The actual Komga container ID/host, mount namespace, UID/GID permissions,
  library path and scan configuration still need read-only inspection and a
  separately approved disposable reader-visible test location.
- The current prototype has no source-to-container path mapping feature.
  A common path namespace or an explicit, validated mapping is required first.
- Komga's handling of the resulting series layout, symlinks and embedded CBZ
  metadata must be verified by an actual disposable library scan/read test.

Komga's [container documentation](https://komga.org/docs/installation/docker/)
requires making media available inside the container. No container or system
service was changed, no remote scan was triggered, no production Komga/Kavita
output was touched, and nothing was pushed to GitHub.
