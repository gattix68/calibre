#!/usr/bin/env python3
"""Test conservative filesystem checks without touching NAS mounts."""
import importlib.util
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FILE = ROOT / 'src/calibre/db/indexed_storage_validation.py'
spec = importlib.util.spec_from_file_location('indexed_storage_validation', FILE)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)


class IndexedStorageValidationTests(unittest.TestCase):
    def test_local_and_nested_network_mounts(self):
        with tempfile.TemporaryDirectory() as temp:
            directory = Path(temp).resolve()
            parent = directory.parent
            mountinfo = (
                f'20 1 8:1 / {parent} rw - ext4 /dev/sda1 rw\n'
                f'21 20 0:44 / {directory} rw - cifs //nas/books rw\n'
            )
            self.assertEqual(mod.linux_filesystem_type(directory, mountinfo), 'cifs')
            with self.assertRaises(mod.UnverifiedIndexedStorage):
                mod.require_local_indexed_storage(directory, platform='linux', mountinfo_text=mountinfo)
            local = f'20 1 8:1 / {parent} rw - ext4 /dev/sda1 rw\n'
            self.assertEqual(mod.require_local_indexed_storage(
                directory, platform='linux', mountinfo_text=local), 'ext4')

    def test_unknown_and_unimplemented_platforms_fail_closed(self):
        with tempfile.TemporaryDirectory() as temp:
            for platform in ('darwin', 'win32'):
                with self.assertRaises(mod.UnverifiedIndexedStorage):
                    mod.require_local_indexed_storage(temp, platform=platform)
            unknown = f'1 0 0:1 / {Path(temp).resolve()} rw - mysteryfs source rw'
            with self.assertRaises(mod.UnverifiedIndexedStorage):
                mod.require_local_indexed_storage(temp, platform='linux', mountinfo_text=unknown)
            with self.assertRaises(mod.UnverifiedIndexedStorage):
                mod.require_local_indexed_storage(temp, platform='linux', mountinfo_text='')

    def test_escaped_mountpoints(self):
        self.assertEqual(mod._unescape_mount('/media/My\\040Books'), '/media/My Books')


if __name__ == '__main__':
    unittest.main(verbosity=2)
