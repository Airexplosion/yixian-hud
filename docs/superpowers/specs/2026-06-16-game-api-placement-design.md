# 弈仙牌 game-api — placement 扩展设计

**分支:** `game-api`(承接 [2026-06-16-game-api-design.md] 的两层架构 + 注册表)

**目标:** 给 API 加 `placement`(摆牌阶段)命名空间:摆牌 / 换牌 / 炼化 三个操作 + 一个只读布局查询,演示并落实"加新 API = C# 加方法 + 注册表加一行"的可扩展性。

---

## 1. 机制(反编译已证)

摆牌/换牌/炼化在客户端都是发同一个服务器消息:
```
RelicOperationReq { RelicOperation operation; List<int> operationParams; }   // Proto IMessage
→ GameClientUtil.client.SendRoomMessageForILRAsync<RelicOperationResp>((IMessage)req)
```
`RelicOperation` 枚举(int 值):`Invalid=0, Vote=1, XiuWeiCunQu=2(摆牌), JingHuaRongLian=3(炼化), LockCard=4, SwitchCard=5(换牌), SealCard=6, ...`

`operationParams` 布局(反编译实证):
- 摆牌 XiuWeiCunQu:`[(int)sourcePosition, sourceIndex, 2, targetGridIndex]`
- 换牌 SwitchCard:`[(int)sourcePosition, sourceIndex, 3, targetGridIndex]`
- 炼化 JingHuaRongLian:熔炼两张卡,params 标识两张卡(精确布局实现时按反编译 218400 区定;形如 `[pos1, idx1, pos2, idx2]`)

**纯 int 参数,服务器权威校验** —— 参数非法/时机不对会被服务器拒(`resp.operation != req.operation`),客户端安全无副作用。

卡牌寻址:`CardInfo { CardPosition position; int index; int id; }`。`CardPosition` 枚举:`Hand=0, Used=1, Relic1=2, Relic2=3, Relic3=4, Relic5=5, Talent199=6, YuanGuRongLu=7, YuanGuXingTu=8, DreamXiuWeiCunQu=9`。

---

## 2. C# 面板:新增 PlacementApi(顶层静态类,namespace YiXianBot)

动作类(构建 RelicOperationReq + fire-and-forget 发送,返回 `ok:dispatched`/`EX:`):
```
PlacementApi.Place(int position, int cardIndex, int targetGrid)   // XiuWeiCunQu
PlacementApi.Swap (int position, int cardIndex, int targetGrid)   // SwitchCard
PlacementApi.Refine(int pos1, int idx1, int pos2, int idx2)       // JingHuaRongLian
```
每个内部:
```csharp
var req = new RelicOperationReq();
req.operation = RelicOperation.RelicOperationXiuWeiCunQu;
req.operationParams.Clear();
req.operationParams.Add(position); req.operationParams.Add(cardIndex);
req.operationParams.Add(2); req.operationParams.Add(targetGrid);
GameClientUtil.client.SendRoomMessageForILRAsync<RelicOperationResp>((IMessage)(object)req);  // fire-and-forget
return ApiUtil.Ok("dispatched");
```

只读布局(call_s 无参 + ret=json):
```
PlacementApi.Board()   // 当前所有卡的寻址信息,JSON
```
返回 `{"cards":[{"position":<int>,"index":<int>,"id":<int>}, ...]}`,来源 = `BattleManager.Instance.currentGameStatus.GetMainPlayerData()` 的卡列表(实现时按反编译定位玩家 CardInfo 列表;若数据模型不便,退而枚举 CardPanel 的 CardItem.cardInfo)。`id` 为卡配置 id,供二次开发对照 card_id_map。

> 引用补充:`RelicOperationReq`/`RelicOperationResp`/`RelicOperation`/`CardPosition`/`CardInfo`/`GameClientUtil` 在 DarkSun.HotUpdate(部分在 Proto 命名空间)。若 `RelicOperationReq` 等在 Proto 下,YiXianApi.cs 顶部已 `using Proto;`(与 Hud.cs 同),否则加。

---

## 3. Python 层:零改动(注册表驱动)

`Client`/`validate`/`gen_docs` 全遍历注册表 —— 只需在 `registry.py` 的 `API` 列表加 4 行 `ApiSpec`,命名空间 `placement` 自动出现为 `api.placement.place/swap/refine/board`:

```python
ApiSpec("placement","place", T_PLACE,"Place","call_s","status",["position","card_index","target_grid"],
        "摆牌:把卡摆到修为存取格(RelicOperationXiuWeiCunQu)"),
ApiSpec("placement","swap", T_PLACE,"Swap","call_s","status",["position","card_index","target_grid"],
        "换牌(RelicOperationSwitchCard)"),
ApiSpec("placement","refine", T_PLACE,"Refine","call_s","status",["pos1","idx1","pos2","idx2"],
        "炼化:熔炼两张卡(RelicOperationJingHuaRongLian)"),
ApiSpec("placement","board", T_PLACE,"Board","call_s","json",[],
        "当前卡牌布局 {cards:[{position,index,id}]},供寻址 place/swap/refine"),
```
(`T_PLACE = "YiXianBot.PlacementApi"`。)

`gen_docs.py` 的 `NS_TITLE`/`order` 加一项 `"placement": "Placement 摆牌阶段"`,文档自动带出。

---

## 4. 验证(活体)

`validate.py` 自动把 placement 纳入遍历。验证策略:
- `placement.board`(只读):在摆牌阶段实机读,断言返回 `{"cards":[...]}` 非空。
- `place/swap/refine`(有副作用):用 `board()` 读到的真实 (position,index) 探测调用一次,观察服务器是否接受(`ok:dispatched` + 游戏画面变化);非法参数被服务器拒属预期。需在**修炼阶段(摆牌)**手动验证(state_dep="修炼阶段")。

文档另出 `docs/api/validation-placement-2026-06-16.md` 记录实测。

---

## 5. 成功标准

- [ ] `PlacementApi` 4 方法编译进 `YiXianApi.dll`。
- [ ] registry 加 4 行后,`api.placement.*` 自动可调,单测(覆盖命名空间)更新含 `placement`。
- [ ] `gen_docs` 输出含 Placement 节。
- [ ] 活体:`board()` 读到真实卡列表;用其寻址 `place`/`swap`/`refine` 实测被服务器接受、画面正确变化。

## 6. 非目标

- 自动摆牌策略/AI(本轮只给"手动可调的操作 + 读盘",策略另立)。
- lock/seal/vote 等其余 RelicOperation(本轮不做,同枚举随时可加)。
- 目标格子的占用校验(交给服务器)。
