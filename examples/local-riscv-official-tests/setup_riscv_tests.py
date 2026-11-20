#!/usr/bin/env python3
"""Download riscv-tests and riscv-test-env at their pinned commits and check their SHA-256.

Nothing of the downloaded sources is kept in this repository. --archives uses archive files
that were downloaded before (same names as the last part of each URL); they are checked the
same way.
"""
import argparse
import hashlib
import io
import json
from pathlib import Path
import sys
import tarfile
import urllib.request

HERE = Path(__file__).resolve().parent
PINS = HERE / 'riscv_tests.json'
RECORD = 'riscv-tests-source.json'


def sha256(data):
    return hashlib.sha256(data).hexdigest()


def extract(data, destination):
    """Regular files and directories only, below one top directory that is dropped."""
    files = {}
    with tarfile.open(fileobj=io.BytesIO(data)) as archive:
        members = archive.getmembers()
        tops = {Path(item.name).parts[0] for item in members if item.name and Path(item.name).parts}
        if len(tops) != 1:
            raise ValueError('archive must have a single top directory')
        for item in members:
            if item.pax_headers and item.name == 'pax_global_header':
                continue
            relative = Path(item.name)
            if relative.is_absolute() or '..' in relative.parts:
                raise ValueError('unsafe archive member')
            if item.issym() or item.islnk():
                continue  # not needed by this example; never followed
            if not (item.isfile() or item.isdir()):
                raise ValueError('unsafe archive member')
            target = destination.joinpath(*relative.parts[1:])
            if item.isdir():
                target.mkdir(parents=True, exist_ok=True)
            else:
                target.parent.mkdir(parents=True, exist_ok=True)
                with archive.extractfile(item) as content:
                    body = content.read()
                target.write_bytes(body)
                files[str(target.relative_to(destination))] = sha256(body)
    return files


def prepare(out, pins, fetch):
    """Create out with the pinned sources and a record of every file's hash."""
    if out.exists():
        raise ValueError('output exists; choose a new directory')
    archives = {}
    for name, source in pins['sources'].items():
        data = fetch(source['url'])
        if sha256(data) != source['sha256']:
            raise ValueError(f'download SHA256 mismatch: {name}')
        archives[name] = data
    out.mkdir(parents=True)
    record = dict(schema_version=1, sources={}, files={})
    for name, source in pins['sources'].items():  # riscv-tests first, then env into its empty directory
        directory = out / source['directory']
        files = extract(archives[name], directory)
        record['sources'][name] = dict(commit=source['commit'], url=source['url'], sha256=source['sha256'])
        record['files'].update({f"{source['directory']}/{path}": digest for path, digest in files.items()})
    (out / RECORD).write_text(json.dumps(record, indent=2, sort_keys=True) + '\n')
    return record


def download(url):
    with urllib.request.urlopen(url, timeout=120) as response:
        return response.read()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--archives', type=Path, help='directory holding the two archives; nothing is downloaded')
    args = parser.parse_args()
    pins = json.loads(PINS.read_text())
    fetch = download if args.archives is None else (lambda url: (args.archives / url.rsplit('/', 1)[1]).read_bytes())
    try:
        record = prepare(args.out, pins, fetch)
    except (OSError, ValueError, tarfile.TarError) as exc:
        print('SETUP_ERROR', exc, file=sys.stderr)
        return 1
    print('RISCV_TESTS_HOME:', args.out.resolve())
    for name, source in record['sources'].items():
        print(f"{name}: commit {source['commit']}, archive SHA256 {source['sha256']}")
    return 0


if __name__ == '__main__':
    sys.exit(main())
