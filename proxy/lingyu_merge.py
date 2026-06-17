"""
灵羽 (Spirit Feather) merge mechanic.

Game rule (confirmed against shadow_log traces):
  - Only 灵羽 lv2 or lv3 can merge with another card.
  - The merge target must be level 1.
  - The target card must give qi or agility (or both).
  - Result: the 灵羽 slot is replaced by the target card at the 灵羽's level
    (lv2 or lv3). The source target stays in place (not consumed) — multiple
    灵羽 can merge with the same target, and the lv1 source card is still
    on the board after the merge.

The merge resolves SERVER-SIDE at battle-time. The wire just shows an
ordinary `MoveCardReq` placement — no merge marker. This means the shadow
can't see the merge until the next GameStatus snapshot. To predict damage
correctly before battle, we apply this substitution to the predicted board
before it's handed to yisim.

If a 灵羽 lv2/3 sits on the board with NO eligible lv1 target nearby, no
substitution happens — the card stays as 灵羽, and the damage calculator
should refuse to estimate (灵羽 itself has no yisim implementation).

Card name list is the union of lv1 cards in yisim's swogi.json + card_actions.js
that emit qi (anima) or agility actions. Built once via tools/build_lingyu_targets.py.
"""

# Cards that ADD qi (anima) at lv1. Strict scan: only cards whose action graph
# contains a positive qi-add (literal `["qi", N>0]`, `add_c_of_x N "anima"`,
# `exhaust_x_to_add_y X "anima"`, conditional adds via `if_x_*_do`, etc.) at
# the target position. Cards that CONSUME or CHECK qi (e.g. `if_x_at_least_c_do
# qi 1 [reduce_c_of_x qi …]`) are excluded.
LINGYU_QI_TARGETS = frozenset({
    "两仪阵", "乾卦", "云剑·唤雨", "云剑·汇灵", "云剑·点星", "云剑·雪影飞",
    "云舞诀", "伤魂咒阵", "修罗吼", "修罗镇魂粽", "兑卦", "八宝杂粮粽",
    "冲霄破浪", "凝意诀", "剑灵葵", "化灵诀", "千里神行符", "向灵葵",
    "吸灵符", "咸肉粽", "培元丹", "天星·牵引", "天机·地煞", "天机·逆施",
    "天机·顺应", "天灵曲", "天髓葫芦", "孤虚金书", "崩天步", "巽卦",
    "引气剑", "悠然葫芦", "护灵符", "护身灵气", "抱气法", "探灵",
    "斩浪之印", "无名白鹿", "星弈·劫争", "星弈·拆", "星弈·立", "星罗棋布",
    "星轨推衍", "望星诀", "木灵·复苏", "木灵·春风拂", "木灵·暗香",
    "木灵·桃花印", "木灵印", "枣泥粽", "气吞星河", "气沉丹田", "气若悬河",
    "气贯长虹", "水晶冰粽", "水气符", "水灵·悠然", "水灵·泉涌",
    "水灵·润木", "水灵·腾浪", "水灵印", "水灵阵", "浑天印", "浑天运笔",
    "浩然正气", "混元化灵", "清心咒", "火灵·焚脉诀", "火灵·聚炎", "火灵印",
    "灵感迸发", "灵枢剑阵", "灵气灌注", "灵气锻身", "灵犀剑阵",
    "灵玄迷踪步", "狂剑·星云", "玄灵愈体", "瑞雪迎春", "画饼充饥",
    "白鹤亮翅", "百兽灵剑阵", "百草神炼鼎", "百鸟灵剑诀", "研墨",
    "空间灵田", "算无遗策", "紫气东来", "红枣粽", "罗刹扑", "聚气咒",
    "聚灵丹", "聚灵心法", "聚灵鲛珠", "腊肉粽", "落花有意", "蜜枣粽",
    "蜜饯果粽", "调色", "起势", "踏鹤飞云", "转弦合调", "轰雷掣电",
    "轻剑", "野渡之印", "锻灵指", "阴符玉简", "韵灵剑", "风冥爪",
    "飞云丹", "飞灵闪影剑", "飞鸿踏雪", "香辣粽",
})

# Cards that ADD agility (身法) at lv1.
LINGYU_AGI_TARGETS = frozenset({
    "冥夜迷踪步", "冥影身法", "冥月蟾光", "冲霄破浪", "凌空飞扫",
    "天地浩荡", "崩天步", "崩拳·闪击", "浩荡不息", "灵玄迷踪步",
    "破茧化蝶", "磅礴之势", "血影遁术", "踏破九霄", "踏鹤飞云", "转势",
    "逍遥连音曲", "醉卧逍遥", "锻神开海", "鹤步",
})

# Union of all eligible merge targets.
LINGYU_MERGE_TARGETS = LINGYU_QI_TARGETS | LINGYU_AGI_TARGETS

LINGYU_NAME = "灵羽"


def _normalize_name(name: str) -> str:
    """Normalize separator characters so '云剑·点星' and '云剑•点星' match."""
    if not name:
        return ""
    return str(name).replace("•", "·").replace("・", "·")


def resolve_lingyu_merges(board):
    """Apply the 灵羽 merge rule to a predicted board.

    Args:
        board: list of ZoneCard-like objects (have .name, .level, .id) or None
               for empty slots.

    Returns:
        (new_board, unresolved_lingyu_slots)
          new_board: list with 灵羽 slots substituted by their merge target.
          unresolved_lingyu_slots: indices of 灵羽 lv2/3 that found no target.
    """
    if not board:
        return list(board or []), []

    def is_lingyu(c):
        return c is not None and _normalize_name(getattr(c, "name", "")) == LINGYU_NAME

    def is_target(c):
        if c is None:
            return False
        if int(getattr(c, "level", 1) or 1) != 1:
            return False
        return _normalize_name(getattr(c, "name", "")) in LINGYU_MERGE_TARGETS

    new_board = list(board)
    unresolved = []
    for i, c in enumerate(new_board):
        if not is_lingyu(c):
            continue
        lv = int(getattr(c, "level", 1) or 1)
        if lv < 2:
            continue
        # Find first lv1 target on the board whose name is in the merge set.
        # The source target is NOT consumed — it stays on the board.
        target = None
        for j, t in enumerate(new_board):
            if j == i:
                continue
            if is_target(t):
                target = t
                break
        if target is None:
            unresolved.append(i)
            continue
        # Substitute: create a copy of the target at the 灵羽's level.
        try:
            from shadow_state import ZoneCard
        except Exception:
            ZoneCard = None
        if ZoneCard is not None:
            new_card = ZoneCard(
                id=int(getattr(target, "id", 0)) + 10000 * (lv - 1),
                name=getattr(target, "name", ""),
                level=lv,
            )
        else:
            # Fallback: clone the target dict and bump level.
            new_card = type(target)(
                id=int(getattr(target, "id", 0)) + 10000 * (lv - 1),
                name=getattr(target, "name", ""),
                level=lv,
            )
        new_board[i] = new_card
    return new_board, unresolved
