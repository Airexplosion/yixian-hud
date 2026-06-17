# YiXianHUD 三新功能设计

**分支:** `hud-features`(off `game-api`,基于 Hud31 + 现有 launcher/设置面板)

**目标:** 给 YiXianHUD 加三个功能:① 注入文字/按钮位置可在设置面板调;② 按 Tab 弹游戏内卡池 overlay(全卡池 + 卡图 + 剩数,标 3 张/删空);③ 悬浮手牌按 D 立即换牌。

---

## 架构

两层各加:
- **Hud.cs(C# 注入层,Hud31→Hud32)**:新增一个 `Observable.EveryUpdate` 订阅做**逐帧输入**(Tab/D 键;现有 0.5s `OnTick` 不动,因 `GetKeyDown` 会被 0.5s 间隔漏掉)。新增卡池 overlay 绘制 + D 换牌。给 `SetPos` 加 `skip` key,新增 `SetPool` RPC。
- **Python(hud_launcher.py / hud_gui.py)**:设置面板加位置输入框(推 `SetPos`)+ 位置持久化;消费线程把 `counter.remaining()` 映射成 `card_id:剩数` 推 `SetPool`。

沿用既有:Hud 迭代改名法(Hud31→Hud32,csproj `YiXianHud32`,launcher `HUD_T`/`HUD_DLL`/`OLD_HUDS` 同步)、`call_str` RPC、`YiXianHUD_config.json` 配置文件、name→card_id 映射(见下)。

---

## Feature 1:位置可调(屏锚元素 + 跳过按钮)

**Hud.cs:**
- 现有 `SetPos("total|warn|opp,x,y")` 已覆盖造伤/警告/对手。**加 `skip` key**:新增字段 `static Vector2 s_skipPos = new Vector2(-30f, -210f);`,`SetPos` 分支加 `else if (p[0]=="skip") s_skipPos = v;`,`DrawSkipButton` 里 `rt.anchoredPosition = s_skipPos;`(替换写死的 `(-30,-210)`)。

**hud_gui.py:**
- 新增「位置」分区,每个可调元素一行:标签 + X 输入框 + Y 输入框。元素:`total`(造伤 T1-T8)、`warn`(危险牌警告)、`opp`(对手命修)、`skip`(跳过战斗按钮)。
- 任一框改动 → `on_pos(key, x, y)` 回调 → 推 `SetPos("key,x,y")`(经 launcher 暴露的回调,见下)。
- 默认值取自 `YiXianHUD_config.json` 的 `positions` 段(无则用 Hud 内置默认)。

**hud_launcher.py:**
- `run_gui` 多传一个 `on_pos` 回调:`ex.call_str(HUD_T, "SetPos", "%s,%d,%d" % (key, x, y))` + 写回 `YiXianHUD_config.json` 的 `positions[key]`。
- 启动时读 config 的 positions,逐个 `SetPos` 推一遍(恢复上次位置)。

---

## Feature 2:Tab 卡池 overlay(游戏内,全卡池网格 + 卡图)

**数据流(Python→HUD):**
- launcher 消费线程已有 `counter.remaining()`(按牌名→剩数)。新增:把每个牌名经 **name→card_id 映射**(复用 `proxy_view`/`cards_from_bundle.json` 的 card_id_map,plan 定位确切来源)转成 card_id,推 `SetPool("id:剩数|id:剩数|...")`(含剩 0 的删空牌)。每轮更新。
- 卡池 = counter 已知的全部牌型(玩家本局牌库),含满数没动的。

**Hud.cs:**
- `SetPool(string data)`:解析成 `Dictionary<int,int>`(id→剩数)存 `s_pool`。
- 逐帧 `Input.GetKeyDown(KeyCode.Tab)` → 切换 `s_poolVisible`。
- overlay = 一个全屏半透明 Panel(Image,黑 0.6 alpha,raycastTarget 挡操作)+ 卡片网格(GridLayoutGroup 或手动布局):每张牌一格 = `Image`(卡图)+ 角标 `剩X`。
  - 卡图:`AsyncLoadExtensions.LoadSprite(img, AssetNameUtil.GetCardSpriteName(id, 0), null, false, default)`;sprite 缓存(已加载的 id 不重复请求)。
  - **剩 3 张:角标/边框标黄;删空(剩 0):整格置灰(alpha 降低)**;其余正常。
- overlay 挂在顶层 Canvas(同 DrawSkipButton 找 Canvas 的方式),按数量分行布局。

**性能:** 网格只在 `s_poolVisible` 切到显示时(或 pool 变化时)重建;隐藏时 SetActive(false) 不销毁。

---

## Feature 3:悬浮手牌 + D 立即换牌

**Hud.cs:**
- 逐帧 `Input.GetKeyDown(KeyCode.D)` → 找鼠标下的手牌:`EventSystem.current.RaycastAll(pointerEventData(鼠标位置), results)`,遍历命中的 GameObject,向上找带 `CardItem` 的(`GetComponentInParent<CardItem>` 等价的非泛型写法),确认是手牌(`cardInfo.position == CardPosition.Hand`)。
- 命中手牌 → `cp.replaceArea.ReplaceCard(thatCard, null)`(`cp` = 现成的 `FindILRPanel<BattlePanel>().FindILRSubPanel<CardPanel>()`;`ReplaceArea.ReplaceCard(card, null)` = game-api 验证过的真·UI 换牌,客户端自己发包+播动画)。
- 无确认(用户选悬浮即换)。非手牌/无命中 → 无操作。

> 不依赖 YiXianApi.dll —— ReplaceArea/ReplaceCard/CardPanel 在 Hud.csproj 引用的 DarkSun.HotUpdate 里(同 game-api),直接调。

---

## 测试

- Hud32 编译通过 + 注入加载(`Show -> subscribed`)。
- F1:设置面板拖 X/Y → 对应元素/按钮实时移动;重启后位置恢复(config)。
- F2:Tab 弹出卡池网格,卡图正确、剩数对、3 张标黄、删空置灰;再按 Tab 收起。
- F3:悬浮某手牌按 D → 该牌被换掉(画面真换牌动画)。
- 活体实测(spawn 游戏)。

## 成功标准

- [ ] 四个屏锚元素 + 跳过按钮位置都能在设置面板调,且持久化。
- [ ] Tab 卡池 overlay 显示全卡池(卡图+剩数),3 张/删空有视觉区分。
- [ ] 悬浮手牌按 D 立即换掉该牌。

## 非目标(YAGNI)

- 每卡「剩X」角标的逐卡偏移调节(本轮不做,只调屏锚元素+跳过按钮)。
- 卡池 overlay 的排序/筛选/搜索(先做基础网格)。
- D 换牌的确认弹窗(用户要即换)。
- 对手卡池(只做自己的)。
