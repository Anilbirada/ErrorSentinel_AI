from __future__ import annotations
import os, shutil
from pathlib import Path
from app.errors.normalizer import normalize_code
class TxtRegistry:
    def __init__(self,path:Path): self.path=path; path.parent.mkdir(parents=True,exist_ok=True); path.touch(exist_ok=True)
    def get_all_codes(self)->set[str]: return {normalize_code(x) for x in self.path.read_text(encoding="utf-8").splitlines() if x.strip()}
    def exists(self,code:str)->bool: return normalize_code(code) in self.get_all_codes()
    def count(self)->int: return len(self.get_all_codes())
    def backup(self)->Path:
        target=self.path.with_suffix(".backup.txt"); shutil.copy2(self.path,target); return target
    def add_codes(self,codes:set[str])->None:
        all_codes=sorted(self.get_all_codes()|{normalize_code(x) for x in codes}); temp=self.path.with_suffix(".tmp")
        temp.write_text("\n".join(all_codes)+("\n" if all_codes else ""),encoding="utf-8"); os.replace(temp,self.path)
