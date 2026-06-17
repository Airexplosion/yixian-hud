# -*- coding: utf-8 -*-
"""弈仙牌 id↔名 查询模块 — 写 bot/大脑时用名字而非数字。

四类映射 (json 同目录):
  卡牌/道韵   card_id_map.json     cardId -> 中文名          (道韵也是 cardId)
  仙命       fate_talent_map.json talentId -> {name,nameCn}  (TalentSelectionPanel, 突破后选)
  天衍       fate_id_map.json     strategyId -> 中文名        (FateStrategyPanel, 2轮后选)
  副职业     career_id_map.json   careerId(1-7) -> {enum,nameCn} (CareerSelectionPanel)

用法:
  from id_names import card_name, xianming_name, tianyan_name, career_name, id_of
  card_name(3)            -> '云剑•崩雪'
  xianming_name(30001)    -> '锻体'
  tianyan_name(9)         -> '云巅雷劫'
  career_name(4)          -> '画师'
  id_of('card', '云剑•崩雪') -> '3'     # 反查 (写策略用)
"""
import json, os

_DIR = os.path.dirname(os.path.abspath(__file__))
def _load(n): return json.load(open(os.path.join(_DIR, n), encoding="utf-8"))

_cards    = _load("card_id_map.json")      # {id: name}
_xianming = _load("fate_talent_map.json")  # {id: {name, nameCn, ...}}
_tianyan  = _load("fate_id_map.json")      # {id: nameCn}
_career   = _load("career_id_map.json")    # {id: {enum, nameCn}}

def card_name(cid):     return _cards.get(str(cid))
def daoyun_name(cid):   return _cards.get(str(cid))            # 道韵 = 卡
def xianming_name(tid): v = _xianming.get(str(tid)); return v["nameCn"] if v else None
def xianming_en(tid):   v = _xianming.get(str(tid)); return v["name"] if v else None
def tianyan_name(sid):  return _tianyan.get(str(sid))
def career_name(cid):   v = _career.get(str(cid)); return v["nameCn"] if v else None
def career_enum(cid):   v = _career.get(str(cid)); return v["enum"] if v else None

def _rev(d, key=None):
    r = {}
    for k, v in d.items():
        name = v[key] if (key and isinstance(v, dict)) else v
        if name not in r: r[name] = k          # first id wins (base tier)
    return r

_REV = {
    "card":     _rev(_cards),
    "daoyun":   _rev(_cards),
    "xianming": _rev(_xianming, "nameCn"),
    "tianyan":  _rev(_tianyan),
    "career":   _rev(_career, "nameCn"),
}

def id_of(kind, name):
    """反查: kind in {card,daoyun,xianming,tianyan,career}, name=中文名 -> id(str) or None"""
    return _REV.get(kind, {}).get(name)

if __name__ == "__main__":
    print("卡 3         ->", card_name(3))
    print("仙命 30001    ->", xianming_name(30001), "/", xianming_en(30001))
    print("天衍 9        ->", tianyan_name(9))
    print("副职 4        ->", career_name(4), career_enum(4))
    print("反查 云剑•崩雪 ->", id_of("card", "云剑•崩雪"))
    print("counts: cards=%d 仙命=%d 天衍=%d 副职=%d" % (len(_cards), len(_xianming), len(_tianyan), len(_career)))
