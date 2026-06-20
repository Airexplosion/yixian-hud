# YiXianHUD → yisim 伤害计算入参文档

> 生成日期：2026-06-20
> 覆盖范围：HUD 实际传给 yisim 的入参 + `yisim.simulate` 全部可接受参数

## 1. 调用链路

```
proxy_view.build_view_model(state)        # 组装 vm（me / opponent 视图模型）
        │  vm = { me:{board,fates,unlocked,hp,tipo,xiuwei,plantStacks,...},
        │         opponent:{board,fates,unlocked,hp,tipo,xiuwei,...} }
        ▼
hud_launcher.total_loop()                 # 主路径：整盘伤害（totalOnly）
        │  把 vm → 拼成 obj（下面第 2 节）→ JSON
        ▼
subprocess: node yisim_marginal.js  (stdin = obj JSON)
        │  yisim_marginal.buildOpts(obj) → simulate 的 opts
        ▼
web/yisim.bundle.js  →  yisim.simulate(slots, opts)
```

另有一条**边际伤害**旧路径 `native_hud/bridge/tool_bridge.py`，只传 `{board, talents}` 两个字段（最简，不含 playerState/plantStacks/opponent），现已被 `hud_launcher` 主路径取代，仅作历史保留。

Web 工具 (`web/ui.js` 的 `updateDamage`) 走的是同一个 `simulate`，HUD 的入参刻意对齐它。

---

## 2. HUD 当前实际传入的入参

### 2.1 发给 `yisim_marginal.js` 的 stdin JSON（`hud_launcher.py` 第 514-544 行）

| 字段 | 来源 | 说明 |
|------|------|------|
| `totalOnly` | 固定 `true` | 只算整盘一次（HUD 显示用），不算逐卡边际 |
| `board` | `me.board` | 我方摆牌 `[{name,level}|null,...]` |
| `talents` | `me.fates` | 我方仙命/天衍天赋对象数组（见 2.3） |
| `deckSlots` | `me.unlocked || len(board) || 8` | 解锁的牌位数 |
| `plantStacks` | `me.plantStacks` | 灵植成长层数 `{*_stacks字段: 层数}`（归元草加血等） |
| `playerState.hp` | `me.hp` | 当前血量 |
| `playerState.maxHp` | `me.hp` | （HUD 用当前 hp 当 maxHp） |
| `playerState.physique` | `me.tipo \|\| 0` | 体魄 |
| `playerState.maxPhysique` | `me.tipo \|\| 0` | |
| `playerState.cultivation` | `me.xiuwei \|\| 0` | 修为 |
| `opponent`（仅 matchup 开启且对手有牌） | `vm.opponent` | 见下 |
| `opponent.board` | `opp.board` | 对手摆牌 |
| `opponent.deckSlots` | `opp.unlocked \|\| len \|\| 8` | |
| `opponent.talents` | `opp.fates` | 对手天赋 |
| `opponent.playerState.{hp,maxHp,physique,maxPhysique,cultivation}` | `opp.hp/tipo/xiuwei` | 对手状态 |

### 2.2 `buildOpts` 把上面映射成 simulate 的 opts（`yisim_marginal.js` 第 22-44 行）

| simulate opts | 取值 | 备注 |
|---------------|------|------|
| `mode` | 有对手→`'matchup'`，否则 `'solo'` | HUD 不直接传 mode，由桥按是否有对手板自动判定 |
| `rollMode` | `j.rollMode \|\| 'average'` | **HUD 的 obj 没有设 rollMode → 永远 `'average'`** |
| `deckSlots` | 同上 | |
| `maxTurns` | 固定 `64` | 桥写死，HUD 不传 |
| `talents` | `j.talents` | |
| `playerState` | `j.playerState` | |
| `plantStacks` | `j.plantStacks` | |
| `opponentSlots` | `opp.board` 切片 → `toSlot` | 仅 matchup |
| `opponentState` | `opp.playerState` | 仅 matchup |
| `opponentTalents` | `opp.talents` | 仅 matchup |

### 2.3 slot / talent 对象形状

- **slot**（`toSlot` 产出）：普通卡 `{name, level, isDream:false}`；梦卡（名字以「梦」开头）`{name, level, phase:level, isDream:true}`。
- **talent**（`proxy_view._fates_to_talents`）：`{detected:true, position, phase, name, simulationKind, runtimeKey, grantedCardBaseIds}`。

---

## 3. `yisim.simulate(slots, options)` 全部可接受参数

> 源：`web/yisim.bundle.js` 第 43958 行起的 `simulate` + `buildPlayers` + 各 `normalize*`。

### 3.1 位置参数 `slots`（第 1 个参数）

摆牌数组 `[slot|null, ...]`，长度被截/补到 `deckSlots`。slot 字段：

| 字段 | 类型 | 说明 |
|------|------|------|
| `name` | string | 卡名（中文，内部模糊匹配成卡 id） |
| `level` | number | 等级 |
| `phase` | number? | 梦卡变体（1..5），非梦卡可省 |
| `isDream` | bool? | 是否梦卡 |

### 3.2 `options`

| 参数 | 类型 / 取值 | 默认 | 处理函数 | 说明 |
|------|-------------|------|----------|------|
| `rollMode` | `"average"` \| `"high"` \| `"low"` | `average`（→DEFAULT_ROLL_MODE） | `normalizeRollMode` | 骰点策略 |
| `deckSlots` | int，截到 `0..8` | `8` | `normalizeDeckSlots` | 牌位数 |
| `maxTurns` | int `1..64` | `64` | inline | 模拟回合上限 |
| `playerState` | object，见 3.3 | 见 3.3 | `normalizePlayerState` | 我方状态 |
| `talents` | talent 对象数组 | `[]` | `normalizeTalents` | 我方天赋（仅 `detected:true` 生效） |
| `mode` | `"matchup"` 或其它 | solo | inline | 等于 `"matchup"` 才启用对手相关参数 |
| `opponentSlots` | slot 数组 | `null` | inline | 仅 matchup；对手摆牌 |
| `opponentState` | object（同 playerState 形状） | 默认值 | `normalizePlayerState` | 仅 matchup |
| `opponentTalents` | talent 数组 | `[]` | `normalizeTalents` | 仅 matchup |
| `turnOrder` | `"me-first"` \| `"opp-first"` \| `"tied"` | `"me-first"` | inline | 先手顺序；`tied` 跑双向取较好 |
| `lastStandSecond` | bool | `false` | inline | 背水/后手最后一击规则开关 |
| `plantStacks` | `{字段名: number>0}` | `{}` | `sanitizePlantStacks` | 灵植成长层数，并入 player 初始 `*_stacks` |
| `playerSwordplayTalentCards` | number[]（5 位 base id） | `[]` | inline | 悟剑天赋选的卡 |
| `opponentSwordplayTalentCards` | number[] | `[]` | inline | 对手悟剑天赋卡 |

### 3.3 `playerState` / `opponentState` 字段（`normalizePlayerState`）

| 字段 | 类型 | 缺省回退 |
|------|------|----------|
| `hp` | number | `110` |
| `maxHp` | number | `null`（回退用 hp） |
| `physique` | number | `0` |
| `maxPhysique` | number | `0` |
| `cultivation` | number | `100` |
| `character` | string | `null`（由 `guess_character` 推断） |

> `max_hp` 最终 = `max(maxHp, hp) + physique`。

### 3.4 talent 字段（`normalizeTalents`，只保留 `detected:true` 且有 `name`）

| 字段 | 说明 |
|------|------|
| `detected` | 必须 `true` 才纳入 |
| `position` | 序位（用于解析 runtimeKey 里的 `{n}` 占位） |
| `phase` | 拾取顺序（1-based），回退到 position |
| `name` | 天赋名 |
| `simulationKind` | 默认 `"non-combat-or-unsupported"` |
| `runtimeKey` | 运行时键 |
| `grantedCardBaseIds` | number[] |
| `stackOverride` | 可选，按回合缩放的层数覆盖（如铸剑师 = round-1） |

---

## 4. HUD 已传 vs yisim 支持的差异

| yisim 参数 | HUD 是否传 | 说明 |
|------------|-----------|------|
| slots / board | ✅ | |
| deckSlots | ✅ | |
| talents | ✅ | me.fates |
| playerState（hp/physique/cultivation 等） | ✅ | 但 **不传 `character`**，靠 `guess_character` 推断 |
| plantStacks | ✅ | |
| mode / opponentSlots / opponentState / opponentTalents | ✅ | matchup 开启且对手有牌时 |
| maxTurns | ⚠️ 间接 | 桥写死 64，HUD 不可调 |
| rollMode | ❌ | HUD obj 未设 → 桥回退 `average`，无法选 high/low |
| turnOrder | ❌ | 用默认 `me-first` |
| lastStandSecond | ❌ | 用默认 `false` |
| playerSwordplayTalentCards / opponentSwordplayTalentCards | ❌ | **悟剑天赋选卡未接线**，目前恒为空 |

### 可改进项
- **悟剑天赋卡**（`playerSwordplayTalentCards`）当前完全没传，带悟剑流派时伤害会偏低。
- **rollMode** 在 HUD 侧固定 average；如想给「保守/激进」估算，可在 obj 里透出该字段。
- **turnOrder / lastStandSecond** 未暴露，若实战先后手影响结果可考虑接入。
