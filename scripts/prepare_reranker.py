"""Download and verify pinned reranker assets before building the image."""
import argparse
import hashlib
import json
import os
import shutil
import tempfile
import zipfile
from pathlib import Path, PurePosixPath
from urllib.parse import urlparse
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / 'backend/model_assets/manifest.json'
MAX_ARCHIVE = 250 * 1024 * 1024


def digest(path):
    checksum = hashlib.sha256()
    with path.open('rb') as source:
        for block in iter(lambda: source.read(1024 * 1024), b''):
            checksum.update(block)
    return checksum.hexdigest()


def prepare(manifest, destination, archive=None):
    model, files = manifest['model'], manifest['files']
    if Path(model).name != model or model in ('.', '..') or not files or any(Path(name).name != name or name in ('.', '..') for name in files):
        raise ValueError('Unsafe model manifest paths')
    if urlparse(manifest['source_url']).scheme != 'https':
        raise ValueError('Model source must use HTTPS')
    with tempfile.TemporaryDirectory() as temp:
        temp = Path(temp)
        downloaded = temp / 'archive.zip'
        if archive is None:
            with urlopen(manifest['source_url'], timeout=60) as source, downloaded.open('wb') as output:
                size = 0
                while block := source.read(1024 * 1024):
                    size += len(block)
                    if size > MAX_ARCHIVE:
                        raise ValueError('Archive exceeds size limit')
                    output.write(block)
        else:
            downloaded = Path(archive)
            if downloaded.stat().st_size > MAX_ARCHIVE:
                raise ValueError('Archive exceeds size limit')
        if digest(downloaded) != manifest['archive_sha256']:
            raise ValueError('Archive checksum mismatch')
        with zipfile.ZipFile(downloaded) as z:
            names = set()
            for info in z.infolist():
                path = PurePosixPath(info.filename)
                if path.is_absolute() or '..' in path.parts or '\\' in info.filename:
                    raise ValueError('Unsafe archive path')
                if info.filename in names:
                    raise ValueError('Duplicate archive entry')
                names.add(info.filename)
            for name, expected in files.items():
                info = z.getinfo(f'{model}/{name}')
                if info.is_dir() or info.file_size > MAX_ARCHIVE or (info.external_attr >> 16) & 0o170000 == 0o120000:
                    raise ValueError('Unsafe archive entry')
                target = temp / name
                with z.open(info) as source, target.open('wb') as output:
                    shutil.copyfileobj(source, output, 1024 * 1024)
                if digest(target) != expected:
                    raise ValueError('Model asset checksum mismatch')
        output_dir = Path(destination) / model
        output_dir.mkdir(parents=True, exist_ok=True)
        for name in files:
            os.replace(temp / name, output_dir / name)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--archive', type=Path)
    args = parser.parse_args()
    prepare(json.loads(MANIFEST.read_text()), MANIFEST.parent, args.archive)


if __name__ == '__main__':
    main()
