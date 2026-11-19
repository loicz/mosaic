#!/usr/bin/env python3
"""Create an offline Linux bundle without changing reusable toolchain files."""
from __future__ import annotations
import argparse
import hashlib
import io
import json
from pathlib import Path
import tarfile
from mission_env import DEFAULT_TOOLCHAIN

ROOT=Path(__file__).resolve().parents[1]


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--toolchain',type=Path,default=DEFAULT_TOOLCHAIN)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    args.toolchain=args.toolchain.expanduser().resolve()
    if args.output.exists(): parser.error('output already exists; choose a new archive')
    prefix='MOSAIC-0.5.0'
    manifest=dict(schema='mosaic.offline-bundle.v1',version='0.5.0',platform='Linux x86_64',
        required_host=['python3','bubblewrap','Linux user namespaces'],
        px4_commit='d6f12ad1c4f70ad3230afd7d86e971421e02fef4',
        gazebo='8.15.0',files={})
    args.output.parent.mkdir(parents=True,exist_ok=True)
    def filter_entry(info):
        path=info.name
        if any(part in ('.git','__pycache__','.pytest_cache') for part in Path(path).parts):return None
        if path.endswith('.pyc') or info.isdev() or info.isfifo():return None
        if '/toolchain/ubuntu24/' in path:
            relative=path.split('/toolchain/ubuntu24/',1)[1]
            if relative.split('/')[0] in ('dev','proc','sys','tmp','run','root'):return None
            if relative.startswith(('var/cache/apt/archives/','var/log/','var/lib/apt/lists/')):return None
        info.uid=0;info.gid=0;info.uname='';info.gname=''
        return info
    def text_file(archive,name,text,mode=0o644):
        data=text.encode();info=tarfile.TarInfo(prefix+'/'+name);info.size=len(data);info.mode=mode
        archive.addfile(info,io.BytesIO(data))
    with tarfile.open(args.output,'w:gz',compresslevel=3) as archive:
        for name in ('.github','.gitignore','CMakeLists.txt','README.md','LICENSE.md','THIRD_PARTY_NOTICES.md','CONTRIBUTING.md',
                     'apps','src','include','third_party','scripts','tests','config','models','dashboard','docs'):
            source=ROOT/name
            if source.exists():
                archive.add(source,arcname=prefix+'/project/'+name,filter=filter_entry)
                candidates=[source] if source.is_file() else source.rglob('*')
                for file in candidates:
                    if file.is_file() and '__pycache__' not in file.parts:
                        with file.open('rb') as stream:manifest['files'][str(file.relative_to(ROOT))]=hashlib.file_digest(stream,'sha256').hexdigest()
        archive.add(args.toolchain/'ubuntu24',arcname=prefix+'/toolchain/ubuntu24',filter=filter_entry)
        archive.add(args.toolchain/'work/venv',arcname=prefix+'/toolchain/work/venv',filter=filter_entry)
        px4=args.toolchain/'work/PX4-Autopilot'
        for name in ('LICENSE','build/px4_sitl_default/bin','build/px4_sitl_default/etc','Tools/simulation/gz/models/x500',
                     'Tools/simulation/gz/models/x500_base','Tools/simulation/gz/LICENSE'):
            archive.add(px4/name,arcname=prefix+'/toolchain/work/PX4-Autopilot/'+name,filter=filter_entry)
        # Empty runtime directories must exist before bwrap creates its mounts.
        for name in ('dev','proc','sys','tmp','run','root'):
            info=tarfile.TarInfo(prefix+'/toolchain/ubuntu24/'+name);info.type=tarfile.DIRTYPE;info.mode=0o755 if name!='tmp' else 0o1777;archive.addfile(info)
        launcher='''#!/usr/bin/env python3
import os,sys
from pathlib import Path
root=Path(__file__).resolve().parent
os.environ['MOSAIC_TOOLCHAIN']=str(root/'toolchain')
os.execv(sys.executable,[sys.executable,'-B',str(root/'project/scripts/mission_run.py'),*sys.argv[1:]])
'''
        text_file(archive,'run.py',launcher,0o755)
        text_file(archive,'BUNDLE.json',json.dumps(manifest,indent=2)+'\n')
        text_file(archive,'START.txt','MOSAIC 0.5.0 / Linux x86_64 offline runtime\nRun: python3 run.py\nOpen http://127.0.0.1:8766\nRequires host Python 3, bubblewrap and enabled unprivileged user namespaces.\nNo UWB, drone, cloud API or GPU required.\nFull operating notes: project/docs/mission-operations.md\nGazebo/PX4 and local-odometry/perching simulation assumptions apply.\n')
    digest=hashlib.file_digest(args.output.open('rb'),'sha256').hexdigest()
    args.output.with_suffix(args.output.suffix+'.sha256').write_text(digest+'  '+args.output.name+'\n')
    print(json.dumps(dict(archive=str(args.output),bytes=args.output.stat().st_size,sha256=digest)))


if __name__=='__main__':main()
