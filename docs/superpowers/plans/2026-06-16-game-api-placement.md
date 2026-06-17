# game-api placement 扩展实现计划

> REQUIRED SUB-SKILL: superpowers:subagent-driven-development。承接 game-api 分支与架构。

**Goal:** 加 `placement` 命名空间(place/swap/refine + board 读盘),演示注册表驱动的可扩展性。

**Architecture:** C# 顶层静态类 `PlacementApi`(namespace YiXianBot)构建并发送 `RelicOperationReq` / 读卡布局;Python 层零改动(只在 registry 加 4 行)。

**Tech Stack:** 同 game-api(dotnet build YiXianApi.csproj,bot_glue3 RPC,pytest)。决compile 在 `/tmp/decomp/*.cs`。

**关键约定(同 game-api):** C# 方法 try/catch → `ApiUtil.Ok/Err/Ex`;`RelicOperationReq`/`RelicOperation`/`CardPosition`/`CardInfo`/`GameClientUtil` 在 DarkSun.HotUpdate(可能在 Proto 命名空间 —— YiXianApi.cs 顶部若无 `using Proto;` 则加,与 Hud.cs 同)。

---

## Task P1: C# PlacementApi — Place / Swap / Board

**Files:** Modify `native_hud/csharp_api/YiXianApi.cs`(新增 `public static class PlacementApi`,放在 StateApi 后)。

- [ ] **Step 1: 在 YiXianApi.cs 顶部确保 `using Proto;`**(若已无则加;`RelicOperationReq` 等可能在 Proto)。先编译试探:不确定就加上,编译报"未使用/找不到"再调。

- [ ] **Step 2: 新增 PlacementApi(Place/Swap/Board)**
```csharp
    public static class PlacementApi
    {
        // 发送一个 RelicOperationReq(fire-and-forget;服务器权威校验,非法参数被拒,安全)。
        static string Send(RelicOperation op, int[] ps)
        {
            try {
                var req = new RelicOperationReq();
                req.operation = op;
                req.operationParams.Clear();
                for (int i = 0; i < ps.Length; i++) req.operationParams.Add(ps[i]);
                GameClientUtil.client.SendRoomMessageForILRAsync<RelicOperationResp>((IMessage)(object)req);
                return ApiUtil.Ok("dispatched");
            } catch (Exception e) { return ApiUtil.Ex(e); }
        }
        // 摆牌:把 (position,cardIndex) 的卡摆到修为存取格 targetGrid。
        public static string Place(int position, int cardIndex, int targetGrid)
        { return Send(RelicOperation.RelicOperationXiuWeiCunQu, new int[] { position, cardIndex, 2, targetGrid }); }
        // 换牌:把 (position,cardIndex) 的卡换到 targetGrid。
        public static string Swap(int position, int cardIndex, int targetGrid)
        { return Send(RelicOperation.RelicOperationSwitchCard, new int[] { position, cardIndex, 3, targetGrid }); }
        // 当前卡牌布局(寻址用):{"cards":[{"position","index","id"}]}。
        public static string Board()
        {
            try {
                var bm = BattleManager.Instance;
                var gs = bm != null ? bm.currentGameStatus : null;
                if (gs == null) return ApiUtil.Err("no GameStatus");
                var p = gs.GetMainPlayerData();
                if (p == null) return ApiUtil.Err("no PlayerData");
                var sb = new StringBuilder();
                sb.Append("{\"cards\":[");
                int n = 0;
                foreach (var ci in EnumerateCards(p))
                {
                    if (ci == null) continue;
                    if (n++ > 0) sb.Append(",");
                    sb.Append("{\"position\":").Append((int)ci.position)
                      .Append(",\"index\":").Append(ci.index)
                      .Append(",\"id\":").Append(ci.id).Append("}");
                }
                sb.Append("]}");
                return sb.ToString();
            } catch (Exception e) { return ApiUtil.Ex(e); }
        }
        // 枚举主玩家当前所有 CardInfo。实现注记:BattlePlayerData 的卡列表字段名按反编译核定
        // (grep "class BattlePlayerData" 找 List<CardInfo> 类字段,如 cards/cardInfos)。
        // 若数据模型不便,退而枚举 CardPanel 的 CardItem.cardInfo:
        //   var cp = ILRPanelBase.FindILRPanel<BattlePanel>()?.FindILRSubPanel<CardPanel>();
        // 然后遍历其 CardItem 列表取 .cardInfo。
        static IEnumerable<CardInfo> EnumerateCards(BattlePlayerData p)
        {
            // TODO(impl): 返回 p 的 CardInfo 列表(按反编译定位真实字段)。下面是占位骨架:
            var list = new List<CardInfo>();
            return list;
        }
    }
```

- [ ] **Step 3: 落实 EnumerateCards** —— grep `class BattlePlayerData` 找其 `List<CardInfo>` 字段(候选名 `cards`/`cardInfos`/`cardList`);返回该列表。若找不到合适字段,改走 CardPanel:`ILRPanelBase.FindILRPanel<BattlePanel>().FindILRSubPanel<CardPanel>()` 的 CardItem 列表(grep `class CardPanel` 找其卡列表),`yield return item.cardInfo`。务必让 `Board()` 在摆牌阶段能返回真实非空 cards(Task P4 实测)。

- [ ] **Step 4: 编译**
Run: `dotnet build "native_hud/csharp_api/YiXianApi.csproj" -c Release -v q -nologo`
Expected: `0 个错误`。若 `RelicOperationReq`/`GameClientUtil`/`CardInfo` 找不到 → 确认 `using Proto;` + grep 反编译核命名空间/字段。

- [ ] **Step 5: 拷贝 + 提交**
```bash
cp native_hud/csharp_api/bin/Release/net40/YiXianApi.dll native_hud/_build/YiXianApi.dll
git add native_hud/csharp_api/YiXianApi.cs native_hud/_build/YiXianApi.dll
git commit -m "feat(game-api): PlacementApi Place/Swap/Board"
```

---

## Task P2: C# PlacementApi.Refine(炼化)

**Files:** Modify `native_hud/csharp_api/YiXianApi.cs`(给 PlacementApi 加 `Refine`)。

- [ ] **Step 1: 深挖炼化 operationParams 布局**
炼化 = `RelicOperation.RelicOperationJingHuaRongLian`(3),熔炼两张卡。反编译里熔炉发送处在 218439 附近,但 `operationParams` 在两张卡进熔炉格时更早填好。grep 定位:
`grep -nE "RelicOperationJingHuaRongLian|operationParams" /tmp/decomp/*.cs | sed -n '1,40p'`
找到 fusion 流程里 `m_CachedRelicOperationReq.operationParams.Add(...)` 的四/多个 Add,确定布局(很可能 `[(int)pos1, idx1, (int)pos2, idx2]` 或含常量)。**以反编译实证为准**。

- [ ] **Step 2: 实现 Refine**(按 Step 1 确定的布局;下面按最可能的 `[pos1,idx1,pos2,idx2]`,如实证不同则改)
```csharp
        // 炼化:熔炼两张卡 (pos1,idx1) + (pos2,idx2)。params 布局以反编译实证为准。
        public static string Refine(int pos1, int idx1, int pos2, int idx2)
        { return Send(RelicOperation.RelicOperationJingHuaRongLian, new int[] { pos1, idx1, pos2, idx2 }); }
```
（`Send` 已在 P1 定义。）

- [ ] **Step 3: 编译 + 拷贝 + 提交**
```bash
dotnet build "native_hud/csharp_api/YiXianApi.csproj" -c Release -v q -nologo
cp native_hud/csharp_api/bin/Release/net40/YiXianApi.dll native_hud/_build/YiXianApi.dll
git add native_hud/csharp_api/YiXianApi.cs native_hud/_build/YiXianApi.dll
git commit -m "feat(game-api): PlacementApi Refine(炼化)"
```
Expected: `0 个错误`。

- [ ] **Step 4: 在报告里写明你确定的炼化 params 布局**(及反编译行号依据),供 Task P4 实测核对。

---

## Task P3: registry + docs + test 加 placement

**Files:** Modify `native_hud/api/registry.py`、`native_hud/tests/test_registry.py`、`native_hud/api/gen_docs.py`;regenerate `docs/api/yixian-api.md`。

- [ ] **Step 1: registry.py 加 T_PLACE 常量 + 4 行 ApiSpec**(放在 state 之后):
```python
T_PLACE = "YiXianBot.PlacementApi"
```
在 `API` 列表末尾(state 之后)加:
```python
    ApiSpec("placement", "board", T_PLACE, "Board", "call_s", "json", [],
            "当前卡牌布局 {cards:[{position,index,id}]},供寻址 place/swap/refine"),
    ApiSpec("placement", "place", T_PLACE, "Place", "call_s", "status",
            ["position", "card_index", "target_grid"],
            "摆牌:把卡摆到修为存取格(RelicOperationXiuWeiCunQu)", "修炼阶段"),
    ApiSpec("placement", "swap", T_PLACE, "Swap", "call_s", "status",
            ["position", "card_index", "target_grid"],
            "换牌(RelicOperationSwitchCard)", "修炼阶段"),
    ApiSpec("placement", "refine", T_PLACE, "Refine", "call_s", "status",
            ["pos1", "idx1", "pos2", "idx2"],
            "炼化:熔炼两张卡(RelicOperationJingHuaRongLian)", "修炼阶段"),
```

- [ ] **Step 2: test_registry.py 的命名空间集合加 placement**
把 `test_covers_v1_namespaces` 里的集合改为:
```python
    assert {s.namespace for s in API} == {"battle", "scene", "game_status", "network", "state", "placement"}
```

- [ ] **Step 3: gen_docs.py 加 placement 的标题与顺序**
- `NS_TITLE` 加一项:`"placement": "Placement 摆牌阶段",`
- `order` 列表末尾加 `"placement"`:`order = ["battle", "scene", "game_status", "network", "state", "placement"]`

- [ ] **Step 4: 跑单测 + 重生成文档**
```bash
python -m pytest native_hud/tests/ -q          # 期望全过(命名空间断言已更新)
python native_hud/api/gen_docs.py              # 重生成,含 Placement 节
grep -cE "^### \`api\." docs/api/yixian-api.md  # 期望 15
```

- [ ] **Step 5: 提交**
```bash
git add native_hud/api/registry.py native_hud/tests/test_registry.py native_hud/api/gen_docs.py docs/api/yixian-api.md
git commit -m "feat(game-api): 注册 placement 命名空间(place/swap/refine/board)+ 文档"
```

---

## Task P4: placement 活体实测(需用户在对局摆牌阶段)

**Files:** 创建 `docs/api/validation-placement-2026-06-16.md`。

- [ ] **Step 1: 摆牌阶段读盘**(用户在修炼阶段)
Run: `YX_ATTACH=1 PYTHONIOENCODING=utf-8 python native_hud/bridge/apicall.py YiXianBot.PlacementApi Board`
期望返回非空 `{"cards":[{"position":..,"index":..,"id":..}, ...]}`。记录真实卡的 (position,index)。

- [ ] **Step 2: 用读到的真实卡寻址 place / swap**
用 Step 1 的某张手牌(position=0=Hand)调:
`apicall.py YiXianBot.PlacementApi Place <position> <cardIndex> <targetGrid>` → 期望 `ok:dispatched` 且画面把该卡摆上格子。
swap 同理。观察服务器是否接受(画面变化);被拒则调整参数/布局。

- [ ] **Step 3: refine 实测**(若 P2 的布局正确)
用两张可熔炼的卡:`apicall.py YiXianBot.PlacementApi Refine <pos1> <idx1> <pos2> <idx2>` → 观察熔炼结果。布局错则回 P2 修正重测。

- [ ] **Step 4: 写验证报告** `docs/api/validation-placement-2026-06-16.md`(板式同 validation-2026-06-16.md:逐项 ✔/✗ + 实测返回 + 复现命令),提交:
```bash
git add docs/api/validation-placement-2026-06-16.md
git commit -m "test(game-api): placement 活体验证报告"
```

---

## Self-Review 覆盖

- spec §2 PlacementApi → P1(place/swap/board)+ P2(refine)✓
- spec §3 registry 零改动其余层 → P3(registry/test/gen_docs)✓
- spec §4 活体验证 → P4 ✓
- 扩展性证明:Python Client/_rpc/validate 不改一行,加 namespace 仅靠 registry+gen_docs 两处声明 ✓
- 已知风险:Board 的 CardInfo 列表字段(P1 Step3 实证)、炼化 params 布局(P2 Step1 实证)—— 均以实机/反编译裁决,P4 兜底。
