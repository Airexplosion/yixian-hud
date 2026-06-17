# 弈仙牌 game-api 设计

**分支:** `game-api`(基于 `same-domain-hud`,基础 commit 097660f = Hud31 跳过战斗 + 逆向函数验证工具)

**目标:** 把已逆向验证的弈仙牌游戏函数模块化封装成带命名空间的可调用 API(C# 面板层 + Python 包装层),逐个实机活体验证,并以行业规范写成 API 文档,供二次开发调用。

**只做 API 基础设施,不做上层功能。** 上层(自动化 bot、更多按钮等)留到后续各自的 spec。

---

## 1. 架构(两层)

```
外部工具 / 二次开发脚本
   │ import yixian_api
   ▼
[Python API 层]  native_hud/api/   ── 按命名空间组织
   api.battle.skip() / api.network.auto_select() / api.state.self_life()
   每个方法 = 组装(类型名, 方法名, 参数)→ 经 bot_glue3 RPC 调 C# 面板
   │ frida RPC (callS / callStr)
   ▼
[C# 面板层]  native_hud/csharp_api/ ── 编译成独立 YiXianApi{N}.dll
   namespace YiXianBot 下每命名空间一个顶层静态类:BattleApi / SceneApi / GameStatusApi / NetworkApi / StateApi
   每个静态方法 = 把零散反射调用收拢成一个干净入口(内部调 BattleManager.Instance.X / AccountUtil.Y)
   │ 直接 CLR 调用
   ▼
[游戏 ILRuntime AppDomain]  BattleManager / AccountUtil / GameStatus …
```

**为什么两层都要:** C# 面板在游戏内提供稳定、单一职责的调用面(一个方法 = 一个游戏动作,内部封装脏反射);Python 层用同名命名空间让外部工具 `import` 即用,不必关心内部反射细节。

**与 HUD 的关系:** `YiXianApi.dll` 是与 `YiXianHud{N}.dll` 并列的独立 assembly,二者可同时 `loadBot` 进同一 AppDomain、互不耦合。沿用 Hud 的**迭代改名法**(类名 + AssemblyName + Python 侧 TYPE 常量同步 `YiXianApi{N}→{N+1}`)以绕开 ILRuntime 的同名 assembly 去重。

---

## 2. 文件结构

| 文件 | 职责 |
|---|---|
| `native_hud/csharp_api/YiXianApi.cs` | C# 面板:`namespace YiXianBot` 下顶层静态类 `BattleApi`/`SceneApi`/`GameStatusApi`/`NetworkApi`/`StateApi`(顶层而非嵌套,避免 RPC 按 `+` 嵌套名反射的坑) |
| `native_hud/csharp_api/YiXianApi.csproj` | 编译成 `YiXianApi1.dll`;引用 `..\_refs\*.dll`(DarkSun.HotUpdate / UnityEngine.* 等),`AssemblyName=YiXianApi1` |
| `native_hud/api/__init__.py` | `connect(attach=False) -> Client`;`Client` 暴露 `.battle/.scene/.game_status/.network/.state` 子命名空间 |
| `native_hud/api/_rpc.py` | 底层管道:attach/spawn → 加载 `YiXianApi{N}.dll` → 等 AppDomain 就绪 → 按 `(TYPE, method, args)` 调 callS/callStr;`YiXianApiError` 异常类型 |
| `native_hud/api/battle.py` / `scene.py` / `game_status.py` / `network.py` / `state.py` | 各命名空间的方法包装(薄,组装参数 + 解析返回) |
| `native_hud/api/validate.py` | 活体自测验证器:逐个实机调用 + 断言,输出报告表 |
| `docs/api/yixian-api.md` | API 参考文档(行业规范) |

每个 Python 文件保持小而专(<400 行)。命名空间各一个文件,边界清晰、可独立测试。

---

## 3. 命名空间 + v1 函数清单

C# 调用形如 `YiXianBot.BattleApi.Skip`(RPC TypeName = `YiXianBot.BattleApi`,method = `Skip`);Python 形如 `api.battle.skip()`。命名空间在 C# 侧用类名前缀(`BattleApi`)表达,Python 侧用子对象(`api.battle`)表达,语义一致。

| 命名空间 | 函数 | 底层游戏调用(/tmp/decomp 已验证) |
|---|---|---|
| **Battle** | `Skip()` | 跳过链路:force-break 执行器 → 等 `!isExecuting` → `ChangeSceneType(修炼阶段)` → `GameStatusReq()`(照搬 `SkipBattleResultPanel.OnHide`) |
| | `ForceBreak()` | 仅对执行中 `BattleExecuter` 置 `forceBreakExecuting=true` |
| | `IsBattling()` 读 | 任一 `BattleManager.Instance.allBattleExecuters[i].isExecuting` |
| **Scene** | `Change(int sceneType)` | `BattleManager.Instance.ChangeSceneType(SceneType, useTween=true)` |
| | `Current()` 读 | `BattleManager.Instance.currentScene` |
| **GameStatus** | `Req()` | `BattleManager.Instance.GameStatusReq()` |
| **Network** | `AutoSelect(int ping=3)` | `AccountUtil.AutoSelectBestRouteAsync(int)`(UniTask<bool>) |
| | `Optimize()` | `AccountUtil.OptimizeNetwork(Action)` |
| | `Analyze(int n)` | `AccountUtil.AnalyzeNetworkAsync(int)` |
| **State**(只读) | `Round()` | `currentGameStatus.round` |
| | `SelfLife()` / `SelfLifeMax()` / `SelfXiuwei()` | `currentGameStatus.GetMainPlayerData()` 字段 |
| | `OpponentLife()` / `OpponentXiuwei()` / `OpponentBoard()` | `currentBattleResult` 对手侧 |
| | `SwapCount()` 换牌次数 | 摆牌阶段玩家数据 |
| | `SelfBoard()` | 自身当前板面卡列表 |

> 函数清单在实现期间若发现某字段路径与反编译不符,以实机反射为准并回填本表(实现计划里逐个核对)。

---

## 4. 数据流 & 返回契约

- **动作类**(Battle.Skip / Scene.Change / GameStatus.Req / Network.*):C# 返回 `"ok:..."` 或 `"EX:msg"`,Python 层校验前缀。
- **读盘类**(State.* / 读取类):C# 方法返回 **JSON 字符串**(经 `callStr`),Python 层 `json.loads` 成 dict/原值。
- Network 的 async(UniTask)函数:C# 面板 `fire-and-forget` 触发,立即返回 `"ok:dispatched"`;结果异步生效(与游戏内点击"自动选择"等效)。需要结果的(Analyze)再提供读取 `AccountUtil.networkAnalyzeResults` 的 State 风格查询。

---

## 5. 验证(全部实机活体自测)

`native_hud/api/validate.py`:spawn(或 `YX_ATTACH=1` attach)→ load `YiXianApi{N}.dll` → 等 AppDomain 就绪 → 逐个调用每个 API:

- **动作类**:调用 + 断言返回(如 `AutoSelect` → `ok:*`、`GameStatus.Req` → `ok`)。
- **状态依赖类**(Battle.Skip / Battle.ForceBreak / Scene.Change):先读 `Scene.Current()`,若不在所需场景 → 标 `SKIP(需斗法阶段)`,提示手动进对应场景后重跑;在场景内则实调并断言场景/数据变化。
- **读盘类**:实机读一帧,断言合理值(命 > 0、回合 ≥ 1、板面为 list)。

输出报告表:`函数 | 调用 | 返回 | 结果(PASS/FAIL/SKIP)`。报告的验证状态回填到文档"验证状态"列。

---

## 6. 错误处理

- C# 每个面板方法体 try/catch,异常 → 返回 `"EX:" + e.Message`(绝不抛出跨 RPC 边界)。
- Python `_rpc.py`:遇返回 `EX:` / `not found` / `Invoke` 失败 → 抛 `YiXianApiError(method, raw)`。
- RPC 未就绪(AppDomain 未起):重试到就绪(复用 `apicall.py` 的 60 次轮询模式),`getAD()` 在未就绪时抛错且**不会**误调目标。
- 不可变风格:Python 包装方法不改传入对象,返回新 dict。

---

## 7. 文档(行业规范)

`docs/api/yixian-api.md`,结构:

1. 概述 + 连接方式(`from yixian_api import connect; api = connect()`)。
2. 每命名空间一节;每函数一个块:
   - 签名(C# `YiXianApi.Battle.Skip()` + Python `api.battle.skip()`)
   - 参数(名/类型/默认/说明)
   - 返回(类型 + 示例 JSON)
   - 示例代码(Python)
   - 底层游戏调用(`BattleManager.Instance.ChangeSceneType(...)`)
   - 验证状态(✔ 实测 / ⚠ 状态依赖)

---

## 8. 成功标准

- [ ] `YiXianApi1.dll` 编译通过,`loadBot` 加载成功,与 Hud 并存不冲突。
- [ ] 5 个命名空间全部方法在 C# 面板实现,内部反射调用与 /tmp/decomp 一致。
- [ ] Python `yixian_api` 包可 `import` 并 `connect()`,每命名空间方法可调。
- [ ] `validate.py` 跑出全表报告,动作类 PASS、读盘类 PASS、状态依赖类在对应场景 PASS(其余 SKIP 并注明)。
- [ ] `docs/api/yixian-api.md` 覆盖全部 v1 函数,含签名/参数/返回/示例/底层/验证状态。

---

## 9. 非目标(YAGNI)

- 写操作类(SetSelfLife / SkipBattleReady / DebugReq)——发布服大概率被服务器拒,不做。
- 上层自动化(自动摆牌/挂机)——另立 spec。
- 旧的代理 + 网页 overlay 方案——不在本分支范围。
