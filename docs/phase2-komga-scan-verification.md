# Phase 2 — actual Komga scan and read verification

Continues `23f988a6dd`, branch `feature/separated-library-storage`.
Verified locally on 2026-11-08 using a separate Komga **1.30.0** instance.
Machine-readable evidence: [scan results](phase2-komga-scan-results.json).

## Outcome and qualification

Actual Komga successfully scanned and analyzed the existing disposable symlink
view, recognized its series, generated covers, served comic pages and streamed
all complete books with hashes identical to the originals. A deep rescan created
no duplicate books or series. No Calibre implementation change was necessary.

This proves the scanner/analysis/read APIs against real linked CBZs in an
isolated filesystem namespace. It does **not** prove the current remote
production container's mounts or the browser reader UI. Those remain blocked by
missing remote access and an unavailable browser automation host, respectively.

## Installation inspection and access boundary

The project vault places the existing Komga installation on PVE2, historically
`192.168.0.186`, alongside separately hosted media services. It does not record
Komga's current guest/container ID, address, version or mount configuration.

Read-only inspection found:

- The Mint desktop has Java 21 and Docker. Its running Docker containers are
  `open-webui` and `itsnotes-dev-db`; no local Komga container was present.
- A batch SSH inspection of PVE2 using the available `sseod_ops` key was denied
  authentication. No remote commands ran and no credentials were changed.
- No Komga route is recorded in the available historical Caddy note. Production
  Caddy files were not opened or modified.
- Current Komga access details were requested asynchronously; they were not
  available during this verification. No broad network discovery, service
  recovery action or production configuration change was attempted.

The exact remote production installation/configuration remains uninspected.
Do not infer its version or mount list from the temporary instance tested here.

## Why mounting the link output alone is insufficient

The existing output lives on the desktop:

```text
/tmp/calibre-phase2-verification/iron-man-gui-output
```

Its absolute targets are desktop-session GVfs paths below:

```text
/run/user/1000/gvfs/smb-share:server=openmediavault.local,share=mediapool/Media/Comics/Calibre-Comics
```

A symlink is resolved in the reader process's filesystem namespace. A mount at
another path, including `/data`, does not rewrite that absolute target. The
remote LXC cannot automatically see the desktop's local `/tmp` or its GVfs
session mount.

Two isolated namespace probes used the **same 14 links**, without changing them:

| Namespace | Resolving links |
| --- | ---: |
| Output visible; GVfs target mount hidden inside the test namespace | 0 / 14 |
| Output and original absolute target paths both visible, read-only | 14 / 14 |

These demonstrate the required namespace relationship; they are not an audit
of the inaccessible production container's actual mappings.

## Safe test arrangement

The official standalone JAR was used, following Komga's documented
[standalone deployment](https://komga.org/docs/installation/jar/) and
[configuration options](https://komga.org/docs/installation/configuration/).
No Docker/LXC configuration or installed service was changed.

- Official release: `gotson/komga`, tag `1.30.0`, published 2026-11-04.
- JAR: `komga-1.30.0.jar`, 127,123,335 bytes.
- SHA-256 matched the release API's published asset digest:
  `cac820a26caf8c8cc2239351b5f7ac7c5ba13badfae5bb0ce2b2449f1dfd8ff3`.
- All test state: `/tmp/calibre-komga-scan-verification`.
- New database, tasks database, logs, home, temp, image cache and a disposable
  account. No production Komga database or account was used.
- Listener: **127.0.0.1:27600 only**. No Caddy, LAN exposure or firewall change.
- Java heap capped at 1 GiB, processor count at 2, process niceness at 10.
- Bubblewrap created a private mount/PID/IPC/UTS namespace. The host filesystem
  was exposed read-only, with only the dedicated test-state directory writable.
  `findmnt` confirmed the original GVfs mount was `ro` inside this namespace.
- Original ebooks and link output remained read-only. No ebook copies were
  created. Complete-book responses were hashed in bounded memory, not saved.
- The temporary library disabled extension repair, CBZ conversion, automatic
  trash emptying, scheduled scans and startup scanning. An explicit test scan
  and one explicit deep rescan were performed.

Representative launch command (the directory must first contain the verified
JAR and empty local config/home/tmp directories):

```sh
scan_root=/tmp/calibre-komga-scan-verification
bwrap --ro-bind / / --bind "$scan_root" "$scan_root" \
  --proc /proc --dev /dev --unshare-pid --unshare-ipc --unshare-uts \
  --die-with-parent --chdir "$scan_root" \
  /usr/bin/env -i HOME="$scan_root/home" LANG=C.UTF-8 PATH=/usr/bin:/bin \
  /usr/bin/nice -n 10 /usr/bin/java -Xmx1024m -XX:ActiveProcessorCount=2 \
  -Duser.home="$scan_root/home" -Djava.io.tmpdir="$scan_root/tmp" \
  -jar "$scan_root/komga-1.30.0.jar" \
  --komga.config-dir="$scan_root/config" \
  --server.address=127.0.0.1 --server.port=27600
```

This command belongs to a disposable test, not a service unit. Do not point it
at production configuration or bind a writable source mount. The generic
filesystem namespace was used instead of starting or reconfiguring a Docker
container on a production host.

## Scan, series, cover and book results

The test created one library rooted at the disposable link output through the
local REST API. Initial claim/library creation were allowed only on the fresh,
unclaimed instance with zero preexisting libraries. The temporary credentials
were written mode `0600` under the test root and are not committed.

| Check | Actual result |
| --- | --- |
| Linked books discovered | 14 / 14 |
| Media analysis | All 14 `READY` |
| Pages recognized | 2,742 total |
| Series | 4, with book counts 11 / 1 / 1 / 1 |
| Generated book cover responses | 14 valid decoded images |
| Reader page 10 | 14 valid decoded comic-page images |
| Full CBZ responses streamed and hashed | 14 / 14 match original SHA-256 |
| Completed deep rescan | Still 14 books and 4 series |
| Identity stability | All book and series IDs unchanged |
| Duplicate link records | None |
| Pending tasks after rescan | 0 |
| Temporary SQLite integrity | `ok` |
| Independent source hashes before/after | All 14 identical |

Recognized series:

- **Invincible Iron Man (2008-2012): 11 volumes**
- Green Arrow: Year One: 1 book
- Green Arrow: by Kevin Smith (2001-2007): 1 book
- Green Arrow: The Trial of Oliver Queen: 1 book

Book URLs recorded by Komga retain the series-organized symlink paths, rather
than switching the library to Calibre's author/title source directory layout.
The scan used the embedded ComicInfo metadata already present in the CBZs;
original metadata was neither edited nor exported.

Endpoints exercised on the temporary instance:

```text
GET/POST /api/v1/claim
GET/POST /api/v1/libraries
GET      /api/v1/books?unpaged=true
GET      /api/v1/series?unpaged=true
GET      /api/v1/books/{id}/thumbnail
GET      /api/v1/books/{id}/pages/10?convert=png&contentNegotiation=false
GET      /api/v1/books/{id}/file
POST     /api/v1/libraries/{id}/scan?deep=true
```

The deep-scan task completed successfully in the server log; its task queue was
empty before final counting. Unique book URLs and stable ID sets verify that
repeated scanning did not create duplicate book records. Each full-file HTTP
response matched the corresponding original, not merely a thumbnail or filename.

All 14 returned thumbnails and page-10 images were decoded with Pillow. The
Iron Man cover/page and the cover contact sheet were visually inspected. These
are actual images served by Komga, **not screenshots of its browser interface**.
Computer-use inventory returned no browsers and reported that the browser access
host was unavailable. Interactive reader controls/navigation remain unverified.

## Original protection, cleanup and regression checks

All originals were SHA-256 checked immediately before and independently after
scanning, page retrieval, complete-book streaming and deep rescanning. The
post-scan hashes equal both the new pre-scan hashes and the previous milestone's
expected hashes. No original ebook changed. The runtime's read-only namespace
also prevented writes to originals, covers, OPFs or the link tree.

Only the temporary Java PID with the exact disposable JAR argument was sent
SIGTERM. Komga logged graceful HTTP shutdown, closed both connection pools, and
exited. No temporary listener is intentionally left running. Test databases,
logs and derived images remain under the disposable root for review.

Calibre regression checks after this verification:

- `./setup.py build`: passed.
- `./setup.py rapydscript`: passed.
- `./setup.py test --test-module db --test-module dbcli`: 265 tests,
  264 passed, one Windows-only skip, no failures or errors.
- Scoped `setup.py check --fix --no-editor` and `type_check` on the existing
  Phase 2 engine/action/dialog: passed. No application code changed in this
  milestone; earlier repository-wide legacy quality failures remain separate.

Raw evidence in `/tmp/calibre-komga-scan-verification` includes `release.json`,
`api-docs.json`, `server.log`, `probe.log`, `results.json`, `library.json`,
`books.json`, `series.json`, `hashes-before.json`, `hashes-after.json`, the two
`namespace-*-targets.json` probes, `covers-contact-sheet.png`, and
`images/{calibre-id}-interior-10.png`. The local probe/hash scripts are retained
there. The committed results JSON contains a credential-free compact record.

## Remaining deployment work

1. Obtain read-only access to the actual Komga host/container and inspect its
   version, current media mounts, service identity and permissions.
2. Choose an approved, durable test-only path visible to that environment.
   Either identical absolute source paths must exist there, or the link manager
   needs an explicit validated host-to-reader path mapping. The desktop GVfs
   session path should not be assumed to be a durable remote namespace.
3. Verify scanning and interactive browser reading in that actual deployment,
   or a separately approved container alongside it, with its real UID/GID and
   storage protocol. An unrelated local namespace is not production certification.

No production mapping change was necessary for this proof. Any future change
to an existing production container, mapping or library requires approval first.
Seawatch and all other production services, existing reader libraries, and
production Caddy configuration were untouched. Nothing was pushed to GitHub.
