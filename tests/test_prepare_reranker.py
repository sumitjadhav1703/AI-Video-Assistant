import hashlib
import io
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

from scripts.prepare_reranker import prepare


class PrepareRerankerTests(unittest.TestCase):
    def archive(self, name='model/config.json', content=b'good'):
        data = io.BytesIO()
        with zipfile.ZipFile(data, 'w') as z:
            z.writestr(name, content)
        return data.getvalue()

    def test_verified_archive_prepares_only_manifest_files(self):
        data = self.archive()
        manifest = {'model': 'model', 'source_url': 'https://example.test/model.zip', 'archive_sha256': hashlib.sha256(data).hexdigest(), 'files': {'config.json': hashlib.sha256(b'good').hexdigest()}}
        with tempfile.TemporaryDirectory() as directory, patch('scripts.prepare_reranker.urlopen', return_value=io.BytesIO(data)):
            prepare(manifest, Path(directory))
            self.assertEqual((Path(directory) / 'model' / 'config.json').read_bytes(), b'good')

    def test_bad_archive_hash_and_traversal_are_rejected(self):
        for name, sha in [('model/config.json', '0' * 64), ('../escape', None)]:
            data = self.archive(name)
            manifest = {'model': 'model', 'source_url': 'https://example.test/model.zip', 'archive_sha256': sha or hashlib.sha256(data).hexdigest(), 'files': {'config.json': hashlib.sha256(b'good').hexdigest()}}
            with self.subTest(name=name), tempfile.TemporaryDirectory() as directory, patch('scripts.prepare_reranker.urlopen', return_value=io.BytesIO(data)):
                with self.assertRaises(ValueError):
                    prepare(manifest, Path(directory))

    def test_file_hash_failure_does_not_install(self):
        data = self.archive()
        manifest = {'model': 'model', 'source_url': 'https://example.test/model.zip', 'archive_sha256': hashlib.sha256(data).hexdigest(), 'files': {'config.json': '0' * 64}}
        with tempfile.TemporaryDirectory() as directory, patch('scripts.prepare_reranker.urlopen', return_value=io.BytesIO(data)):
            with self.assertRaises(ValueError):
                prepare(manifest, Path(directory))
            self.assertFalse((Path(directory) / 'model').exists())
