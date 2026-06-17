# 弈仙牌 game-api 参考

> 由 `native_hud/api/gen_docs.py` 从声明式注册表 `registry.py` 生成,勿手改。

## 连接

```python
from native_hud.api import connect
api = connect()            # spawn 游戏并注入;connect(attach=True) 接已运行的游戏
api.battle.skip()
api.state.round()          # -> {'round': 7}
```

## Battle 战斗

### `api.battle.skip()`

- **说明:** 跳过当前战斗动画,正常回到摆牌(发牌+加换牌次数)
- **C# 面板:** `YiXianBot.BattleApi.Skip`
- **返回:** 状态串 `ok:...`/`EX:...`
- **场景依赖:** 需在 **斗法阶段** 调用

### `api.battle.force_break()`

- **说明:** 强制打断所有执行中的战斗执行器(不切场景)
- **C# 面板:** `YiXianBot.BattleApi.ForceBreak`
- **返回:** 状态串 `ok:...`/`EX:...`
- **场景依赖:** 需在 **斗法阶段** 调用

### `api.battle.is_battling()`

- **说明:** 当前是否有战斗动画在播放(ok:1/ok:0)
- **C# 面板:** `YiXianBot.BattleApi.IsBattling`
- **返回:** 状态串 `ok:...`/`EX:...`

## Scene 场景

### `api.scene.change(scene_type)`

- **说明:** 切换场景:0=修炼阶段(摆牌) 1=斗法阶段(战斗)
- **C# 面板:** `YiXianBot.SceneApi.Change`
- **返回:** 状态串 `ok:...`/`EX:...`

### `api.scene.current()`

- **说明:** 当前场景枚举 int(0/1)
- **C# 面板:** `YiXianBot.SceneApi.Current`
- **返回:** 状态串 `ok:...`/`EX:...`

## GameStatus 对局状态

### `api.game_status.req()`

- **说明:** 向服务器请求当前权威对局状态(补发牌/换牌次数)
- **C# 面板:** `YiXianBot.GameStatusApi.Req`
- **返回:** 状态串 `ok:...`/`EX:...`

## Network 网络

### `api.network.auto_select(ping_amount)`

- **说明:** 自动选择最优线路(=设置-网络-自动选择)
- **C# 面板:** `YiXianBot.NetworkApi.AutoSelect`
- **返回:** 状态串 `ok:...`/`EX:...`

### `api.network.analyze(ping_amount)`

- **说明:** 分析各线路延迟(不切),结果异步落库
- **C# 面板:** `YiXianBot.NetworkApi.Analyze`
- **返回:** 状态串 `ok:...`/`EX:...`

### `api.network.optimize()`

- **说明:** 优化网络(会重载到 Home 场景,有打断性)
- **C# 面板:** `YiXianBot.NetworkApi.Optimize`
- **返回:** 状态串 `ok:...`/`EX:...`

## State 只读状态

### `api.state.round()`

- **说明:** 当前对局轮次 {round}
- **C# 面板:** `YiXianBot.StateApi.Round`
- **返回:** JSON 对象

### `api.state.self()`

- **说明:** 自身上一轮快照 {life,maxHp,tiPo,level}
- **C# 面板:** `YiXianBot.StateApi.Self`
- **返回:** JSON 对象

## Placement 摆牌阶段

### `api.placement.board()`

- **说明:** 当前手牌布局 {hand:[{slot,id}]},slot 用于 move/swap/refine 寻址
- **C# 面板:** `YiXianBot.PlacementApi.Board`
- **返回:** JSON 对象
- **场景依赖:** 需在 **修炼阶段** 调用

### `api.placement.move(hand_idx, grid_idx)`

- **说明:** 摆牌:把手牌第 hand_idx 张摆到棋盘格子第 grid_idx 个
- **C# 面板:** `YiXianBot.PlacementApi.Move`
- **返回:** 状态串 `ok:...`/`EX:...`
- **场景依赖:** 需在 **修炼阶段** 调用

### `api.placement.swap(hand_idx)`

- **说明:** 换牌:换掉手牌第 hand_idx 张
- **C# 面板:** `YiXianBot.PlacementApi.Swap`
- **返回:** 状态串 `ok:...`/`EX:...`
- **场景依赖:** 需在 **修炼阶段** 调用

### `api.placement.refine(hand_idx)`

- **说明:** 炼化第 hand_idx 张手牌得修为
- **C# 面板:** `YiXianBot.PlacementApi.Refine`
- **返回:** 状态串 `ok:...`/`EX:...`
- **场景依赖:** 需在 **修炼阶段** 调用

### `api.placement.ready()`

- **说明:** 准备/确认结束本回合摆牌(ReadyLayer.PressReadyButton)
- **C# 面板:** `YiXianBot.PlacementApi.Ready`
- **返回:** 状态串 `ok:...`/`EX:...`
- **场景依赖:** 需在 **修炼阶段** 调用

### `api.placement.fate_select(index)`

- **说明:** 选天衍仙命:选第 index 个选项(需「选择天衍仙命」面板弹出时)
- **C# 面板:** `YiXianBot.PlacementApi.FateSelect`
- **返回:** 状态串 `ok:...`/`EX:...`

### `api.placement.daoyun_select(daoyun_id)`

- **说明:** 选道韵:选 daoyun_id(需道韵选择面板弹出时)
- **C# 面板:** `YiXianBot.PlacementApi.DaoyunSelect`
- **返回:** 状态串 `ok:...`/`EX:...`

### `api.placement.pact(kind, param)`

- **说明:** 通用弹窗选择 SimpleClientPact{kind,param}:仙命=26 天衍仙命=46 道韵=9 天命=5 失败再战=13 逃跑=0 rogue=11
- **C# 面板:** `YiXianBot.PlacementApi.Pact`
- **返回:** 状态串 `ok:...`/`EX:...`

### `api.placement.select_career(career, random, fzjx)`

- **说明:** 选(副)职业:career 1炼丹2符咒3琴4画5阵法6灵植7命理;fzjx=1副职业;random=1随机
- **C# 面板:** `YiXianBot.PlacementApi.SelectCareer`
- **返回:** 状态串 `ok:...`/`EX:...`

### `api.placement.fate_branch_select(index)`

- **说明:** 选择仙命:选第 index 个选项(0起;面板自动读真实 FateBranchType)
- **C# 面板:** `YiXianBot.PlacementApi.FateBranchSelect`
- **返回:** 状态串 `ok:...`/`EX:...`

### `api.placement.ui_select(index)`

- **说明:** 真·UI选择:选项弹窗里选第index个Toggle+点ConfirmButton(任何选项+确定弹窗通用;index<0只点确定)
- **C# 面板:** `YiXianBot.PlacementApi.UiSelect`
- **返回:** 状态串 `ok:...`/`EX:...`

### `api.placement.click_button(text)`

- **说明:** 按可见文字点任意按钮(真UI点击):再战/逃跑/随机/确定/职业名/奇遇选项等,子串匹配
- **C# 面板:** `YiXianBot.PlacementApi.ClickButton`
- **返回:** 状态串 `ok:...`/`EX:...`

### `api.placement.breakthrough()`

- **说明:** 突破:进入突破态(等效点突破按钮,美术字无文字);之后弹的天命/仙命用 ui_select 选
- **C# 面板:** `YiXianBot.PlacementApi.Breakthrough`
- **返回:** 状态串 `ok:...`/`EX:...`

