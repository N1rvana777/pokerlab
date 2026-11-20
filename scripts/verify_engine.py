"""Verify the exact upstream revision and the documented PokerLab extension."""
from pathlib import Path
import subprocess

ROOT=Path(__file__).resolve().parents[1]
REV='9d1509fe5077d019825f833eed04b16d342dfda1'

def verify():
    def git(*args):
        return subprocess.run(['git','-C',str(ROOT/'third_party/postflop-solver'),*args],
                              capture_output=True,text=True,check=True).stdout
    if git('rev-parse','HEAD').strip()!=REV:
        raise RuntimeError('Engine revision differs from pinned commit')
    untracked=git('ls-files','--others','--exclude-standard','--','src').strip()
    if untracked:
        raise RuntimeError('Unrecorded engine source files (include them in the documented patch): '+untracked)
    expected=(ROOT/'third_party/patches/expanded-suits.patch').read_text(encoding='utf-8')
    if git('diff','HEAD')!=expected:
        raise RuntimeError('Engine edits differ from documented expanded-suits.patch')
    print('Pinned engine + documented expanded-suits patch verified')

if __name__=='__main__':verify()
