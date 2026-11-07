#!/usr/bin/env python3
"""Standalone tests for ComicInfo.xml metadata extraction."""
import importlib.util
import tempfile
import zipfile
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
MODULE = ROOT / 'src/calibre/db/indexed_metadata_extraction.py'
spec = importlib.util.spec_from_file_location('indexed_metadata_extraction', MODULE)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


COMICINFO = b'''<?xml version="1.0" encoding="utf-8"?>
<ComicInfo>
  <Title>Doctor Strange v05</Title>
  <Series>Doctor Strange</Series>
  <Number>5</Number>
  <Writer>Jed MacKay</Writer>
  <Publisher>Marvel</Publisher>
  <Year>2022</Year>
  <Month>8</Month>
  <Day>3</Day>
  <Summary>Collected stories.</Summary>
  <Genre>Fantasy, Superhero</Genre>
  <LanguageISO>en</LanguageISO>
</ComicInfo>'''


class ComicInfoTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.cbz = Path(self.tmp.name) / 'sample.cbz'
        with zipfile.ZipFile(self.cbz, 'w') as archive:
            archive.writestr('ComicInfo.xml', COMICINFO)
            archive.writestr('001.jpg', b'page')

    def test_cbz_comicinfo_fields_and_provenance(self):
        values, sources = module._comicinfo_metadata(str(self.cbz), 'cbz')
        self.assertEqual(values['title'], 'Doctor Strange v05')
        self.assertEqual(values['series'], 'Doctor Strange')
        self.assertEqual(values['series_index'], 5.0)
        self.assertEqual(values['authors'], ['Jed MacKay'])
        self.assertEqual(values['publisher'], 'Marvel')
        self.assertEqual(values['publication_date'], '2022-08-03')
        self.assertEqual(values['comments'], 'Collected stories.')
        self.assertEqual(values['tags'], ['Fantasy', 'Superhero'])
        self.assertEqual(values['languages'], ['en'])
        self.assertTrue(all(x == 'ComicInfo.xml' for x in sources.values()))

    def test_case_insensitive_nested_member_name(self):
        with zipfile.ZipFile(self.cbz, 'w') as archive:
            archive.writestr('metadata/COMICINFO.XML', COMICINFO)
        values, _ = module._comicinfo_metadata(str(self.cbz), 'cbz')
        self.assertEqual(values['series'], 'Doctor Strange')

    def test_oversized_comicinfo_rejected(self):
        with zipfile.ZipFile(self.cbz, 'w') as archive:
            archive.writestr('ComicInfo.xml', b' ' * (module.MAX_COMICINFO_BYTES + 1))
        with self.assertRaises(ValueError):
            module._comicinfo_metadata(str(self.cbz), 'cbz')

    def test_missing_comicinfo_returns_no_override(self):
        with zipfile.ZipFile(self.cbz, 'w') as archive:
            archive.writestr('001.jpg', b'page')
        values, sources = module._comicinfo_metadata(str(self.cbz), 'cbz')
        self.assertEqual(values, {})
        self.assertEqual(sources, {})


if __name__ == '__main__':
    unittest.main(verbosity=2)
