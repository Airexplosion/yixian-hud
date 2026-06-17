# -*- coding: utf-8 -*-
"""把 counter.remaining()(牌名→剩数)映射成 Hud.SetPool 的 'id:剩|id:剩' 串。
牌名查不到 card_id 的丢弃;剩 0(删空)保留以便 overlay 置灰。"""


def pool_payload(remaining, name_to_id):
    parts = []
    for name, cnt in remaining.items():
        cid = name_to_id.get(name)
        if cid is None:
            continue
        parts.append("%d:%d" % (int(cid), int(cnt)))
    return "|".join(parts)
