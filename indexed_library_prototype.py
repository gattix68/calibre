#!/usr/bin/env python3
"""Isolated proof of concept for external format references.

Run with: python3 indexed_library_prototype.py
This script uses only an in-memory SQLite database and temporary files.
It does not import Calibre or touch an existing Calibre library.
"""
import hashlib
import sqlite3
import tempfile
from pathlib import Path


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class IndexedRegistry:
    def __init__(self) -> None:
        self.db = sqlite3.connect(":memory:")
        self.db.execute("PRAGMA foreign_keys=ON")
        self.db.executescript("""
            CREATE TABLE books (
                id INTEGER PRIMARY KEY,
                title TEXT NOT NULL
            );
            CREATE TABLE indexed_files (
                book_id INTEGER NOT NULL REFERENCES books(id) ON DELETE CASCADE,
                format TEXT NOT NULL COLLATE NOCASE,
                file_path TEXT NOT NULL,
                file_size INTEGER NOT NULL,
                modified_time_ns INTEGER NOT NULL,
                PRIMARY KEY (book_id, format)
            );
        """)

    def register(self, book_id: int, title: str, fmt: str, path: Path) -> None:
        path = path.resolve(strict=True)
        if not path.is_file():
            raise ValueError("Not a regular file")
        stat = path.stat()
        fmt = fmt.upper().lstrip(".")
        if not fmt or path.suffix.lower() != "." + fmt.lower():
            raise ValueError("Format does not match file extension")
        with self.db:
            self.db.execute(
                "INSERT INTO books(id, title) VALUES (?, ?) "
                "ON CONFLICT(id) DO NOTHING", (book_id, title)
            )
            self.db.execute(
                "INSERT INTO indexed_files(book_id, format, file_path, file_size, modified_time_ns) "
                "VALUES (?, ?, ?, ?, ?) "
                "ON CONFLICT(book_id, format) DO UPDATE SET "
                "file_path=excluded.file_path, file_size=excluded.file_size, "
                "modified_time_ns=excluded.modified_time_ns",
                (book_id, fmt, str(path), stat.st_size, stat.st_mtime_ns),
            )

    def resolve(self, book_id: int, fmt: str) -> Path | None:
        row = self.db.execute(
            "SELECT file_path FROM indexed_files WHERE book_id=? AND format=?",
            (book_id, fmt.upper()),
        ).fetchone()
        return Path(row[0]) if row else None

    def set_title(self, book_id: int, title: str) -> None:
        with self.db:
            self.db.execute("UPDATE books SET title=? WHERE id=?", (title, book_id))

    def remove_book(self, book_id: int) -> None:
        with self.db:
            self.db.execute("DELETE FROM books WHERE id=?", (book_id,))


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="calibre-indexed-poc-") as tmp:
        original = Path(tmp) / "example.epub"
        original.write_bytes(b"Disposable test content: not a real EPUB")
        before = digest(original)
        registry = IndexedRegistry()
        registry.register(1, "Original title", "EPUB", original)
        assert registry.resolve(1, "epub") == original
        registry.set_title(1, "Updated title")
        assert registry.resolve(1, "EPUB") == original
        assert digest(original) == before
        registry.remove_book(1)
        assert registry.resolve(1, "EPUB") is None
        assert original.exists() and digest(original) == before
        print("PASS: registration, resolution, metadata edit and index removal")
        print("PASS: original file unchanged and preserved")


if __name__ == "__main__":
    main()
