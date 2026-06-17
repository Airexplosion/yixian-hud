# 梦 dream-card audit report (v2: reads card_actions.js)

- Game-side dream cards: **103**
- yisim base dream IDs (names.json): **80**
- Cards with JS overrides loaded: **400** (includes non-dream cards)
- Missing from yisim entirely: **23**
- Likely buggy / mismatched: **8**
- Probably fine: **72**


---

## Missing from yisim entirely

- **梦·不动金刚阵** (1 phases) — sample: `'生命及上限+{otherParams[0]}\\n自身下回合[无法行动]，直至下回合结束前自身生命及上限的损失变为1('`
- **梦·九煞破灵曲** (1 phases) — sample: `'双方减{otherParams[1]}[灵气]\\n[被动]：双方各自首个回合的加[灵气]效果减半('`
- **梦·冰封雪莲** (2 phases) — sample: `'[防]+{def}\\n获得{otherParams[0]}层[护体]('`
- **梦·厄劫缠身** (2 phases) — sample: `'施加{otherParams[0]}层[内伤]\\n[开局]：对方同格牌[降级]，若无法[降级]则令对方下次使用同格牌时改为[跳过]('`
- **梦·回响阵纹** (2 phases) — sample: `'重复手牌中的一张[消耗]牌或[持续]牌的效果('`
- **梦·大还丹** (2 phases) — sample: `'生命及上限+{otherParams[1]}\\n[持续]：自身回合开始时，若生命上限/生命小于对方则加{otherParams[0]}生命上限/{otherParams[0]}生命('`
- **梦·天命重现** (1 phases) — sample: `'自身减{otherParams[0]}生命\\n对方已用过牌则[再次行动]\\n[先机]：令对方[跳至]上1张牌('`
- **梦·天音困仙曲** (1 phases) — sample: `'自身减{otherParams[1]}生命\\n[被动]：阻止双方各自前[{otherParams[0]}]个回合的[再次行动]的效果('`
- **梦·天马行空** (1 phases) — sample: `'随机使用{otherParams[0]}张化神期梦境牌0'`
- **梦·妙笔生花** (2 phases) — sample: `'[炼化]：[修为]-{otherParams[0]}，随机获得{otherParams[0]}张其他门派的元婴期牌('`
- **梦·寒冰咒** (2 phases) — sample: `'重复{otherParams[1]}次：对方减{otherParams[0]}[生命]\\n令对方下回合无法加[防]和生命('`
- **梦·弱体符** (1 phases) — sample: `'施加{otherParams[0]}层[虚弱]\\n[再次行动]\\n[消耗]('`
- **梦·清心咒** (1 phases) — sample: `'[灵气]+{anima}\\n自身所有[负面状态]减{otherParams[0]}层，获得{otherParams[1]}层[辟邪]('`
- **梦·狂舞曲** (1 phases) — sample: `'双方各自下{otherParams[0]}次使用牌后[再次行动]('`
- **梦·画龙点睛** (1 phases) — sample: `'[炼化]：升级[卡组]中的1张副职牌（不限等级）('`
- **梦·神来之笔** (2 phases) — sample: `'[防]+{def}\\n随机使用一张元婴期及以上的灵宠、法宝或秘术牌的效果('`
- **梦·空间灵田** (1 phases) — sample: `'若在后2格，首次使用改为[跳过]此牌\\n[被动]：战斗结束时减1修为获得卡组中1张1级[常规牌]的复制('`
- **梦·缚仙古藤** (2 phases) — sample: `'施加{otherParams[0]}层[外伤]\\n下{otherParams[1]}次攻击[碎防]\\n[先机]：施加{otherParams[2]}层[困缚]('`
- **梦·自在随心** (1 phases) — sample: `'[炼化]：织梦珊瑚+10'`
- **梦·转弦合调** (2 phases) — sample: `'[灵气]+{anima}\\n自身下次[再次行动]时不会被其他效果阻止\\n已用过其他牌则[再次行动]('`
- **梦·锐金符** (2 phases) — sample: `'造成{otherParams[0]}[伤害]（若对方生命≤{otherParams[1]}，此牌的效果改为令对方生命变为-100）('`
- **梦·飞云丹** (2 phases) — sample: `'[灵气]+{anima}\\n[持续]：自身回合开始时，若对方有[防]，则自身下{otherParams[0]}次攻击[无视防御]，否则加{otherParams[0]}[灵气]('`
- **梦·飞枭灵芝** (1 phases) — sample: `'[炼化]：下场战斗开始时自身[速度]+{otherParams[0]}，若自身为后手，则获得[死战之志]效果('`


## Likely buggy / mismatched (against card_actions.js)


### 梦·云剑柔心  (D11161 family)
- **phase 1** (D11161, card_actions.js)
  - game: `[防]+{def}\n[持续]：每回合开始时加{otherParams[0]}[防]`
  - yisim: `game.increase_idx_def(0, 4);     game.continuous();     game.increase_idx_x_by_c(0, "dream_cloud_sword_softheart_gain_def", 1);`
- **phase 2** (D11162, card_actions.js)
  - game: `[防]+{def}\n[持续]：每回合开始时加{otherParams[0]}[防]`
  - yisim: `game.increase_idx_def(0, 8);     game.continuous();     game.increase_idx_x_by_c(0, "dream_cloud_sword_softheart_gain_def", 1);`
- **phase 3** (D11163, card_actions.js)
  - game: `[防]+{def}\n[持续]：每回合开始时加{otherParams[0]}[防]`
  - yisim: `game.increase_idx_def(0, 4);     game.continuous();     game.increase_idx_x_by_c(0, "dream_cloud_sword_softheart_gain_def", 2);`
- **phase 4** (D11164, card_actions.js)
  - game: `[防]+{def}\n[持续]：每回合开始时加{otherParams[0]}[防]，每次使用剑阵时加1[云海]`
  - yisim: `game.increase_idx_def(0, 4);     game.continuous();     game.increase_idx_x_by_c(0, "dream_cloud_sword_softheart_gain_def", 3);     game.increase_idx_x_by_c(0, "dream_cloud_sword_softheart_sword_formation_gives_cloud_sea", 1);`
- **phase 5** (D11165, card_actions.js)
  - game: `[防]+{def}\n[水月]{otherParams[1]}\n[持续]：每回合开始时加{otherParams[0]}[防]，每次使用剑阵时加1[云海]`
  - yisim: `game.increase_idx_def(0, 4);     game.continuous();     game.increase_idx_x_by_c(0, "dream_cloud_sword_softheart_gain_def", 5);     game.increase_idx_x_by_c(0, "dream_cloud_sword_softheart_sword_formation_gives_cloud_sea", 1);`

  Flags:
  - phase5 (D11165, card_actions.js): text has `[水月]` but body lacks any of ['moon_water']

### 梦·云剑汇灵  (D11181 family)
- **phase 1** (D11181, card_actions.js)
  - game: `{attack}攻\n[灵气]>0则追加一次攻击`
  - yisim: `const hits = 1 + (game.players[0].qi > 0 ? 1 : 0);     for (let i = 0; i < hits; i++) {         game.atk(4);     }`
- **phase 2** (D11182, card_actions.js)
  - game: `{attack}攻\n[灵气]>0则追加一次攻击`
  - yisim: `const hits = 1 + (game.players[0].qi > 0 ? 1 : 0);     for (let i = 0; i < hits; i++) {         game.atk(5);     }`
- **phase 3** (D11183, card_actions.js)
  - game: `{attack}攻\n[灵气]>0则追加一次攻击`
  - yisim: `const hits = 1 + (game.players[0].qi > 0 ? 1 : 0);     for (let i = 0; i < hits; i++) {         game.atk(6);     }`
- **phase 4** (D11184, card_actions.js)
  - game: `{attack}攻\n每有{otherParams[0]}点[灵气]就追加一次攻击\n[连云]：改为每有{otherParams[2]}点[灵气]就追加一次攻击\n[开局]：[云海]+{otherParams[1]}`
  - yisim: `const me = game.players[0];     const hits = 1 + Math.floor(me.qi * 0.5);     for (let i = 0; i < hits; i++) {         game.atk(3);     }`
- **phase 5** (D11185, card_actions.js)
  - game: `{attack}攻\n每有{otherParams[0]}点[灵气]就追加一次攻击\n[连云]：改为每有{otherParams[2]}点[灵气]就追加一次攻击\n[开局]：[云海]+{otherParams[1]}`
  - yisim: `const me = game.players[0];     const hits = 1 + Math.floor(me.qi * 0.5);     for (let i = 0; i < hits; i++) {         game.atk(4);     }`

  Flags:
  - phase4 (D11184, card_actions.js): text has `[云海]` but body lacks any of ['cloud_sea']
  - phase5 (D11185, card_actions.js): text has `[云海]` but body lacks any of ['cloud_sea']

### 梦·崩拳封  (D14031 family)
- **phase 1** (D14031, card_actions.js)
  - game: `[防]+{def}\n下张崩拳多{otherParams[0]}[攻]`
  - yisim: `game.increase_idx_def(0, 12);     game.add_c_of_x(2, "later_crash_fist_poke_stacks");`
- **phase 2** (D14032, card_actions.js)
  - game: `[防]+{def}\n下张崩拳多{otherParams[0]}[攻]`
  - yisim: `game.increase_idx_def(0, 14);     game.add_c_of_x(3, "later_crash_fist_poke_stacks");`
- **phase 3** (D14033, card_actions.js)
  - game: `[防]+{def}\n每加过{otherParams[0]}[防]，下张崩拳就多1[攻]`
  - yisim: `game.increase_idx_def(0, 18);     const atk = Math.floor(game.players[0].total_def_gained * 0.14285715);     game.add_c_of_x(atk, "later_crash_fist_poke_stacks");`
- **phase 4** (D14034, card_actions.js)
  - game: `[防]+{def}\n每加过{otherParams[0]}[防]，下张崩拳就多1[攻]`
  - yisim: `game.increase_idx_def(0, 18);     const atk = Math.floor(game.players[0].total_def_gained * 0.16666667);     game.add_c_of_x(atk, "later_crash_fist_poke_stacks");`
- **phase 5** (D14035, card_actions.js)
  - game: `[防]+{def}\n每加过{otherParams[0]}[防]，下张崩拳就多1[攻]`
  - yisim: `game.increase_idx_def(0, 18);     const atk = Math.floor(game.players[0].total_def_gained * 0.20000001);     game.add_c_of_x(atk, "later_crash_fist_poke_stacks");`

  Flags:
  - phase1 (D14031, card_actions.js): text has `[攻]` but body lacks any of ['atk(', 'atk,']
  - phase2 (D14032, card_actions.js): text has `[攻]` but body lacks any of ['atk(', 'atk,']

### 梦·崩拳连崩  (D14141 family)
- **phase 1** (D14141, card_actions.js)
  - game: `{attack}攻×{attackCount}\n使用下张崩拳后追加{otherParams[0]}攻×2`
  - yisim: `game.atk(3);     game.atk(3);     game.players[0].dream_crash_fist_continue_bonus_atk += 2;`
- **phase 2** (D14142, card_actions.js)
  - game: `{attack}攻×{attackCount}\n使用下张崩拳后追加{otherParams[0]}攻×2`
  - yisim: `game.atk(4);     game.atk(4);     game.players[0].dream_crash_fist_continue_bonus_atk += 2;`
- **phase 3** (D14143, card_actions.js)
  - game: `{attack}攻×{attackCount}\n使用下张崩拳后追加{otherParams[0]}攻×2`
  - yisim: `game.atk(5);     game.atk(5);     game.players[0].dream_crash_fist_continue_bonus_atk += 2;`
- **phase 4** (D14144, card_actions.js)
  - game: `{attack}攻×{attackCount}\n此牌触发的崩拳效果保留至下一张崩拳`
  - yisim: `game.atk(6);     game.atk(6);     game.players[0].dream_crash_fist_continue_bonus_atk += 2;`
- **phase 5** (D14145, card_actions.js)
  - game: `{attack}攻×{attackCount}\n此牌触发的崩拳效果保留至下一张崩拳`
  - yisim: `game.atk(9);     game.atk(9);     game.players[0].dream_crash_fist_continue_bonus_atk += 2;`
- **phase 6** (D14146, MISSING)
  - game: `{attack}攻×{attackCount}\n使用下张崩拳后追加2攻×{otherParams[0]}`
  - yisim: ``
- **phase 7** (D14147, MISSING)
  - game: `{attack}攻×{attackCount}\n使用下张崩拳后追加2攻×{otherParams[0]}`
  - yisim: ``
- **phase 8** (D14148, MISSING)
  - game: `{attack}攻×{attackCount}\n使用下张崩拳后追加2攻×{otherParams[0]}`
  - yisim: ``
- **phase 9** (D14149, MISSING)
  - game: `{attack}攻×{attackCount}\n使用下张崩拳后追加2攻×{otherParams[0]}（手牌每留1张崩拳多追加1次，最多{otherParams[1]}次）`
  - yisim: ``
- **phase 10** (D141410, MISSING)
  - game: `{attack}攻×{attackCount}\n使用下张崩拳后追加2攻×{otherParams[0]}（手牌每留1张崩拳多追加1次，最多{otherParams[1]}次）`
  - yisim: ``

  Flags:
  - phase6 (D14146): NO entry in card_actions.js or swogi.json
  - phase7 (D14147): NO entry in card_actions.js or swogi.json
  - phase8 (D14148): NO entry in card_actions.js or swogi.json
  - phase9 (D14149): NO entry in card_actions.js or swogi.json
  - phase10 (D141410): NO entry in card_actions.js or swogi.json

### 梦·星罗棋布  (D12151 family)
- **phase 1** (D12151, card_actions.js)
  - game: `[持续]{otherParams[0]}次：使用[非星位]上的牌后加1[灵气]和1[星力]`
  - yisim: `game.continuous();     game.players[0].dream_dotted_around_countdown += 1;`
- **phase 2** (D12152, card_actions.js)
  - game: `[灵气]+{anima}\n[持续]{otherParams[0]}次：使用[非星位]上的牌后加1[灵气]和1[星力]`
  - yisim: `game.increase_idx_qi(0, 1);     game.continuous();     game.players[0].dream_dotted_around_countdown += 1;`
- **phase 3** (D12153, card_actions.js)
  - game: `[持续]{otherParams[0]}次：使用[非星位]上的牌后加1[灵气]和1[星力]`
  - yisim: `game.continuous();     game.players[0].dream_dotted_around_countdown += 2;`
- **phase 4** (D12154, card_actions.js)
  - game: `[持续]{otherParams[0]}次：使用[非星位]上的牌后加1[灵气]和1[星力]`
  - yisim: `game.continuous();     game.players[0].dream_dotted_around_countdown += 3;`
- **phase 5** (D12155, card_actions.js)
  - game: `[持续]：每回合首次使用[非星位]上的牌后加1[灵气]和1[星力]`
  - yisim: `game.continuous();     game.players[0].dream_dotted_around_per_turn += 1;`

  Flags:
  - phase1 (D12151, card_actions.js): text has `[灵气]` but body lacks any of ['qi']
  - phase3 (D12153, card_actions.js): text has `[灵气]` but body lacks any of ['qi']
  - phase4 (D12154, card_actions.js): text has `[灵气]` but body lacks any of ['qi']
  - phase5 (D12155, card_actions.js): text has `[灵气]` but body lacks any of ['qi']

### 梦·枯木逢春  (D12181 family)
- **phase 1** (D12181, card_actions.js)
  - game: `若用过[梦`
  - yisim: `const me = game.players[0];     me.dream_revitalized_doublings = Math.min(1, me.dream_revitalized_played_count);     game.atk(5);     me.dream_revitalized_played_count += 1;`
- **phase 2** (D12182, card_actions.js)
  - game: `，此牌攻翻倍\n{attack}攻`
  - yisim: `const me = game.players[0];     me.dream_revitalized_doublings = Math.min(1, me.dream_revitalized_played_count);     game.atk(6);     me.dream_revitalized_played_count += 1;`
- **phase 3** (D12183, card_actions.js)
  - game: `若用过[梦`
  - yisim: `const me = game.players[0];     me.dream_revitalized_doublings = Math.min(1, me.dream_revitalized_played_count);     game.atk(8);     me.dream_revitalized_played_count += 1;`
- **phase 4** (D12184, card_actions.js)
  - game: `，此牌攻翻倍\n{attack}攻`
  - yisim: `const me = game.players[0];     me.dream_revitalized_doublings = Math.min(1, me.dream_revitalized_played_count);     game.atk(10);     me.dream_revitalized_played_count += 1;`
- **phase 5** (D12185, card_actions.js)
  - game: `若用过[梦`
  - yisim: `const me = game.players[0];     me.dream_revitalized_doublings = me.dream_revitalized_played_count;     game.atk(12);     me.dream_revitalized_played_count += 1;`
- **phase 6** (D12186, MISSING)
  - game: `，此牌攻翻倍\n{attack}攻`
  - yisim: ``
- **phase 7** (D12187, MISSING)
  - game: `若用过[梦`
  - yisim: ``
- **phase 8** (D12188, MISSING)
  - game: `，此牌攻翻倍\n{attack}攻`
  - yisim: ``
- **phase 9** (D12189, MISSING)
  - game: `每用过一次[梦`
  - yisim: ``
- **phase 10** (D121810, MISSING)
  - game: `，攻就翻倍一次\n{attack}攻`
  - yisim: ``

  Flags:
  - phase6 (D12186): NO entry in card_actions.js or swogi.json
  - phase7 (D12187): NO entry in card_actions.js or swogi.json
  - phase8 (D12188): NO entry in card_actions.js or swogi.json
  - phase9 (D12189): NO entry in card_actions.js or swogi.json
  - phase10 (D121810): NO entry in card_actions.js or swogi.json

### 梦·水灵泉涌  (D13061 family)
- **phase 1** (D13061, card_actions.js)
  - game: `本场战斗每[击伤]过对方{otherParams[0]}生命就获得1层[水势]\n[开局]：[灵气]+{otherParams[1]}`
  - yisim: `const me = game.players[0];     const add = Math.floor(me.total_amount_injured * 0.125);     game.add_c_of_x(add, "force_of_water");`
- **phase 2** (D13062, card_actions.js)
  - game: `本场战斗每[击伤]过对方{otherParams[0]}生命就获得1层[水势]\n[开局]：[灵气]+{otherParams[1]}`
  - yisim: `const me = game.players[0];     const add = Math.floor(me.total_amount_injured * 0.14285715);     game.add_c_of_x(add, "force_of_water");`
- **phase 3** (D13063, card_actions.js)
  - game: `本场战斗每[击伤]过对方{otherParams[0]}生命就获得1层[水势]\n[开局]：[灵气]+{otherParams[1]}`
  - yisim: `const me = game.players[0];     const add = Math.floor(me.total_amount_injured * 0.16666667);     game.add_c_of_x(add, "force_of_water");`
- **phase 4** (D13064, card_actions.js)
  - game: `本场战斗每[击伤]过对方{otherParams[0]}生命就获得1层[水势]\n[开局]：[灵气]+{otherParams[1]}`
  - yisim: `const me = game.players[0];     const add = Math.floor(me.total_amount_injured * 0.16666667);     game.add_c_of_x(add, "force_of_water");`
- **phase 5** (D13065, card_actions.js)
  - game: `[灵气]+{anima}\n本场战斗每[击伤]过对方{otherParams[0]}生命就获得1层[水势]\n[开局]：[灵气]+{otherParams[1]}`
  - yisim: `game.increase_idx_qi(0, 2);     const me = game.players[0];     const add = Math.floor(me.total_amount_injured * 0.20000001);     game.add_c_of_x(add, "force_of_water");`

  Flags:
  - phase1 (D13061, card_actions.js): text has `[灵气]` but body lacks any of ['qi']
  - phase2 (D13062, card_actions.js): text has `[灵气]` but body lacks any of ['qi']
  - phase3 (D13063, card_actions.js): text has `[灵气]` but body lacks any of ['qi']
  - phase4 (D13064, card_actions.js): text has `[灵气]` but body lacks any of ['qi']

### 梦·火灵聚炎  (D13161 family)
- **phase 1** (D13161, card_actions.js)
  - game: `[灵气]+{anima}\n减对方{otherParams[0]}生命及上限\n[先机]：双方使用下张牌时将其[消耗]`
  - yisim: `const me = game.players[0];     game.increase_idx_qi(0, 1);     game.reduce_enemy_hp(5);     game.reduce_enemy_max_hp(5);     if (!me.can_post_action[me.currently_playing_card_idx]) {         game.increase_idx_x_by_c(0, "consume_next_card_played_stacks", 1);         game.increase…`
- **phase 2** (D13162, card_actions.js)
  - game: `[灵气]+{anima}\n减对方{otherParams[0]}生命及上限\n[先机]：双方使用下张牌时将其[消耗]`
  - yisim: `const me = game.players[0];     game.increase_idx_qi(0, 1);     game.reduce_enemy_hp(7);     game.reduce_enemy_max_hp(7);     if (!me.can_post_action[me.currently_playing_card_idx]) {         game.increase_idx_x_by_c(0, "consume_next_card_played_stacks", 1);         game.increase…`
- **phase 3** (D13163, card_actions.js)
  - game: `[灵气]+{anima}\n减对方{otherParams[0]}生命及上限（每点[灵气]多{otherParams[1]}）\n[先机]：双方使用下张牌时将其[消耗]`
  - yisim: `const me = game.players[0];     game.increase_idx_qi(0, 3);     const dmg = 2 + me.qi;     game.reduce_enemy_hp(dmg);     game.reduce_enemy_max_hp(dmg);     if (!me.can_post_action[me.currently_playing_card_idx]) {         game.increase_idx_x_by_c(0, "consume_next_card_played_sta…`
- **phase 4** (D13164, card_actions.js)
  - game: `[灵气]+{anima}\n减对方{otherParams[0]}生命及上限（每点[灵气]多{otherParams[1]}）\n[先机]：双方使用下张牌时将其[消耗]`
  - yisim: `const me = game.players[0];     game.increase_idx_qi(0, 3);     const dmg = 2 + 2 * me.qi;     game.reduce_enemy_hp(dmg);     game.reduce_enemy_max_hp(dmg);     if (!me.can_post_action[me.currently_playing_card_idx]) {         game.increase_idx_x_by_c(0, "consume_next_card_played…`
- **phase 5** (D13165, card_actions.js)
  - game: `[灵气]+{anima}\n减对方{otherParams[0]}生命及上限（每点[灵气]多{otherParams[1]}）\n[先机]：双方使用下张牌时将其[消耗]`
  - yisim: `const me = game.players[0];     game.increase_idx_qi(0, 4);     const dmg = 2 + 2 * me.qi;     game.reduce_enemy_hp(dmg);     game.reduce_enemy_max_hp(dmg);     if (!me.can_post_action[me.currently_playing_card_idx]) {         game.increase_idx_x_by_c(0, "consume_next_card_played…`

  Flags:
  - phase1 (D13161, card_actions.js): text has `[消耗]` but body lacks any of ['consumption', 'exhaust']
  - phase2 (D13162, card_actions.js): text has `[消耗]` but body lacks any of ['consumption', 'exhaust']
  - phase3 (D13163, card_actions.js): text has `[消耗]` but body lacks any of ['consumption', 'exhaust']
  - phase4 (D13164, card_actions.js): text has `[消耗]` but body lacks any of ['consumption', 'exhaust']
  - phase5 (D13165, card_actions.js): text has `[消耗]` but body lacks any of ['consumption', 'exhaust']


## Probably fine

- 梦·万法归灵剑 (D11081)
- 梦·两仪阵 (D12041)
- 梦·乾卦 (D12171)
- 梦·云剑厚土 (D11111)
- 梦·云剑极意 (D11031)
- 梦·云剑点星 (D11021)
- 梦·云舞诀 (D11051)
- 梦·五行刺 (D13041)
- 梦·五行天髓诀 (D13141)
- 梦·修罗吼 (D14021)
- 梦·冥影身法 (D14091)
- 梦·冲霄破浪 (D14051)
- 梦·凝意诀 (D11171)
- 梦·劈山掌 (D14111)
- 梦·反身剑 (D11121)
- 梦·反震心法 (D12091)
- 梦·土灵断崖 (D13181)
- 梦·土灵绝壁 (D13131)
- 梦·地煞剑 (D11151)
- 梦·威震四方 (D14161)
- 梦·岿然不动 (D14201)
- 梦·崩天步 (D14121)
- 梦·崩拳弹 (D14081)
- 梦·崩拳突 (D14061)
- 梦·巨鹏灵剑 (D11141)
- 梦·引气剑 (D11191)
- 梦·御空剑阵 (D11131)
- 梦·御雷卦诀 (D12201)
- 梦·斗转星移 (D12101)
- 梦·星弈挡 (D12011)
- 梦·星弈点 (D12191)
- 梦·星轨推衍 (D12021)
- 梦·朝气蓬勃 (D14101)
- 梦·木灵柳纷飞 (D13071)
- 梦·木灵芽 (D13151)
- 梦·木灵阵 (D13081)
- 梦·杯弓蛇影 (D12131)
- 梦·气疗术 (D12141)
- 梦·气若悬河 (D14171)
- 梦·水灵汹涌 (D13191)
- 梦·水灵波澜 (D13031)
- 梦·浑天印 (D13021)
- 梦·海底捞月 (D12081)
- 梦·混元无极阵 (D13051)
- 梦·混元碎击 (D13201)
- 梦·火灵灼心 (D13091)
- 梦·火灵瞬燃 (D13101)
- 梦·火灵阵 (D13171)
- 梦·灵气灌注 (D11011)
- 梦·灵犀剑阵 (D11101)
- 梦·灵玄迷踪步 (D14011)
- 梦·狂剑一式 (D11061)
- 梦·狂剑二式 (D11201)
- 梦·狂剑零式 (D11091)
- 梦·白蛇吐信 (D12161)
- 梦·百鸟灵剑诀 (D11071)
- 梦·磅礴之势 (D14181)
- 梦·离卦 (D12111)
- 梦·荷重前行 (D14151)
- 梦·落花有意 (D12061)
- 梦·落雷术 (D12051)
- 梦·蜻蜓点水 (D12121)
- 梦·轰雷掣电 (D12031)
- 梦·迎风掌 (D14131)
- 梦·金灵铁骨 (D13111)
- 梦·金灵锋芒 (D13121)
- 梦·金灵阵 (D13011)
- 梦·锻拳 (D14191)
- 梦·锻神开海 (D14041)
- 梦·锻筋 (D14071)
- 梦·飞牙剑 (D11041)
- 梦·黄雀在后 (D12071)
