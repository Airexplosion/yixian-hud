# R30/R31/R32/R33/R34 — 2026-05 patch new-card status

Of the 48 new base cards added in the 2026-05 patch, **46 are now wired into
yisim**. Only 2 remain.

## ✓ WIRED (45 cards)

### R30 batch 1 (4 cards — simple stat-add patterns)
灵羽, 极•暗鸦灵剑, 望星诀, 极•两仪阵

### R30 batch 2 (11 cards — direct state-read math)
御风飞闪, 气旋掌, 灵枢剑阵, 极•迎风掌, 锻灵指, 星弈•长, 星弈•劫争, 灵蛇绕柱, 丹雀灵剑, 金刚捣碓, 凌空飞扫

### R32 (19 cards — new engine hooks + counters)
剑影结界, 弯弓射虎, 折枝点穴, 犀牛望月, 飞豹灵剑, 水灵•乘风浪, 玄灵愈体, 伤魂咒阵, 极•云剑柔心, 极•水灵阵, 极•崩天步, 御灵心法, 极•静气心法, 百鸟曳影诀, 闪转腾挪, 冯虚御风, 醉拳架势, 镇印心法, 万魂破军

**Engine in R32**: 13 new state vars, qi-gain/qi-loss/agility-gain/flaw-loss/element-activate/cloud_sword-played/water_spirit-played/on-atk hooks, `is_crash_fist` override, hp_cost counter.

### R33 (11 cards — using reference-card patterns + hp_cost hooks)
云剑•裂空 (双倍 bonus, ref 一心一剑), 迅影飞剑 (atk that doesn't trigger sword_intent, ref 金灵·飞梭), 五行灵击 (per-element scaling, ref 混元碎击), 云剑•追风 (counts-as-cloud_sword, ref 幻·云剑探云), 土灵•遁地 / 木灵•春风拂 / 火灵•焚脉诀 / 极•木灵巡林 / 混元化灵 (`[X灵]:` conditionals, ref 火灵·瞬燃), 崩拳•碎骨 (hp_cost damage carry), 血影遁术 (next hp_cost → agility)

**Engine in R33**: 2 new state vars (`crash_fist_shattered_bone_carry_stacks`, `blood_shadow_escape_stacks`) + 2 hooks in the hp_cost handler.

### R34 (1 card)

金灵•回锋刃 — manually captures `blade_forging_sharpness_stacks` per atk in card_actions (not via engine hook). On each atk: consume all sharpness for +3 atk/stack damage boost, then if `if_metal_spirit()` refund `ceil(N% × consumed)`. L1 / L2 / L3 use 50% / 75% / 100% refund.

---

## ✗ SKIPPED (2 cards)

### 星弈•治孤 — placement card

`[灵气]+anima / [星位]：施加N层[虚弱]和M层[破绽] / [开局]：[相邻]格[成为星位]，若为空格则放入"星弈•飞"`

IDs: 389 / 10389 / 20389

Why skipped: the `[开局]：[相邻]格[成为星位]，若为空格则放入"星弈•飞"` clause requires:
1. An `[开局]:` opening trigger (yisim has the swogi `opening` flag).
2. Marking adjacent slots as `star_point` (yisim has `become_star_point(N)` but it operates on consecutive slots from the current position, not arbitrary "adjacent" positions).
3. Placing the specific card `星弈•飞` into empty adjacent slots (similar to `applySolitaryVoidTransform`'s prefab insertion in `yisim_entry.js`).

**To resume**: extend `applySolitaryVoidTransform` to a generic helper that takes a card-id and adjacency rule, then use it from this card's `opening` trigger.

### 五行忘忧梦 — call another card

`生命及上限+N / 使用五行玉瓶中第一格牌的效果`

IDs: 390 / 10390 / 20390

Why skipped: user instructed "(temperary dont code this one)". Requires runtime dispatch of another card's actions, which yisim doesn't currently support.

---

## Total

| Status | Count |
|---|---|
| Wired | **46** |
| Skipped | 2 |
| Total | 48 |

All 46 wired cards × 3 phases = **138 simulate-clean entries** in the bundle. Engine changes from R30→R34: 18 new state vars, 12 new hook insertions, 1 method override.
