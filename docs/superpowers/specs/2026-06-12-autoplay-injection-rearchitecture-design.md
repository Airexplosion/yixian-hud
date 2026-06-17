# 自动摆牌重构:从「代理发包」到「进程注入 + 调用游戏自身逻辑」

- 日期:2026-06-12
- 分支:`computer_use`
- 状态:**P0 侦察已完成,据实修订**(执行层 = ILRuntime AppDomain 反射;宿主/大脑 = **选项 A:Frida + Python**,已定)

> 本版在初版设计基础上,按 P0 注入侦察的实测结果做了修订。被 P0 推翻或细化的点用 **(P0 修订)** 标注。

## 1. 背景与问题

当前 `computer_use` 分支的 autoplay 通过 **mitmproxy 注入伪造的 Colyseus 协议帧**驱动游戏(`autoplay/protocol.py` 把动作编码成 `MoveCardReq` / `SimpleClientPact` 等 protobuf,经代理直接发给服务器)。这套「发包提交」有两个**结构性**缺陷:

1. **客户端 UI 不同步**:服务器是权威方。直接把 `MoveCardReq` 发给服务器,服务器认了并更新服务器态,但游戏**客户端没发起过这个操作**,本地乐观状态与服务器态脱节,导致画面错乱、撤回/放置无限震荡(见近期一连串 fix 提交)。
2. **拿不到实时状态**:状态只能等服务器广播、经代理解码后才知道;发完包还得等广播回来才知道成没成,中间是盲区,无法实时决策。

## 2. 目标与非目标

**目标**
- 用**注入游戏进程、调用游戏自身的逻辑方法**的方式执行动作,让客户端自己发起操作 → 本地状态/UI 自然同步。
- 从**进程内存实时读取对战状态**(含客户端本地态),消灭决策盲区。
- 决策「大脑」(coordinator / planner / strategy)迁入注入端(语言/宿主见 §4 开放项)。

**非目标**
- 不移植 yisim 对战模拟引擎(见 §4 决策)。
- 不做反作弊对抗 / 检测规避;不改动服务器交互之外的任何东西。
- 本设计不覆盖排位上分策略调优(那是 autoplay 既有 strategy 层的范畴)。

## 3. 侦察结论(P0 已验证的事实)

静态:Il2CppDumper(v6.7.46)dump `GameAssembly.dll` + `global-metadata.dat`(产物 `il2cpp_recon/`,仓库外)。
动态:`frida-il2cpp-bridge` 注入运行中的 `YiXianPai.exe`,在对局中实测(探针 `autoplay_recon/`,仓库外)。

| 维度 | 事实 |
|---|---|
| 引擎 | **Unity 2020.3.49f1** + **IL2CPP**;`global-metadata.dat` 11.9MB 未加密,**完整 dump**(dump.cs 31MB) |
| 反作弊 | **未发现** EAC/BattlEye 等 |
| 注入 | **frida-il2cpp-bridge 实测注入成功**,il2cpp 域可枚举全部程序集/类/方法 |
| 网络 | **Colyseus**;动作经 `ColyseusRoom<GameRoomState>.Send("<type>", ProtobufData{type,data})` 发送 |
| **协议枢纽** | `GameClient.m_RoomParser : ProtobufParser`(DarkSun.Utility.dll)双向枢纽:<br>• `DecodeFromProtobufData(ProtobufData)->IMessage` = **入站状态解码**(StateReader hook 点)<br>• `EncodeToProtobufData(IMessage)->ProtobufData` = **出站动作编码**(已实测捕获放牌 = `Proto.MoveCardReq`) |
| 🔴 **逻辑运行时** | **游戏逻辑跑在 ILRuntime(热更解释执行),不在原生 IL2CPP**。`Proto.*`、牌面/放牌/每张卡效果等都是 ILRuntime 的 `ILTypeInstance`,**不在 dump.cs** |
| 🟢 **逻辑可达** | `ILRuntime.Runtime.Enviorment.AppDomain` 单例可达;`mapType`/`LoadedTypes` 可枚举出**全部热更类型(实测 10222 个)**,英文可读名:`BattleManager` / `BattleExecuter` / **`CardOperationGridBase`**(放牌)/ 每张 `Card_XXX`(`OnExecuted`/`DoEffect`)。⟹ 经 AppDomain 反射(IType→IMethod→`Invoke`)**可读可调任意游戏逻辑** |
| 战斗模拟 | 客户端**有**整套战斗执行逻辑(`BattleExecuter.Execute` / `Card_XXX.OnExecuted` / `CharacterBattleAnimator`),但**深度耦合异步动画与战斗场景**,无法当作"无副作用、可假设性调用"的 headless oracle。战斗结果仍由服务器权威结算。 |

**关键推论(P0 修订)**:
- **执行层不再是"调 il2cpp 方法",而是"经 ILRuntime AppDomain 反射调用热更方法"**(如 `CardOperationGridBase` 的放牌方法)。这对 Frida 与 BepInEx 是同一种机制(都把 AppDomain 当 il2cpp 对象、走它的反射 API),**C# 相对 Frida 不再有调用优势**。
- **yisim 仍必须保留**:虽然客户端有战斗逻辑,但它为动画而生、强耦合 UI/场景,做不了推荐器需要的"对一堆未提交摆法的纯打分"。游戏当不了 oracle 的结论不变。

## 4. 关键决策与理由

| 决策 | 选择 | 理由 |
|---|---|---|
| 注入手段 | **frida-il2cpp-bridge**(P0 已全程跑通)固化为生产注入 | 读状态/枚举 AppDomain/调方法已实测可行;秒级迭代 |
| **执行机制 (P0 修订)** | **ILRuntime `AppDomain` 反射**:取 IType→IMethod→`Invoke` 调游戏逻辑方法 | 游戏逻辑在 ILRuntime,这是唯一入口;调 `CardOperationGridBase` 放牌方法即客户端自执行 → UI 同步 |
| yisim | **保留 JS,经本地通道调用** | 游戏不能当 oracle(§3),移植无收益 |
| yisim 宿主 | **Node 边车进程(localhost RPC)** | 复用原封不动的 `web/yisim.bundle.js` + recommend 逻辑 |
| 读状态 | **hook `ProtobufParser.DecodeFromProtobufData`** 拿入站 IMessage | 真·实时,与代理同样的 protobuf 但在进程内 |
| 显示层 | **游戏内 IMGUI overlay** | 一体化,不依赖外部窗口 |

### ✅ 宿主/大脑 = 选项 A:Frida + Python(已定)

> 初版选过"大脑迁到 C# / BepInEx"。P0 发现游戏逻辑在 ILRuntime 后,C# 对执行层不再有优势(Frida 与 BepInEx 调 AppDomain 反射是同一套机制),故**改定为选项 A**:

- **大脑**:现有 **Python**(recommender / planner / coordinator / strategy)+ **JS yisim** —— 原封不动复用,只把"读状态 / 执行"两端从代理切到注入桥。
- **注入宿主**:`frida-python` 加载 `frida-il2cpp-bridge` agent;Python 与 agent 经 frida message bridge 收发。
- 理由:改动最小、复用最多、P0 已全程跑通;C# 方案对 ILRuntime 无优势却要重写大脑,被否决。

被否决的选项 B(BepInEx C# 模组)留档:组件职责相同,仅宿主语言/打包不同;若未来 Frida 路线遇阻可回退。

## 5. 架构(以选项 A 描述)

```
                    YiXianPai.exe（被注入）
   ┌──────────────────────────────────────────────────────┐
   │  il2cpp-bridge agent（注入侧:读状态 + 反射执行）        │
   │                                                        │
   │  StateReader ── hook ProtobufParser.DecodeFromProtobufData ─▶ 实时 GameState
   │       │                                                │   牌面/手牌/对手/血/灵气/选项
   │  ActionExecutor ── ILRuntime AppDomain.Invoke ─────────▶│ 游戏自执行放牌/换牌/合成（UI 同步）
   │       │ (CardOperationGridBase 等热更方法)              │
   │  Overlay（IMGUI：状态/推荐/开关/日志）                   │
   └───────┬───────────────────────────────────────┬────────┘
           │ frida message bridge                  │
   ┌───────▼─────────────────────┐    ┌────────────▼────────────┐
   │  大脑（Python）             │    │  yisim 边车（Node+bundle）│
   │  Coordinator/Planner/Strategy│◀──▶│  simulate / recommendBoard│
   └─────────────────────────────┘    └─────────────────────────┘
```

**数据流(一个决策环)**:hook 入站 protobuf → StateReader → GameState → Coordinator 判断阶段 →(需要时调 yisim 算最佳摆法)→ Planner 出拖牌序列 / Strategy 选离散项 → ActionExecutor 经 AppDomain.Invoke 调游戏方法 → 游戏更新内存与 UI → StateReader 读回校验 → 下一步。

## 6. 组件

- **StateReader**:hook `ProtobufParser.DecodeFromProtobufData`(写法:`.implementation` + `NativeFunction(virtualAddress)` 转发原始调用,见 P0 notes),把入站 `Proto.*` IMessage 归一成与现有 view-model **同形**的 `GameState`。读 ILTypeInstance 字段经 ILRuntime 反射。
- **ActionExecutor**:把每个动作(放/撤/移内/合成/换牌/炼化/突破/选仙命/选道韵/每轮确认)包成一个方法,内部经 **AppDomain.Invoke 调对应热更方法**(放牌优先定位 `CardOperationGridBase`)。每次执行后由 StateReader 读回校验。
- **Coordinator / Planner / Strategy**:选项 A 下保留现有 Python(`autoplay/coordinator.py`/`planner.py`/`strategy.py`),仅把"读状态/执行"两端从代理切到注入桥。
- **SimClient**:向 yisim 边车发 RPC(选项 A 下即现有 Python→Node 调用)。
- **yisim 边车**:加载现成 `web/yisim.bundle.js` + `web/recommend.js`,localhost 暴露 `simulate`/`recommendBoard`。零改动复用。
- **Overlay**:游戏内 IMGUI 显示实时状态、推荐摆法、autoplay 开关/急停、日志。

## 7. 风险(P0 修订)

**make-or-break 已基本回答(P0)**:注入 ✓ / 实时读状态 ✓(DecodeFromProtobufData)/ 动作可观察 ✓(MoveCardReq)/ **游戏逻辑全可达可调 ✓(ILRuntime AppDomain 反射,10222 类)**。

**唯一剩余实操验证**:取 `CardOperationGridBase` 放牌方法 → `AppDomain.Invoke` → 看 UI 是否同步(P2 起手;已无技术悬念,因反射机制已验证)。

**其它风险**:
- **ILRuntime 反射编组**:传参给热更方法(尤其 ILTypeInstance / 枚举 / 自定义类型)需经 AppDomain 的封送,细节多 → P2 逐个动作验证。
- **游戏热更/版本更新**:热更 DLL 变化会改类/方法 → 用**按名字反射**(类名/方法名)而非硬编码地址,降低脆性;名字变了需重定位。
- **封号**:无反作弊但仍违反 ToS → 默认 dry-run、先练习/人机、急停热键。

## 8. 阶段路线(P0 修订)

| 阶段 | 内容 | 验收 | 状态 |
|---|---|---|---|
| **P0** | 注入打通 + 侦察:状态根 / 协议枢纽 / ILRuntime AppDomain / 放牌消息 | 已读通实时态、捕获 MoveCardReq、AppDomain 全枚举 | ✅ **基本完成**(差"调放牌方法看 UI 同步"实证) |
| **P1** | StateReader 完整 GameState 提取 | 与代理解码**对拍一致** | |
| **P2** | ActionExecutor 全部动作(AppDomain.Invoke) | 每动作**读回状态校验**通过(从放牌 UI 同步实证起步) | |
| **P3** | yisim Node 边车 + SimClient | 复用现有 parity 测试 | |
| **P4** | 大脑接线(选项 A:Python 切注入桥 / 选项 B:移植 C#) | 移植 test_planner + 状态机测试 | |
| **P5** | IMGUI overlay | 画面可见、开关/急停可用 | |
| **P6** | 整局全自动 + 安全 | 人机/练习跑通端到端 → 再上排位 | |

## 9. 错误处理 / 安全

- **急停热键**:任何时刻一键禁用 autoplay。
- **逐动作校验**:每个动作后 StateReader 读回,与预期不符即重试(限次)→ 仍不符则中止报警,不盲目继续。
- **未知状态不动**:Coordinator 遇无法识别的阶段,停在原地或交还人控。
- **超时保护**:等待服务器响应/状态变化设超时,超时走错误恢复。
- **默认 dry-run**:只规划打印、不真执行,直到**显式开关**;先练习/人机调通。

## 10. 测试

- **StateReader**:同一局对照现有 `proxy/` 解码出的 view-model,逐字段对拍。
- **ActionExecutor**:每个动作执行后读回状态断言(放置后该格=该牌、手牌-1 等)。
- **yisim 边车**:复用仓库现有 yisim parity / 优化验证测试。
- **大脑**:复用/移植 `autoplay/test_planner.py`;为 Coordinator 状态机补单测。
- **集成**:dry-run 全程日志审阅 → 练习模式真执行 → 排位。

## 11. 工具链 / 构建 / 目录(P0 修订)

- **注入(选项 A)**:`frida` + `frida-tools`(已装于 `.venv`);agent 用 `frida-il2cpp-bridge` + `frida-compile`(TS→单文件 agent);Python 侧 `frida.attach("YiXianPai.exe")` 加载 agent 并经 message bridge 收发。
- **注入(选项 B)**:BepInEx 6(BepInEx.Unity.IL2CPP)+ Il2CppInterop,产出 `YiXianAuto.dll`;ILRuntime AppDomain 仍按反射调用。
- **yisim 边车**:`sidecar/`(Node 脚本 + 复用 `web/yisim.bundle.js`、`web/recommend.js`)。
- **侦察产物**:`il2cpp_recon/`(dump)与 `autoplay_recon/`(frida agent / 全量热更类型表 / run.py)留在仓库外,**不进 git**。
- 旧 `autoplay/protocol.py`(发包路径)在 P2 验证新执行路径稳定后**废弃**。

## 12. 开放项(实施时定)

- ~~大脑/宿主 A vs B~~ —— **已定:选项 A(Frida + Python)**,见 §4。
- ActionExecutor 各动作的精确热更方法名 + 参数——P2 逐个经 AppDomain 反射定位(放牌从 `CardOperationGridBase` 起)。
- StateReader 对 ILTypeInstance 字段的读取封装——P1 定。
- (选项 A)Python↔agent 的桥协议——倾向 frida `rpc.exports` + `script.post`/`on('message')`。
