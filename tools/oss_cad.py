"""Pinned OSS CAD Suite identity and an inventory of files, links and executable bits."""
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import platform
import tarfile

HERE=Path(__file__).resolve().parent
CONFIG=HERE/'oss_cad.json'

def digest(path):
    h=hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda:stream.read(1024*1024),b''):h.update(block)
    return h.hexdigest()

def platform_key():
    system=platform.system().lower();machine=platform.machine().lower()
    return system+'-'+{'x86_64':'x64','amd64':'x64','aarch64':'arm64'}.get(machine,machine)

def config(key=None):
    data=json.loads(CONFIG.read_text());key=key or platform_key()
    if data.get('schema_version')!=1 or key not in data['platforms']:raise ValueError('unsupported OSS CAD platform: '+key)
    return data,key,data['platforms'][key]

def inventory(home):
    home=Path(home).resolve()
    if not home.is_dir():raise ValueError('OSS CAD Suite directory missing: '+str(home))
    result={}
    for path in sorted(home.rglob('*')):
        name=path.relative_to(home).as_posix()
        if path.is_symlink():
            target=os.readlink(path)
            if not path.resolve().is_relative_to(home):raise ValueError('toolchain link escapes installation: '+name)
            result[name]=dict(kind='symlink',target=target)
        elif path.is_file():result[name]=dict(kind='file',sha256=digest(path),execute=path.stat().st_mode & 0o111)
        elif not path.is_dir():raise ValueError('unexpected toolchain file type: '+name)
    if not result:raise ValueError('empty OSS CAD Suite')
    return result

def tree_digest(records):
    return hashlib.sha256(json.dumps(records,sort_keys=True,separators=(',',':'),ensure_ascii=True).encode()).hexdigest()

def verify(home,key=None):
    data,key,spec=config(key);files=inventory(home);observed=tree_digest(files)
    if observed!=spec['tree_sha256']:raise ValueError('OSS CAD Suite content differs from pinned installation: '+key)
    return dict(root=str(Path(home).resolve()),platform=key,release=data['release'],archive_sha256=spec['sha256'],tree_sha256=observed,files=len(files))

def extract(archive,destination):
    with tarfile.open(archive,'r:gz') as tar:
        for member in tar.getmembers():
            parts=PurePosixPath(member.name).parts
            if not parts or parts[0]!='oss-cad-suite' or '..' in parts:raise ValueError('archive member outside toolchain')
        tar.extractall(destination,filter='data')

def bin_path(home,name):
    path=Path(home).absolute()/'bin'/name
    if not path.is_file() or not os.access(path,os.X_OK):raise ValueError('missing executable: '+str(path))
    return str(path)

def prepare_environment():
    # Bundled Python helpers must not modify the pinned installation on import.
    os.environ['PYTHONDONTWRITEBYTECODE']='1'
