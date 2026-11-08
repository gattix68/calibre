# Indexed Library first-build test (Linux)

This is a development build test guide for the current `feature/indexed-library`
branch. It is not a release installer.

## 1. Update the local checkout

```bash
cd ~/Development/calibre
git switch feature/indexed-library
git pull --ff-only origin feature/indexed-library
```

## 2. Launch Calibre from this source checkout

Use the Calibre Python runtime and an isolated development configuration:

```bash
CALIBRE_DEVELOP_FROM="$HOME/Development/calibre/src" \
CALIBRE_CONFIG_DIRECTORY="$HOME/Development/calibre-dev-config" \
calibre-debug -g
```

This leaves the normal Calibre configuration and existing libraries untouched.

## 3. Create a disposable Indexed Library

1. Make an empty local directory for the Indexed Library database, on the workstation's local SSD.
2. Make a separate test source directory containing a few copies of ebooks.
3. In the development Calibre window, use the **Indexed Library** toolbar action and choose **Create Indexed Library**.
4. Select the empty local database directory and the test source directory.
5. Confirm creation. The dialog reports discovered and registered books.

Do not use the production ebook collection for this first test.

## 4. Open the new library

Use Calibre's normal **Library** switch control and choose the option to use an existing library. Select the local Indexed Library database directory created above.

The new Indexed Library should open as a Calibre library and show the registered books. The separate **Indexed Library** toolbar action should identify the loaded library by name.

## 5. Test a filename change

1. Leave the Indexed Library open in Calibre.
2. In the file manager, rename one test ebook in the source directory. Keep its file extension unchanged and do not move it to another filesystem.
3. Return to Calibre and choose **Indexed Library → Sync Library**.
4. The report should show one renamed file reconciled.
5. The book should remain in the library, and Calibre should resolve its format from the new external path.

The synchronization updates Calibre's database mapping only. It does not rename, move, copy, or delete source files.

## Scope of this first build

- Intended for Linux testing first. The current creator uses Linux-specific local-storage safeguards.
- Rename matching uses filesystem device/inode identity, so test a rename within the same filesystem.
- Ambiguous or unmatched files are reported and left unchanged.
- Metadata editing, conversions, adding/removing formats, and other normal Calibre write workflows are not part of this first-build test. Use a disposable source collection and limit testing to create, open, rename, and sync.
