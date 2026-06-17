# P2 ActionExecutor 侦察

## ILRuntime 方法反射枚举(已跑通)
- 经 AppDomain `mapType`→InnerDictionary→entries 拿到某类的 `IType`(ILType),
  调 `IType.GetMethods()`→`List<IMethod>`,`get_Item(i).get_Name()` 列方法名。
- 注意:entries 的 key 用 `.content` 取(否则带引号匹配不上)。

## 放牌处理方法(找到)
- **`CardGrid`**(摆牌格子,ILType,26 方法):
  - `OnDrop(1)` — Unity 拖放事件处理
  - **`OnCardDropped(1)`** — "卡被放到此格"处理器(最可能的放牌入口)
  - `EnableDropEvent(0)` / `GetCard(0)` / `RefreshGrid(0)` / `ForceRefreshGrid(0)` / `Init(1)` /
    `OnInit/OnEnable/OnUpdate/OnDisable` / `ShowStarPosIcon(1)` / `get/set index/cardRoot/unlocked/visible`
- **`CardOperationGridBase`**(12):`OnDrop(1)` / `GetCard(0)` / `Refresh(1)` / `OnInit(0)` /
  `get cardPanel/readyLayer` / `get/set index/cardRoot/gridType`
- ⟹ 放牌走 `OnDrop`/`OnCardDropped`,触发本地 UI 更新 + 发 MoveCardReq。

## P2 make-or-break(待做)
1. 查 `OnCardDropped(1)` / `OnDrop(1)` 的**参数类型**(`IMethod` 的 parameters):
   - 若是卡对象/数据 → 好构造;若是 Unity `PointerEventData` → 需合成拖放事件(较难)。
2. 取目标 `CardGrid` 实例(场景里的格子,gc.choose 或从 CardPanel 拿),
   经 `AppDomain.Invoke(method, instance, args)` 调用。
3. 实测:游戏是否接受 + **UI 是否即时同步**(这是执行侧最终 make-or-break)。
- 备选:找更高层的 CardPanel/手牌管理器的"MoveCard(handIdx, boardIdx)"类方法,参数更简单。

## 🟢🟢🟢 P2 make-or-break 成功(实测!)
- 干净放牌方法 = **`CardPanel.MoveToGrid(CardItem, CardGrid)`**(非拖放事件 OnDrop)。
- 执行链(全经 ILRuntime `AppDomain.Invoke(IMethod, instance, object[])`):
  1. 堆里 `gc.choose(ILTypeInstance)` 筛 `get_Type().get_Name()=="CardPanel"` 拿实例(名字用 `.content`,否则带引号匹配不上)。
  2. `GetHandCards()`→List(手牌) / `GetCardGrids()`→List(8 格);`CardGrid.GetCard()==null` 找空格。
  3. `args = Il2Cpp.array(System.Object, [card, grid])`;`MoveToGrid(card, grid)`。
- 反射调用机制确认:`AppDomain.Invoke(IMethod, 实例, object[])`;`IType.GetMethods()`/`get_Item`/`get_Name(.content)` 取 IMethod。
- **实测:把手牌#0 放进空格#6 → 牌真的放上牌面、UI 同步**(用户确认)。
- ⟹ 执行侧根治:调客户端自己的方法 → 客户端自执行 → UI 不脱节。**整个注入架构两端(读+执行)全部验证通过。**

## 对 P2 工程化的输入
- ActionExecutor 各动作映射:
  - 放牌 → `CardPanel.MoveToGrid(card, grid)`;撤回 → `MoveToHand(card)`
  - 合成 → `TryUpgradeHandCard(card, card)` / `TryFuseHandCard(card, card, int)`
  - 换牌 → `ReplaceCardAsync(...)`;炼化 → `RefineCardAsync(...)`;插入 → `InsertCard(card)`
  - 突破/选仙命/选道韵/每轮确认 → 走 BattleManager 的对应 Req 方法(待定位)
- 取实例/参数:`GetHandCards`/`GetCardGrids`/`GetUsedCards` + `CardGrid.GetCard`;
  通用工具:按名拿 IType→IMethod→Invoke(注意 .content 去引号)。

## 2026-06-13 补齐剩余动作(全局方法扫描 agent 14/15/16)

扫遍 10222 个热更类后的**完整动作机制图**:

- **准备**:`ReadyLayer.PressReadyButton()` — 无参,内部自发 SimpleClientPact(kind=3)。
  ⟹ ActionExecutor 加 `ready()`,**已 resolve 校验通过(method+inst live)**;
  实际开火会提交回合,留待练习局/可弃回合 live 验证。
- **换牌/炼化**:纯拖拽几何驱动 —— `ReplaceArea.OnDrop(PointerEventData)` /
  `RefineArea.OnDrop(PointerEventData)` 吃携带被拖 CardItem 的事件;
  `CardPanel.ReplaceCardAsync/RefineCardAsync` 都需服务器 `Resp`(响应后驱动 UI,事后)。
  **没有干净的单方法发起入口。** ⟹ P4:合成 PointerEventData,或当作服务器权威 Req。
- **选道韵**:`BattleDaoYunSelectionPanel.set_daoYun(id)` + `OnSelected()`;
  确认 `BattleManager.PendingDaoYunReq(bool)`。`OnSelected()` 无参 → `call()` 可调。
- **选仙命/天衍**:`FateStrategyPanel.OnFateStrategySelected(idx,ReadyLayer,PlayerData)` +
  `OnConfirmButtonClick()`;`TalentSelectionPanel.TalentOnSelect(id)`;
  确认 `BattleManager.PendingTalentReq(bool,bool)`。确认按钮无参 → `call()` 可调。
- **突破**:全局 `*Req`/`Pact`/`Breakthrough` 扫描**未命中具名方法** —— 应为某个
  通用 `SimpleClientPact(kind=2)` 发送器,待突破 UI 出现时再定位。

**所有高级动作都把发包封装在热更方法内部** —— 调它们即可,无需自己拼 SimpleClientPact。
带参选择 handler(`set_daoYun(id)`/`TalentOnSelect(id)`)需对 int 做 System.Object 装箱,
待面板打开可实测时再做。

### ActionExecutor 新增(actions.ts + executor.py)
- `ready()` — `ReadyLayer.PressReadyButton()`,补齐"摆牌→准备"闭环。
- `resolve(type, method, pc?)` — **零副作用**可达性探针 `{method:bool, instance:bool}`,
  用于在不开火的情况下验证有副作用/依赖面板的动作已接好。
- `call(type, method)` — 通用无参 handler 调用(各 `OnSelected/OnConfirmButtonClick` 确认按钮)。
- 8 个入口 resolve 全绿(见 autoplay_recon/validate_actions.py)。

## 2026-06-13 (下午) 换牌/炼化/突破 攻克 —— 统一发送管线

之前判定"无干净入口"的三个动作,通过**出口抓包 + 复现真实 Req 字节**全部打通。

### 出口抓包(autoplay_recon/capture_actions.py)逆出的 wire 格式
- **换牌** `ReplaceCardReq { CardInfo card=1 { f2=pos?, f3=cardId } }`,如 `0a06 100d 18 ca843d`
- **炼化** `RefineCardReq` 同构;`f2` 可省略 → `0a04 18 <cardId>` 服务器也接受
- **突破** `SimpleClientPact { f1=kind }` = `08 02` → **kind=2**
- 突破后服务器回 `PendingTalentResp` 给选项 → 选择 = `SimpleClientPact{f1=5, f2=id}` = `08 05 10 43`
- 通用:`SimpleClientPact{kind, id?}` —— 准备=3 突破=2 仙命=5+id 道韵=9+id

### 发送管线(全 il2cpp,零 ILRuntime 装箱)—— actions.ts sendmsg
1. `GameClient`(DarkSun.Utility.dll 真 il2cpp,**单一 live 实例** via gc.choose)
2. `ProtobufParser`(实例方法!)`.DecodeFromBase64(typeName, base64)` → IMessage
3. `GameClient.SendRoomMessageAsync(IMessage)`(fire-and-forget UniTask)
⟹ `sendmsg(typeName, base64)`:我按已知格式拼字节 → 游戏自己的解析器转 IMessage → 自己的发送器发出。
**服务器权威**(Resp 驱动 UI),所以注入发送 UI 安全 —— 跟放牌(本地预测)本质不同。
- frida rpc 导出名必须全小写(`sendMsg`→查 `sendmsg` 对不上)。

### cardId/pos 映射(map_cardid.py 十余样本钉死)
- **wire cardId === StateReader ZoneCard.id**(无 canonical 偏差)
- **wire pos === 0-based 手牌索引**
- ⟹ P4 数据流:读 shadow.hand → 选第 i 张 → `refine/replace(hand[i].id, i)`

### 实测
- **突破** `breakthrough()` → 用户**肉眼确认境界突破**(SimpleClientPact kind=2)。
- **炼化** `refine(cardId,pos)` 发送成功;字节与真实客户端**逐字节一致**;待手里有牌时 live 视觉复验。

### ActionExecutor 最终 API(executor.py)
- 本地预测动作(调游戏方法,P2 早段证实):`place/evict/merge/ready`
- 服务器权威动作(发包,本节):`breakthrough() / refine(id,pos) / replace(id,pos) /
  select_fate(id) / select_daoyun(id) / pact(kind,id)`,底层统一 `send_msg`。
- 通用:`state / resolve / call`。**读(StateReader)写(ActionExecutor)两端全部打通。**

## 2026-06-13 (晚) UI 同步攻坚 —— 炼化做到"发包+客户端自播动画"

### 核心教训:服务器权威动作裸发包不更新本地 UI
- 突破/炼化/换牌裸发包,服务器会接受(SUCCESS),但**本地 UI 不动,要到下回合整包同步才显示**。
  原因:客户端只在**自己发起**(拖拽进区域)时进入"待响应"状态,收到 Resp 才播动画/消卡。
  我直接塞包,客户端没这个待定态 → 收到 Resp 不知道对应哪张卡 → UI 不更新。
- **拖拽模拟(合成 PointerEventData 调 `RefineArea.OnDrop`)不可行**:OnDrop 内部校验拖拽上下文
  (射线/位置/拖拽态),合成事件过不了校验,静默什么都不做(返回 ok 但不发包)。
  OnBeginDrag/OnEndDrag 全序列反而触发取消。3 种模式实测全废。

### ✅ 可行方案:发包 + 调客户端自己的响应处理方法
`refineshow(handIdx)`:
1. 发真 `RefineCardReq`(服务器更新)—— 经 `GameClient.SendRoomMessageAsync`
2. **本地构造**一个 success 的 `RefineCardResp`(`08 01 1a{len}18{cardId}`,经 DecodeFromBase64 转 IMessage)
3. 调 **`RefineArea.RefineCard(CardItem, RefineCardResp)`** —— 这是客户端收到响应后消卡+播动画的方法
⟹ 客户端自己消卡、播动画、UI 同步。**实测连炼整手牌、稳定、有动画**(用户确认)。
- 取卡 GameObject 的钥匙:`CardItem.GetMoveableRectTransform().gameObject`(IType.GetMethods 不含继承的
  get_gameObject,但 GetMoveableRectTransform 是声明方法)。

### 明天做换牌(同法):
- `ReplaceArea.ReplaceCard(CardItem, Proto.ReplaceCardResp)`。
- **注意差异**:换牌 Resp 带**新卡**(field2)——`08 01 12{newCardInfo} 1a{oldCardInfo}`,
  本地构造 resp 时新卡 id 未知(服务器才知道)。可能要先发包、**等真 Resp 回来再调 ReplaceCard**
  (拦截 inbound ReplaceCardResp + 匹配 cardId),而不是本地伪造。这是和炼化的关键区别。

### 性能(常驻面板必须):IL2CPP 是 Boehm GC(不移动对象)
- 句柄不会因 GC 失效。"system error" 真因 = 热更类型字典**扩容换了 entries 数组**(进对局加载新类型)。
- 缓存策略:
  - **类型/方法 IType/IMethod**:可永久缓存(元数据稳定);字典 count 变了才清。
  - **应用级单例**(GameClient/ProtobufParser):永久缓存(整 app 生命周期)。
  - **对局场景实例**(CardPanel/RefineArea/…):**每回合 `hand()`/`state()` 时重建一次**
    (`refreshInstances()` 一次堆扫描);动作复用缓存。**绝不跨对局缓存** —— 上一局的死实例
    Boehm 没回收但已是销毁的 Unity 对象,调它**原生崩溃**(本会话崩过两次,皆此因或 hook 重写)。
- `Il2Cpp.gc.choose(klass)` = 全堆扫描,跑在游戏主线程 → 卡顿源。降到每回合一次后用户确认"顺了"。

### 其它坑
- **frida rpc 导出名必须全小写**:`sendMsg`/`refineDrag` 驼峰 → frida 查 `sendmsg`/`refinedrag` 对不上 →
  RPCException。统一小写。
- **绝不 hook/重写 native 方法**(尤其异步 UniTask 的 `SendRoomMessageAsync`)—— 用 NativeFunction
  重写转发会崩游戏。只读/调方法是安全的。
- 开发面板:`autoplay_recon/gui_panel.py`(常驻 tkinter,attach 一次,按钮触发,log 写
  `gui_panel.log`),配合 `capture.ts` 被动记响应。仅 dev 工具,未入库。
