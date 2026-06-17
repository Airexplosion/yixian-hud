# YiXianHUD 三新功能实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:subagent-driven-development(推荐)或 executing-plans。逐任务,checkbox 跟踪。

**Goal:** 给 YiXianHUD 加:① 注入文字/按钮位置在设置面板可调并持久化;② Tab 弹游戏内卡池 overlay(全卡池+卡图+剩数,标黄/置灰);③ 悬浮手牌按 D 立即换牌。

**Architecture:** Hud.cs(C# 注入层)Hud31→Hud32:新增 `Observable.EveryUpdate` 逐帧输入(Tab/D)+ 卡池 overlay + D 换牌 + SetPos 加 skip + SetPool。Python:hud_gui 加位置框、launcher 持久化位置 + 推 SetPool。

**Tech Stack:** C# net40 + ILRuntime(dotnet build,_refs 含 DarkSun.HotUpdate:ReplaceArea/CardPanel/AssetNameUtil/AsyncLoadExtensions);bot_glue3 call_str RPC;Python 3 + pytest;`proxy/card_id_map.json`(id→name);`YiXianHUD_config.json`。

**关键约定:**
- **Hud31→Hud32 一次性改名**(类 `Hud32`、csproj `<AssemblyName>YiXianHud32`、hud_launcher `HUD_DLL=YiXianHud32.dll`/`HUD_T="YiXianBot.Hud32"`/`OLD_HUDS` 前插 `"Hud31"`)。整个 hud-features 用 Hud32;每个 F 的实测靠 launcher **spawn 全新游戏**(kill+respawn)首次加载,无 ILRuntime 去重问题。
- 游戏类型(`Input`/`KeyCode`/`EventSystem`/`PointerEventData`/`GraphicRaycaster`/`AssetNameUtil`/`AsyncLoadExtensions`/`ReplaceArea`/`CardPanel`/`CardItem`/`CardPosition`)在 _refs 引用的程序集,`namespace YiXianBot` 直接用(同现有 Hud.cs)。`EventSystem`/`PointerEventData` 需 `using UnityEngine.EventSystems;`。
- C# 每改一次:`dotnet build native_hud/csharp/Hud.csproj -c Release -v q -nologo` → `0 个错误` → `cp` 到 `native_hud/_build/YiXianHud32.dll`。

---

## 文件结构

| 文件 | 改动 |
|---|---|
| `native_hud/csharp/Hud.cs` | Hud31→Hud32;SetPos 加 skip;EveryUpdate 输入;SetPool + 卡池 overlay;D 换牌 |
| `native_hud/csharp/Hud.csproj` | AssemblyName YiXianHud32;加 `using UnityEngine.EventSystems` 所需引用(UnityEngine.UI 已含 EventSystems) |
| `native_hud/bridge/hud_launcher.py` | HUD_T/HUD_DLL/OLD_HUDS;位置持久化+恢复;消费线程推 SetPool;`run_gui` 传 `on_pos` |
| `native_hud/bridge/hud_gui.py` | 位置输入框分区 + on_pos 回调 |
| `native_hud/bridge/pool_payload.py` | 新:`pool_payload(remaining, name_to_id)` 构建 SetPool 串(可单测) |
| `native_hud/tests/test_pool_payload.py` | 新:pool_payload 单测 |

---

## Task 1: Hud31→Hud32 改名 + SetPos 加 skip

**Files:** Modify `native_hud/csharp/Hud.cs`、`native_hud/csharp/Hud.csproj`、`native_hud/bridge/hud_launcher.py`。

- [ ] **Step 1: 改名**
```bash
cd "C:/Users/zd117/Desktop/yxp辅助/yixian-counter-main"
sed -i 's/public static class Hud31/public static class Hud32/' native_hud/csharp/Hud.cs
sed -i 's/YiXianHud31/YiXianHud32/' native_hud/csharp/Hud.csproj
sed -i 's/YiXianHud31/YiXianHud32/; s/YiXianBot.Hud31/YiXianBot.Hud32/; s/OLD_HUDS = \["Hud30"/OLD_HUDS = ["Hud31", "Hud30"/' native_hud/bridge/hud_launcher.py
```

- [ ] **Step 2: SetPos 加 skip key**
在 Hud.cs 加字段(在 `s_oppPos` 那组后):
```csharp
        static Vector2 s_skipPos = new Vector2(-30f, -210f);   // 跳过战斗按钮(右上)
```
在 `SetPos` 的分支链里(`else if (p[0] == "opp") ...` 后)加:
```csharp
                else if (p[0] == "skip") s_skipPos = v;
```
`DrawSkipButton` 里把写死的 `rt.anchoredPosition = new Vector2(-30f, -210f);` 改成 `rt.anchoredPosition = s_skipPos;`。

- [ ] **Step 3: 编译 + 拷贝**
```bash
dotnet build native_hud/csharp/Hud.csproj -c Release -v q -nologo
cp native_hud/csharp/bin/Release/net40/YiXianHud32.dll native_hud/_build/YiXianHud32.dll
```
Expected: `0 个错误`。

- [ ] **Step 4: 同步 .gitignore 追踪的 DLL**
`native_hud/.gitignore` 把 `!_build/YiXianHud31.dll` 改 `!_build/YiXianHud32.dll`:
```bash
sed -i 's#!_build/YiXianHud31.dll#!_build/YiXianHud32.dll#' native_hud/.gitignore
git rm --cached native_hud/_build/YiXianHud31.dll -q 2>/dev/null || true
git add -f native_hud/_build/YiXianHud32.dll
```

- [ ] **Step 5: 提交**
```bash
git add native_hud/csharp/Hud.cs native_hud/csharp/Hud.csproj native_hud/bridge/hud_launcher.py native_hud/.gitignore
git commit -m "feat(hud): Hud32 + SetPos 加 skip(跳过按钮位置可调)"
```

---

## Task 2: 设置面板位置框 + 持久化/恢复

**Files:** Modify `native_hud/bridge/hud_gui.py`、`native_hud/bridge/hud_launcher.py`。

- [ ] **Step 1: hud_gui.py 加位置分区**
在 `run_gui` 的伤害模式分隔符后、状态行前,插入位置控件。`run_gui` 签名加 `pos_get=None, on_pos=None`:
```python
    POS_ELEMENTS = [("total", "造伤 T1–T8"), ("warn", "危险牌警告"),
                    ("opp", "对手 命/修"), ("skip", "跳过战斗按钮")]
    ttk.Separator(frm).pack(fill="x", pady=8)
    ttk.Label(frm, text="位置 (X, Y)", font=("", 10, "bold")).pack(anchor="w")
    for key, text in POS_ELEMENTS:
        row = ttk.Frame(frm); row.pack(fill="x", pady=1)
        ttk.Label(row, text=text, width=12).pack(side="left")
        cx, cy = (pos_get(key) if pos_get else (0, 0))
        ex = ttk.Entry(row, width=6); ex.insert(0, str(int(cx))); ex.pack(side="left")
        ey = ttk.Entry(row, width=6); ey.insert(0, str(int(cy))); ey.pack(side="left", padx=(4, 0))

        def _push(k=key, exx=ex, eyy=ey):
            try:
                x, y = int(exx.get().strip()), int(eyy.get().strip())
            except ValueError:
                return
            if on_pos:
                on_pos(k, x, y)
        ttk.Button(row, text="应用", width=5, command=_push).pack(side="left", padx=4)
```

- [ ] **Step 2: hud_launcher.py — 位置默认值 + 回调 + 启动恢复**
在 `hud_launcher.py` 顶部加内置默认(与 Hud.cs 一致):
```python
DEFAULT_POS = {"total": (0, -182), "warn": (0, -222), "opp": (70, -240), "skip": (-30, -210)}
```
加两个函数:
```python
def _positions():
    cfg = _load_cfg()
    p = dict(DEFAULT_POS)
    for k, v in (cfg.get("positions") or {}).items():
        if isinstance(v, (list, tuple)) and len(v) == 2:
            p[k] = (int(v[0]), int(v[1]))
    return p


def _pos_get(key):
    return _positions().get(key, (0, 0))


def _make_on_pos(ex):
    def on_pos(key, x, y):
        try:
            ex.call_str(HUD_T, "SetPos", "%s,%d,%d" % (key, x, y))
        except Exception:
            pass
        cfg = _load_cfg()
        cfg.setdefault("positions", {})[key] = [x, y]
        _save_cfg(cfg)
    return on_pos
```
在 hud_loader 成功 subscribe 后(`_hud_ready.set()` 附近),启动恢复:逐个把已存位置 SetPos 推一遍:
```python
        for k, (x, y) in _positions().items():
            try:
                ex.call_str(HUD_T, "SetPos", "%s,%d,%d" % (k, x, y))
            except Exception:
                pass
```
`main()` 里 `run_gui(...)` 调用加 `pos_get=_pos_get, on_pos=_make_on_pos(_hud_ex["ex"])`(确保在 ex 就绪后调;若 run_gui 在 ready 前启动,用 lambda 延迟取 `_hud_ex["ex"]`)。

- [ ] **Step 3: 实测(spawn)** — 见 Task 6 的 F1 部分(本步先确保启动不报错:`python native_hud/bridge/hud_launcher.py` 能起、设置窗有"位置"分区)。

- [ ] **Step 4: 提交**
```bash
git add native_hud/bridge/hud_gui.py native_hud/bridge/hud_launcher.py
git commit -m "feat(hud): 设置面板位置框 + 位置持久化/恢复"
```

---

## Task 3: Hud.cs 逐帧输入 + Tab 卡池 overlay

**Files:** Modify `native_hud/csharp/Hud.cs`(+ csproj 若缺 EventSystems)。

- [ ] **Step 1: 顶部加 using**
Hud.cs usings 加 `using UnityEngine.EventSystems;`(EventSystems 在 UnityEngine.UI 程序集,已引用)。

- [ ] **Step 2: 字段 + 逐帧输入订阅**
加字段:
```csharp
        static IDisposable s_inputSub;            // 逐帧输入(Tab/D)
        static Dictionary<int, int> s_pool = new Dictionary<int, int>();   // card_id -> 剩数
        static GameObject s_poolGo;               // 卡池 overlay 根
        static bool s_poolVisible = false;
        static bool s_poolDirty = true;
```
在 `Show()` 里 `s_sub` 订阅之后,加逐帧订阅:
```csharp
                if (s_inputSub == null)
                    s_inputSub = ObservableExtensions.Subscribe(Observable.EveryUpdate(), new Action<long>(OnInput));
```
`Hide()` 里释放:`if (s_inputSub != null) { s_inputSub.Dispose(); s_inputSub = null; }` 并销毁 s_poolGo。

- [ ] **Step 3: SetPool RPC**
```csharp
        public static string SetPool(string data)   // "id:剩|id:剩"
        {
            try {
                var d = new Dictionary<int, int>();
                if (!string.IsNullOrEmpty(data))
                    foreach (var part in data.Split('|'))
                    { var kv = part.Split(':'); int id, c; if (kv.Length == 2 && int.TryParse(kv[0], out id) && int.TryParse(kv[1], out c)) d[id] = c; }
                s_pool = d; s_poolDirty = true; return "ok:" + d.Count;
            } catch (Exception e) { return "EX:" + e.Message; }
        }
```

- [ ] **Step 4: OnInput(逐帧)— Tab 切卡池**
```csharp
        static void OnInput(long _)
        {
            try {
                if (Input.GetKeyDown(KeyCode.Tab))
                {
                    s_poolVisible = !s_poolVisible;
                    if (s_poolVisible) ShowPool(); else if (s_poolGo != null) s_poolGo.SetActive(false);
                }
                // D 换牌见 Task 5
            } catch (Exception) { }
        }
```

- [ ] **Step 5: ShowPool — 全屏面板 + 卡图网格**
```csharp
        static Dictionary<int, Image> s_poolCells = new Dictionary<int, Image>();
        static void ShowPool()
        {
            try {
                if (s_poolGo == null || s_poolDirty)
                {
                    if (s_poolGo != null) { UnityEngine.Object.Destroy(s_poolGo); s_poolGo = null; s_poolCells.Clear(); }
                    Canvas canv = null;
                    foreach (var o in UnityEngine.Object.FindObjectsOfType(typeof(Canvas)))
                    { var c = o as Canvas; if (c != null) { canv = c; if (c.transform.parent == null) break; } }
                    if (canv == null) return;
                    s_poolGo = new GameObject("BotPool");
                    s_poolGo.transform.SetParent(canv.transform, false);
                    var prt = s_poolGo.AddComponent(typeof(RectTransform)) as RectTransform;
                    prt.anchorMin = Vector2.zero; prt.anchorMax = Vector2.one; prt.offsetMin = Vector2.zero; prt.offsetMax = Vector2.zero;
                    var bg = s_poolGo.AddComponent(typeof(Image)) as Image;
                    bg.color = new Color(0f, 0f, 0f, 0.6f); bg.raycastTarget = true;
                    // 网格:每行 N 张,卡 110x150,间距 12
                    int n = 0, perRow = 10; float cw = 110f, ch = 150f, gap = 12f;
                    float startX = -((perRow - 1) * (cw + gap)) / 2f, startY = 280f;
                    foreach (var kv in s_pool)
                    {
                        int id = kv.Key, rem = kv.Value;
                        int row = n / perRow, col = n % perRow; n++;
                        var cell = new GameObject("c" + id); cell.transform.SetParent(s_poolGo.transform, false);
                        var crt = cell.AddComponent(typeof(RectTransform)) as RectTransform;
                        crt.sizeDelta = new Vector2(cw, ch);
                        crt.anchoredPosition = new Vector2(startX + col * (cw + gap), startY - row * (ch + gap));
                        var img = cell.AddComponent(typeof(Image)) as Image;
                        img.raycastTarget = false;
                        img.color = (rem <= 0) ? new Color(0.4f, 0.4f, 0.4f, 0.5f) : Color.white;   // 删空置灰
                        AsyncLoadExtensions.LoadSprite(img, AssetNameUtil.GetCardSpriteName(id, 0), (string)null, false, default(System.Threading.CancellationToken));
                        // 剩X 角标
                        var tgo = new GameObject("n"); tgo.transform.SetParent(cell.transform, false);
                        var lbl = tgo.AddComponent(typeof(TextMeshProUGUI)) as TextMeshProUGUI;
                        var f = FindFont(); if (f != null) lbl.font = f;
                        lbl.fontSize = 30f; lbl.alignment = TextAlignmentOptions.BottomRight; lbl.raycastTarget = false;
                        lbl.color = (rem == 3) ? new Color(1f, 0.9f, 0.2f, 1f) : Color.white;        // 剩3标黄
                        lbl.text = rem.ToString();
                        var lrt = lbl.rectTransform; lrt.anchorMin = Vector2.zero; lrt.anchorMax = Vector2.one; lrt.offsetMin = new Vector2(0, 0); lrt.offsetMax = new Vector2(-4, 0);
                    }
                    s_poolDirty = false;
                }
                s_poolGo.SetActive(true);
            } catch (Exception) { }
        }
```

- [ ] **Step 6: 编译 + 拷贝**
```bash
dotnet build native_hud/csharp/Hud.csproj -c Release -v q -nologo
cp native_hud/csharp/bin/Release/net40/YiXianHud32.dll native_hud/_build/YiXianHud32.dll
```
Expected: `0 个错误`。若 `AsyncLoadExtensions`/`AssetNameUtil`/`EventSystems` 不解析,grep `/tmp/decomp` 核命名空间(`AssetNameUtil.GetCardSpriteName(int,int=0,string=null)` 在 410664;`LoadSprite(Image,string,string,bool,CancellationToken)`),必要时加 using/引用。

- [ ] **Step 7: 提交**
```bash
git add native_hud/csharp/Hud.cs native_hud/csharp/Hud.csproj
git commit -m "feat(hud): 逐帧输入 + Tab 卡池 overlay(卡图网格+剩数,3张标黄/删空置灰)"
```

---

## Task 4: launcher 推 SetPool(name→card_id)

**Files:** Create `native_hud/bridge/pool_payload.py`、`native_hud/tests/test_pool_payload.py`;Modify `native_hud/bridge/hud_launcher.py`。

- [ ] **Step 1: 写失败测试** `native_hud/tests/test_pool_payload.py`:
```python
from native_hud.bridge.pool_payload import pool_payload


def test_maps_names_to_ids_and_keeps_zeros():
    remaining = {"普通攻击": 3, "云泉道茶": 0, "未知牌": 2}
    name_to_id = {"普通攻击": 0, "云泉道茶": 1}
    out = pool_payload(remaining, name_to_id)
    parts = dict(p.split(":") for p in out.split("|") if p)
    assert parts == {"0": "3", "1": "0"}   # 未知牌无 id → 丢弃;0 保留(删空)


def test_empty():
    assert pool_payload({}, {"a": 1}) == ""
```
(注:`native_hud/bridge/__init__.py` 需存在使其可导入;若无则本任务创建,内容 `# package marker`。)

- [ ] **Step 2: 运行确认失败**
Run: `python -m pytest native_hud/tests/test_pool_payload.py -q`
Expected: FAIL(ModuleNotFoundError)。

- [ ] **Step 3: 写 pool_payload.py**
`native_hud/bridge/pool_payload.py`:
```python
# -*- coding: utf-8 -*-
"""把 counter.remaining()(牌名→剩数)映射成 Hud.SetPool 的 'id:剩|id:剩' 串。
牌名查不到 card_id 的丢弃;剩 0(删空)保留以便 overlay 置灰。"""


def pool_payload(remaining, name_to_id):
    parts = []
    for name, cnt in remaining.items():
        cid = name_to_id.get(name)
        if cid is None:
            continue
        parts.append("%d:%d" % (int(cid), int(cnt)))
    return "|".join(parts)
```
若缺 `native_hud/bridge/__init__.py` / `native_hud/tests/__init__.py`,创建(`# package marker`)。

- [ ] **Step 4: 运行确认通过**
Run: `python -m pytest native_hud/tests/test_pool_payload.py -q`
Expected: PASS(2 passed)。

- [ ] **Step 5: hud_launcher.py 加载 name→id + 消费线程推 SetPool**
顶部加载反转的 card_id_map:
```python
def _load_name_to_id():
    try:
        import json
        m = json.loads((REPO / "proxy" / "card_id_map.json").read_text(encoding="utf-8"))
        return {v: int(k) for k, v in m.items()}   # id→name 反转成 name→id
    except Exception:
        return {}

NAME_TO_ID = _load_name_to_id()
```
在消费线程**已计算 remaining 的地方**(推 SetRemaining 附近),加推 SetPool:
```python
                from pool_payload import pool_payload
                ex.call_str(HUD_T, "SetPool", pool_payload(rem, NAME_TO_ID))
```
(`rem` = 该处已有的 `counter.remaining()` 结果 dict;若变量名不同,用实际的剩余 dict。)

- [ ] **Step 6: 提交**
```bash
git add native_hud/bridge/pool_payload.py native_hud/tests/test_pool_payload.py native_hud/bridge/__init__.py native_hud/tests/__init__.py hud_launcher.py 2>/dev/null; git add native_hud/bridge/hud_launcher.py
git commit -m "feat(hud): launcher 推 SetPool(name→card_id)+ pool_payload 单测"
```

---

## Task 5: 悬浮 + D 立即换牌

**Files:** Modify `native_hud/csharp/Hud.cs`(在 `OnInput` 里加 D 分支 + 辅助)。

- [ ] **Step 1: OnInput 加 D 分支**
在 `OnInput` 的 Tab 处理后加:
```csharp
                if (Input.GetKeyDown(KeyCode.D))
                {
                    var card = HandCardUnderMouse();
                    if (card != null)
                    {
                        var bp = ILRPanelBase.FindILRPanel<BattlePanel>();
                        var cp = bp != null ? bp.FindILRSubPanel<CardPanel>() : null;
                        if (cp != null && cp.replaceArea != null) cp.replaceArea.ReplaceCard(card, null);
                    }
                }
```

- [ ] **Step 2: HandCardUnderMouse — 射线找鼠标下的手牌**
```csharp
        static CardItem HandCardUnderMouse()
        {
            try {
                if (EventSystem.current == null) return null;
                var ped = new PointerEventData(EventSystem.current);
                ped.position = Input.mousePosition;
                var results = new List<RaycastResult>();
                EventSystem.current.RaycastAll(ped, results);
                for (int i = 0; i < results.Count; i++)
                {
                    var go = results[i].gameObject;
                    var ci = go != null ? go.GetComponentInParent(typeof(CardItem)) as CardItem : null;
                    if (ci != null && ci.cardInfo != null && ci.cardInfo.position == CardPosition.Hand)
                        return ci;
                }
            } catch (Exception) { }
            return null;
        }
```
> `RaycastResult`/`List` 需 `using UnityEngine.EventSystems;`(Task 3 已加)+ `System.Collections.Generic`(已有)。`GetComponentInParent(typeof(CardItem))` 非泛型写法避 ILRuntime 泛型坑。

- [ ] **Step 3: 编译 + 拷贝**
```bash
dotnet build native_hud/csharp/Hud.csproj -c Release -v q -nologo
cp native_hud/csharp/bin/Release/net40/YiXianHud32.dll native_hud/_build/YiXianHud32.dll
```
Expected: `0 个错误`。若 `GetComponentInParent`/`RaycastResult`/`ReplaceCard` 不解析,grep `/tmp/decomp` 核(`ReplaceArea.ReplaceCard(CardItem, ReplaceCardResp=null)` 在 229680;`CardPanel.replaceArea` public 属性)。

- [ ] **Step 4: 提交**
```bash
git add native_hud/csharp/Hud.cs native_hud/_build/YiXianHud32.dll
git commit -m "feat(hud): 悬浮手牌按 D 立即换牌(射线找CardItem + ReplaceArea.ReplaceCard)"
```

---

## Task 6: 活体实测(spawn 游戏,逐功能验证)

**Files:** 无新文件;运行 launcher + 实操。

- [ ] **Step 1: 起 launcher(spawn 新游戏,Hud32)**
Run: `python native_hud/bridge/hud_launcher.py`(spawn 模式)。等 `[hud] Show -> ok:subscribed`。登录进对局。

- [ ] **Step 2: F1 — 位置可调**
设置窗"位置"分区,改 `skip` 的 X/Y 点"应用" → 战斗时"跳过战斗"按钮移动。改 total/warn/opp 同理。关 launcher 重启 → 位置应恢复(config 持久化)。

- [ ] **Step 3: F2 — Tab 卡池**
对局中按 **Tab** → 弹出卡池网格:卡图正确、每张剩数对、剩 3 张的标黄、删空(0)的置灰半透明。再按 Tab 收起。

- [ ] **Step 4: F3 — D 换牌**
摆牌阶段,鼠标悬浮某手牌,按 **D** → 该牌被换掉(真换牌动画)。

- [ ] **Step 5: 处理问题**
任一 FAIL:按报错/现象回对应 Task 修(C# grep `/tmp/decomp` 核 API;Python 核 remaining 变量名/card_id_map)。全过则完成。

---

## Self-Review 覆盖

- spec §F1 位置可调 → Task 1(skip key)+ Task 2(设置框+持久化)✓
- spec §F2 Tab卡池overlay → Task 3(逐帧输入+SetPool+网格+卡图+标黄置灰)+ Task 4(launcher 推数据)✓
- spec §F3 悬浮D换牌 → Task 5 ✓
- spec §测试/成功标准 → Task 6 ✓
- Hud 迭代改名 → Task 1 ✓;EveryUpdate 逐帧输入 → Task 3 ✓
- 类型一致:`s_skipPos`/`s_pool`/`s_poolGo`/`s_inputSub`/`SetPool`/`OnInput`/`ShowPool`/`HandCardUnderMouse`/`pool_payload(remaining,name_to_id)` 全程一致;HUD_T=`YiXianBot.Hud32`/HUD_DLL=`YiXianHud32.dll` 一致。
- 已知风险:消费线程里 `rem` 的实际变量名(Task 4 Step5 按实际改)、`GetComponentInParent`/`AsyncLoadExtensions` 的 ILRuntime 可用性(Task 3/5 编译期 grep 兜底,Task 6 实测裁决)。
