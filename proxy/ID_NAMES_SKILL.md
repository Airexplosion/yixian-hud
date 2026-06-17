# 弈仙牌 id↔名 映射 Skill

写 bot / 大脑时**用名字不用数字**。所有映射 + 查询模块都在本目录 (`proxy/`)。

## 调用 (推荐)

```python
from id_names import card_name, daoyun_name, xianming_name, tianyan_name, career_name, id_of
card_name(3)             # '云剑•崩雪'
xianming_name(30001)     # '锻体'        (突破后选的"仙命")
tianyan_name(9)          # '云巅雷劫'      (2轮后选的"天衍")
career_name(4)           # '画师'
id_of('card', '云剑•崩雪')  # '3'          反查: 写策略时按名字拿 id
```
`id_of(kind, 中文名)` 的 kind ∈ {card, daoyun, xianming, tianyan, career}。

## 四张映射表 (本目录 json)

| 表 | 文件 | 键 | 值 | 条数 | 对应游戏选择 |
|---|---|---|---|---|---|
| 卡牌 / 道韵 | `card_id_map.json` | cardId | 中文名 | 2915 | 摆牌的牌; 道韵也是 cardId |
| **仙命** | `fate_talent_map.json` | talentId | {name(英), nameCn, simulationKind, …} | 412 | `TalentSelectionPanel` (**突破后**) |
| **天衍** | `fate_id_map.json` | strategyId | 中文名 | 496 | `FateStrategyPanel` (**2轮后**, 标题"选择天衍仙命") |
| 副职业 | `career_id_map.json` | careerId(1-7) | {enum, nameCn} | 7 | `CareerSelectionPanel` |

> ⚠️ **代码命名与游戏 UI 相反**: 代码里的 `Talent`(TalentSelectionPanel) = 游戏的**仙命**;
> 代码里的 `FateStrategy`(FateStrategyPanel) = 游戏的**天衍**。`id_names.py` 已按游戏 UI 命名 (xianming=仙命, tianyan=天衍)。
> 仙命 id 有分层 (1 / 10001 / 20001 / 30001 同名"锻体", 不同档); 名字相同, 选择时用面板实际给的那个 id。

## 选择动作怎么用名字 (写 bot 时)

读面板选项 → bot 返回 `序号:id` → 用本表把 id 翻成名 (决策) → 按序号 select:
- 仙命: `Bot.ReadTalents()` → `talents=0:22|1:30188|2:30001|3:30016`; `xianming_name(30001)`='锻体'; `Bot.SelectTalentByIndex(i)`
- 天衍: `Bot.ReadFates()`  → `fates=0:..`; `tianyan_name(id)`; `Bot.SelectFateByIndex(i)`
- 道韵: `Bot.ReadDaoyuns()`→ `daoyuns=0:..(cardId)`; `daoyun_name(id)`; `Bot.SelectDaoyunByIndex(i)`
- 副职: `Bot.ReadCareers()`→ `careers=0:HuaShi(4)..`; `career_name(4)`='画师'; `Bot.SelectCareerByIndex(i)`

(选择动作的同域 bot 实现见 `_recon_hotfix/bot8`(Bot8) + memory `hotfix-dll-plaintext-decompiled`。)

## 名字从哪来 / 怎么再生

- 卡/仙命/天衍 map 是仓库原有 (card-counter 工具抓的)。
- 副职 `career_id_map.json` 由运行时 `TranslateUtil.GetCareerTranslate((Career)i)` 导出 (i=1..7, Career 枚举见 `Proto/Career.cs`)。
- 要补/校验任何名字: 游戏内配置在 `ConfigManager` (cardConfigDict / talentConfigs / fateStrategyConfigs),
  经同域 bot 反射读取后落 UTF-8 json (终端是 GBK, 必须写文件再读, 别直接 print 中文)。
