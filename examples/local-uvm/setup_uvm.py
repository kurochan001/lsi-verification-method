#!/usr/bin/env python3
"""Explicitly download the unmodified Accellera UVM 2020-3.2 reference library."""
import argparse
import hashlib
from pathlib import Path
import tarfile
import tempfile
import urllib.request
URL='https://www.accellera.org/images/downloads/standards/uvm/1800.2-2020.3.2%20Release.gz'
SHA256='4664ac015f23c72106dd785906aa874d70932ea63f74b85de1e32fa5339c15eb'
def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--out',type=Path,required=True);a=p.parse_args()
    if a.out.exists():p.error('output exists; choose a new directory')
    with tempfile.TemporaryDirectory() as tmp:
        archive=Path(tmp)/'uvm.tar.gz'
        with urllib.request.urlopen(URL,timeout=60) as response:archive.write_bytes(response.read())
        if hashlib.sha256(archive.read_bytes()).hexdigest()!=SHA256:raise ValueError('download SHA256 mismatch')
        # extract only regular files/directories and check paths, compatible with Python 3.10+.
        with tarfile.open(archive) as source:
            members=source.getmembers()
            for item in members:
                relative=Path(item.name)
                if relative.is_absolute() or '..' in relative.parts or not (item.isfile() or item.isdir()):raise ValueError('unsafe archive member')
            a.out.mkdir(parents=True,exist_ok=False)
            for item in members:
                destination=a.out/item.name
                if item.isdir():destination.mkdir(parents=True,exist_ok=True)
                else:
                    destination.parent.mkdir(parents=True,exist_ok=True)
                    with source.extractfile(item) as content:destination.write_bytes(content.read())
    print('UVM_HOME:',a.out.resolve()/'1800.2-2020.3.2');print('Archive SHA256:',SHA256)
if __name__=='__main__':main()
