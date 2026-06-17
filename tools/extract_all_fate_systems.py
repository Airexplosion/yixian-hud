"""Extract all three fate/talent catalogs from the YiXianPai localization bundle.
Outputs id->{zh,en,tw} JSON for Talent(天命), FateStrategy(命途), FateBranch(仙命)."""
from __future__ import annotations
import json, re, warnings
from pathlib import Path
import UnityPy, UnityPy.config
UnityPy.config.FALLBACK_UNITY_VERSION="2022.3.40f1"; warnings.filterwarnings("ignore")
ROOT=Path(__file__).resolve().parent.parent
BUNDLE_DIR=Path(r"F:/Steam/steamapps/common/YiXianPai/YiXianPai_Data/StreamingAssets/aa/StandaloneWindows64/")
LOC=BUNDLE_DIR/"390aa60bf746a15c602ce953c17f21f3.bundle"
env=UnityPy.load(str(LOC)); terms=None
for obj in env.objects:
    if obj.type.name!="MonoBehaviour": continue
    try: tree=obj.read_typetree()
    except: continue
    if isinstance(tree,dict) and isinstance(tree.get("mSource"),dict) and "mTerms" in tree["mSource"]:
        terms=tree["mSource"]["mTerms"]; break

def collect(name_pfx, desc_pfx=None, cat_pfx=None):
    npat=re.compile(rf"^{re.escape(name_pfx)}_(\d+)$")
    dpat=re.compile(rf"^{re.escape(desc_pfx)}_(\d+)$") if desc_pfx else None
    names={}; descs={}
    for t in terms:
        term=str(t.get("Term","")); langs=t.get("Languages") or []
        zh=str(langs[0]).strip() if langs else ""
        m=npat.match(term)
        if m: names[int(m.group(1))]=zh; continue
        if dpat:
            m=dpat.match(term)
            if m: descs[int(m.group(1))]=zh
    out={}
    for i in sorted(names):
        out[str(i)]={"name":names[i]}
        if i in descs: out[str(i)]["desc"]=descs[i]
    return out

cats={
 "talent_tianming": collect("Talent","TalentDesc"),
 "fatestrategy_mingtu": collect("FateStrategyName","FateStrategyDesc"),
 "fatebranch_xianming": collect("FateBranchName","FateBranchDesc"),
}
for key,d in cats.items():
    base={k:v for k,v in d.items() if int(k)<10000}
    p=ROOT/"tools"/f"{key}.json"
    p.write_text(json.dumps(d,ensure_ascii=False,indent=1),encoding="utf-8")
    print(f"{key}: {len(d)} total, {len(base)} base(<10000) -> {p.name}")
