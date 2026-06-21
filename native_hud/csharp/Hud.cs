using System;
using System.Collections.Generic;
using UnityEngine;
using UnityEngine.UI;
using UnityEngine.Events;
using TMPro;
using UniRx;
using Proto;

namespace YiXianBot
{
    // Per-card overlay, no top panel:
    //  · board card top:  "配置攻击(边际贡献)"  e.g. 12(42)  — config from bot, marginal pushed (yisim).
    //  · every card top-right: 剩X (counter.remaining() by NAME).
    // 8-layer manual outline (font-agnostic). Parented to movableRT (scales on hover).
    public static class Hud32
    {
        const string DMG = "BotDmg";
        const string LEFT = "BotLeft";
        static readonly Vector2[] OFF = {
            new Vector2(2,0), new Vector2(-2,0), new Vector2(0,2), new Vector2(0,-2),
            new Vector2(2,2), new Vector2(-2,2), new Vector2(2,-2), new Vector2(-2,-2)
        };
        static IDisposable s_sub;
        static IDisposable s_fast;   // 0.05s 主线程泵:执行 Tab/D 待办(RPC 跑在注入线程,Unity 操作必须回主线程)
        static bool s_pendingToggle = false;   // Tab 按下 → 主线程泵切换卡池
        static bool s_pendingSwap = false;     // D 按下 → 主线程泵换悬浮手牌
        static CardItem s_lastHovered = null;  // 主线程每帧记录的悬浮手牌(按 D 时用它,防"按D后移开就丢")
        static int s_noCard = 0;     // consecutive ticks with no visible card (battle debounce)
        static TMP_FontAsset s_font;
        static Dictionary<string, int> s_remaining = new Dictionary<string, int>();   // by card name
        static bool s_showLeft = true;   // 记牌器 剩X toggle
        static Dictionary<int, int> s_marginal = new Dictionary<int, int>();           // by board slot index
        static float s_dmgY = -2f;   // damage label Y (on the card top, below the prepare bar)
        static string s_total = "";  // 造伤表格:行用 \n 分隔,单元格用 \t 分隔(screen-anchored)
        static GameObject s_totalGo;
        // 造伤改用"每格独立定位"的网格渲染:游戏字体比例字 + TMP 不认 <mspace>/<pos>,纯文本
        // 无法对齐 → 每个单元格是独立 TMP(9 层描边),钉在固定列像素 x 上,逐列严格对齐。
        static List<List<TextMeshProUGUI>> s_totalCells;   // 扁平 r*ncol+c → 该格的 9 层
        static int s_totalRows = -1, s_totalCols = -1;     // 缓存网格维度,仅维度变化时重建
        const float TT_COLW = 60f;    // 列宽 px
        const float TT_LINEH = 30f;   // 行高 px
        const float TT_FS = 24f;      // 造伤字号
        static string s_opp = "";    // opponent HP cap + 修为 (top-left, by 生命上限)
        static GameObject s_oppGo;
        static List<TextMeshProUGUI> s_oppLayers;
        static string s_warn = "";   // danger-card warning (flashes)
        static GameObject s_warnGo;
        static List<TextMeshProUGUI> s_warnLayers;
        static GameObject s_skipBtnGo;   // in-battle 跳过 button
        static bool s_skipPending;        // true after click → waiting for executers to settle
        static bool s_forceDaoyun;        // 跳过吞了该出道韵的回合 → 进摆牌后强拉一次道韵选择面板
        // Anchored positions (runtime-tunable via SetPos so we needn't recompile).
        static Vector2 s_totalPos = new Vector2(0f, -182f);   // T1..T8 (top-center)
        static Vector2 s_warnPos = new Vector2(0f, -222f);    // danger warning
        static Vector2 s_oppPos = new Vector2(70f, -240f);    // opponent 命/修 (top-left)
        static Vector2 s_skipPos = new Vector2(-80f, -380f);   // 跳过战斗按钮(右上;默认下移约4行、左移约1.5字)
        static bool s_showSkip = true;   // 跳过战斗按钮 显示开关(设置面板可关)
        static readonly Color s_black = new Color(0f, 0f, 0f, 1f);
        static Dictionary<int, int> s_pool = new Dictionary<int, int>();   // card_id -> 剩数
        static GameObject s_poolGo;               // 卡池 overlay 根
        static bool s_poolVisible = false;
        static bool s_poolDirty = true;
        static Dictionary<int, Image> s_poolCells = new Dictionary<int, Image>();
        static bool s_poolPrewarmed = false;      // IllustrationCardItem.InitPrefabPool 只触发一次
        static string s_poolErr = "";             // 卡池渲染异常,显示在 overlay 顶部便于排错
        static int s_poolMode = 0;                // 置顶模式:0=手牌 1=已空(剩0) 2=危险(剩≤3)
        static bool s_poolRebuild = false;        // 三按钮切换后请求重建 overlay(主线程泵执行)
        const int POOL_ABUNDANT = 3;              // 剩≥此值算"充足"(放下面);剩1..2算"快空"(放上面)
        const float POOL_CARD_SCALE = 0.62f;      // 原生卡面缩放(适配网格格子,实测可调)
        const int PILE_FULL = 999;                // 没见过(满数未动)的排序标记 → 充足组、放最下,显示"满"

        public static string Show()
        {
            try {
                if (s_sub != null) return "ok:already";
                s_sub = ObservableExtensions.Subscribe(
                    Observable.Interval(TimeSpan.FromSeconds(0.5), Scheduler.MainThreadIgnoreTimeScale),
                    new Action<long>(OnTick));
                // 高频泵:把热键(Tab/D)的 Unity 操作搬到主线程执行,~16ms(约每帧)响应,跟手。
                // 只在标志置位时才碰 Unity,空转仅查两个 bool,开销可忽略。
                s_fast = ObservableExtensions.Subscribe(
                    Observable.Interval(TimeSpan.FromSeconds(0.016), Scheduler.MainThreadIgnoreTimeScale),
                    new Action<long>(PumpActions));
                return "ok:subscribed";
            } catch (Exception e) { return "EX:" + e.Message; }
        }
        public static string Hide()
        {
            try {
                if (s_sub != null) { s_sub.Dispose(); s_sub = null; }
                if (s_fast != null) { s_fast.Dispose(); s_fast = null; }
                if (s_poolGo != null) { UnityEngine.Object.Destroy(s_poolGo); s_poolGo = null; s_poolCells.Clear(); }
                foreach (var o in UnityEngine.Object.FindObjectsOfType(typeof(GameObject)))
                {
                    var g = o as GameObject;
                    if (g != null && (g.name == DMG || g.name == LEFT || g.name == "BotTotal"
                        || g.name == "BotOpp" || g.name == "BotWarn")) UnityEngine.Object.Destroy(g);
                }
                s_totalGo = null; s_totalCells = null; s_totalRows = -1; s_totalCols = -1;
                s_oppGo = null; s_oppLayers = null; s_warnGo = null; s_warnLayers = null;
                return "ok:hidden";
            } catch (Exception e) { return "EX:" + e.Message; }
        }
        public static string SetRemaining(string data)   // "卡名:剩数|卡名:剩数"
        {
            try {
                var d = new Dictionary<string, int>();
                if (!string.IsNullOrEmpty(data))
                    foreach (var part in data.Split('|'))
                    { int idx = part.LastIndexOf(':'); if (idx > 0) { int c; if (int.TryParse(part.Substring(idx + 1), out c)) d[part.Substring(0, idx)] = c; } }
                s_remaining = d; return "ok:" + d.Count;
            } catch (Exception e) { return "EX:" + e.Message; }
        }
        public static string SetDmgY(string y) { float v; if (float.TryParse(y, out v)) s_dmgY = v; return "ok:" + s_dmgY; }
        public static string SetTotal(string s) { s_total = s ?? ""; return "ok:" + s_total; }
        public static string SetOpponent(string s) { s_opp = s ?? ""; return "ok:" + s_opp; }
        public static string SetShowLeft(string v) { s_showLeft = (v == "1" || v == "true"); return "ok:" + s_showLeft; }
        public static string SetShowSkip(string v) { s_showSkip = (v == "1" || v == "true"); return "ok:" + s_showSkip; }
        public static string SetWarning(string s) { s_warn = s ?? ""; return "ok:" + s_warn; }
        // Runtime position tuning: SetPos("total,0,-132") / "warn,..." / "opp,...".
        public static string SetPos(string data)
        {
            try {
                var p = (data ?? "").Split(',');
                if (p.Length != 3) return "bad";
                float fx, fy;
                if (!float.TryParse(p[1], out fx) || !float.TryParse(p[2], out fy)) return "badnum";
                var v = new Vector2(fx, fy);
                if (p[0] == "total") s_totalPos = v;
                else if (p[0] == "warn") s_warnPos = v;
                else if (p[0] == "opp") s_oppPos = v;
                else if (p[0] == "skip") s_skipPos = v;
                else return "no:" + p[0];
                return "ok:" + p[0] + " " + fx + "," + fy;
            } catch (Exception e) { return "EX:" + e.Message; }
        }
        public static string SetMarginal(string data)     // "slot:值|slot:值"
        {
            try {
                var d = new Dictionary<int, int>();
                if (!string.IsNullOrEmpty(data))
                    foreach (var part in data.Split('|'))
                    { var kv = part.Split(':'); int s, v; if (kv.Length == 2 && int.TryParse(kv[0], out s) && int.TryParse(kv[1], out v)) d[s] = v; }
                s_marginal = d; return "ok:" + d.Count;
            } catch (Exception e) { return "EX:" + e.Message; }
        }
        public static string SetPool(string data)   // "id:剩|id:剩"
        {
            try {
                var d = new Dictionary<int, int>();
                if (!string.IsNullOrEmpty(data))
                    foreach (var part in data.Split('|'))
                    { var kv = part.Split(':'); int id, c; if (kv.Length == 2 && int.TryParse(kv[0], out id) && int.TryParse(kv[1], out c) && IsRegularDeckCard(id)) d[id] = c; }
                s_pool = d; s_poolDirty = true; return "ok:" + d.Count;
            } catch (Exception e) { return "EX:" + e.Message; }
        }

        // 是否"正常牌库牌":用游戏 CardConfig 排除机缘/灵宠/秘术/幻境/梦/隐藏/废弃。
        // (Python 端只按宗门+阶段筛,灵宠如勤拙剑挂 sect=1 漏网,这里靠 subcategory 精确剔除。)
        static bool IsRegularDeckCard(int id)
        {
            try {
                if (!ConfigManager.cardConfigDict.ContainsKey(id)) return false;
                var c = ConfigManager.cardConfigDict[id];
                if (c == null || c.hidden || c.obsolete) return false;
                var sub = c.subcategory;
                if (sub == Subcategory.JiYuan || sub == Subcategory.Pet || sub == Subcategory.MiShu
                    || sub == Subcategory.MirageCard || sub == Subcategory.DreamCard
                    || sub == Subcategory.TA18Card || sub == Subcategory.TA27Card || sub == Subcategory.MaCard)
                    return false;
                return true;
            } catch (Exception) { return true; }   // 判断不了就保留,别误杀
        }

        // F2:Tab 热键(Python 端)只能置标志 —— RPC 跑在注入线程,直接 new GameObject /
        // FindObjectsOfType 会被 Unity 拒(只能主线程)。真正的切换在 PumpActions(主线程)里做。
        // ★必须带一个(被忽略的)string 参:bot_glue3 的 callStr 硬匹配「1 个参数」的方法,
        //   无参方法 callStr 找不到 → 静默失败(这正是之前 Tab/D 完全无效的根因)。
        public static string TogglePool(string _) { s_pendingToggle = true; return "ok:queued"; }

        // F3:D 热键(Python 端)同理只置标志,换牌动作在 PumpActions(主线程)里做。
        public static string SwapHovered(string _) { s_pendingSwap = true; return "ok:queued"; }

        // #1 卡池补全:返回玩家主宗门 id(对应 card_phases.json 的 sect 编号)+ 当前境界,
        // 供记牌器列出"本宗门 + 当前阶段所有常规牌"。格式 "sect,realm"。
        public static string GetPlayerSect(string _)
        {
            try {
                var pd = BattleManager.Instance.currentGameStatus.GetMainPlayerData();
                return ((int)pd.sect) + "," + ((int)pd.level);
            } catch (Exception e) { return "EX:" + e.Message; }
        }

        // 主线程泵(~16ms):处理热键待办 + 每帧记录悬浮手牌。注意顺序:先用"上一帧记录的
        // 悬浮卡"处理换牌待办,再更新本帧悬浮卡 —— 用户按 D 后常立刻移开鼠标,等这里执行
        // 时卡面已缩回、找不到悬浮卡,所以必须用上一帧的记录。
        static void PumpActions(long n)
        {
            try { if (s_pendingToggle) { s_pendingToggle = false; DoTogglePool(); } } catch (Exception) { }
            try { if (s_poolRebuild) { s_poolRebuild = false; if (s_poolVisible) { s_poolDirty = true; ShowPool(); } } } catch (Exception) { }
            try { if (s_pendingSwap) { s_pendingSwap = false; if (s_lastHovered != null) DoSwap(s_lastHovered); } } catch (Exception) { }
            try { s_lastHovered = FindHoveredCard(); } catch (Exception) { s_lastHovered = null; }
        }

        // 三按钮切换置顶模式(Unity Button onClick 调,主线程);设标志,下一帧泵重建 overlay。
        static void PoolModeHand() { s_poolMode = 0; s_poolRebuild = true; }
        static void PoolModeEmpty() { s_poolMode = 1; s_poolRebuild = true; }
        static void PoolModeDanger() { s_poolMode = 2; s_poolRebuild = true; }

        // 切换卡池 overlay(主线程执行)。
        static void DoTogglePool()
        {
            s_poolVisible = !s_poolVisible;
            if (s_poolVisible) ShowPool();
            else if (s_poolGo != null) s_poolGo.SetActive(false);
        }

        // 找当前"悬浮放大"的手牌:悬浮的卡 movableRT 被 DOTween 放大到 ZOOMIN_SIZE(1.5),
        // 取手牌里 localScale 最大且明显>1 的那张。无则返回 null。
        static CardItem FindHoveredCard()
        {
            var bp = ILRPanelBase.FindILRPanel<BattlePanel>();
            var cp = bp != null ? bp.FindILRSubPanel<CardPanel>() : null;
            if (cp == null) return null;
            var hand = cp.GetHandCards();
            if (hand == null || hand.Count == 0) return null;
            CardItem best = null; float bestScale = 1.05f;   // 需明显放大才算悬浮
            for (int i = 0; i < hand.Count; i++)
            {
                var c = hand[i];
                if (c == null) continue;
                var mrt = c.movableRT;
                float s = mrt != null ? mrt.localScale.x : c.transform.localScale.x;
                if (s > bestScale) { bestScale = s; best = c; }
            }
            return best;
        }

        // 换掉指定手牌(主线程执行,客户端自己发包+播动画)。
        static void DoSwap(CardItem card)
        {
            if (card == null) return;
            var bp = ILRPanelBase.FindILRPanel<BattlePanel>();
            var cp = bp != null ? bp.FindILRSubPanel<CardPanel>() : null;
            if (cp != null && cp.replaceArea != null) cp.replaceArea.ReplaceCard(card);
        }

        // 预热图鉴卡面 prefab 池:InitPrefabPool 异步从 Addressables 加载卡面 prefab,
        // 内部 if(pool==null) 才真正加载,触发一次即可。之后 IllustrationCardItem.Spawn 才有货。
        static void PrewarmPool()
        {
            if (s_poolPrewarmed) return;
            try { IllustrationCardItem.InitPrefabPool(); } catch (Exception) { }
            s_poolPrewarmed = true;
        }

        static Canvas FindRootCanvas()
        {
            Canvas canv = null;
            foreach (var o in UnityEngine.Object.FindObjectsOfType(typeof(Canvas)))
            { var c = o as Canvas; if (c != null) { canv = c; if (c.transform.parent == null) break; } }
            return canv;
        }
        static RectTransform AddRT(GameObject go) { return go.AddComponent(typeof(RectTransform)) as RectTransform; }
        static void Fill(RectTransform rt)
        { rt.anchorMin = Vector2.zero; rt.anchorMax = Vector2.one; rt.offsetMin = Vector2.zero; rt.offsetMax = Vector2.zero; }

        // 排序:手牌(当前手里有的牌,一级 baseId)置顶,其余按剩余从少到多。
        // (右侧 手牌/已空/危险 三按钮切换置顶 + 顶部阶段筛选 下一步做。)
        // 返回每项 = {card_id, rem, group}。
        static List<int[]> SortedPool()
        {
            var handIds = new List<int>();
            try {
                var bp = ILRPanelBase.FindILRPanel<BattlePanel>();
                var cp = bp != null ? bp.FindILRSubPanel<CardPanel>() : null;
                if (cp != null)
                {
                    var hand = cp.GetHandCards();
                    if (hand != null)
                        for (int i = 0; i < hand.Count; i++)
                        {
                            var c = hand[i];
                            if (c != null && c.cardConfig != null)
                            {
                                int bid = ConfigManager.GetCardBaseId(c.cardConfig.id);
                                if (!handIds.Contains(bid)) handIds.Add(bid);
                            }
                        }
                }
            } catch (Exception) { }
            var list = new List<int[]>();
            foreach (var kv in s_pool)
            {
                int id = kv.Key, rem = kv.Value;
                int grp;
                if (s_poolMode == 1) grp = (rem <= 0) ? 0 : 1;        // 已空(剩0)置顶
                else if (s_poolMode == 2) grp = (rem <= 3) ? 0 : 1;   // 危险(剩≤3)置顶
                else grp = handIds.Contains(id) ? 0 : 1;             // 手牌置顶(默认)
                list.Add(new int[] { id, rem, grp });
            }
            for (int i = 0; i < list.Count; i++)   // 按 (group, rem) 升序:手牌在前,组内剩少在前
            {
                int best = i;
                for (int j = i + 1; j < list.Count; j++)
                    if (list[j][2] < list[best][2] || (list[j][2] == list[best][2] && list[j][1] < list[best][1])) best = j;
                if (best != i) { var t = list[i]; list[i] = list[best]; list[best] = t; }
            }
            return list;
        }

        // 卡池 overlay v2:全屏黑底 + ScrollRect 可上下滚 + 每张游戏原生完整卡面(IllustrationCardItem,
        // 含卡图/卡名/描述)+ 卡下方"剩X"。
        static void ShowPool()
        {
            try {
                if (s_poolGo == null || s_poolDirty)
                {
                    if (s_poolGo != null) { UnityEngine.Object.Destroy(s_poolGo); s_poolGo = null; }
                    s_poolErr = "";
                    var canv = FindRootCanvas();
                    if (canv == null) return;

                    s_poolGo = new GameObject("BotPool");
                    s_poolGo.transform.SetParent(canv.transform, false);
                    Fill(AddRT(s_poolGo));
                    var bg = s_poolGo.AddComponent(typeof(Image)) as Image;
                    bg.color = new Color(0.04f, 0.05f, 0.09f, 0.96f); bg.raycastTarget = true;   // 深蓝黑,厚重
                    var f = FindFont();

                    // 顶部标题栏(略亮的条 + 标题 + 分隔线)
                    var barGo = new GameObject("Bar"); barGo.transform.SetParent(s_poolGo.transform, false);
                    var brt = AddRT(barGo); brt.anchorMin = new Vector2(0f, 1f); brt.anchorMax = new Vector2(1f, 1f);
                    brt.pivot = new Vector2(0.5f, 1f); brt.anchoredPosition = Vector2.zero; brt.sizeDelta = new Vector2(0f, 54f);
                    var barbg = barGo.AddComponent(typeof(Image)) as Image; barbg.color = new Color(0.10f, 0.13f, 0.21f, 1f); barbg.raycastTarget = false;
                    var lineGo = new GameObject("Line"); lineGo.transform.SetParent(s_poolGo.transform, false);
                    var lrt2 = AddRT(lineGo); lrt2.anchorMin = new Vector2(0f, 1f); lrt2.anchorMax = new Vector2(1f, 1f);
                    lrt2.pivot = new Vector2(0.5f, 1f); lrt2.anchoredPosition = new Vector2(0f, -54f); lrt2.sizeDelta = new Vector2(0f, 2f);
                    var lImg = lineGo.AddComponent(typeof(Image)) as Image; lImg.color = new Color(0.4f, 0.6f, 0.95f, 0.7f); lImg.raycastTarget = false;
                    var titleGo = new GameObject("Title"); titleGo.transform.SetParent(barGo.transform, false);
                    var trt = AddRT(titleGo); Fill(trt);
                    var tlbl = titleGo.AddComponent(typeof(TextMeshProUGUI)) as TextMeshProUGUI;
                    if (f != null) tlbl.font = f; tlbl.fontSize = 28f; tlbl.alignment = TextAlignmentOptions.Center; tlbl.raycastTarget = false;

                    // 滚动容器:ScrollRect + Viewport(RectMask2D 裁剪) + Content(手动定位,固定高度)
                    var scrollGo = new GameObject("Scroll"); scrollGo.transform.SetParent(s_poolGo.transform, false);
                    var srt = AddRT(scrollGo); srt.anchorMin = Vector2.zero; srt.anchorMax = Vector2.one;
                    srt.offsetMin = new Vector2(48f, 26f); srt.offsetMax = new Vector2(-150f, -64f);
                    var sr = scrollGo.AddComponent(typeof(ScrollRect)) as ScrollRect;
                    sr.horizontal = false; sr.vertical = true; sr.scrollSensitivity = 45f;

                    var vpGo = new GameObject("Viewport"); vpGo.transform.SetParent(scrollGo.transform, false);
                    var vrt = AddRT(vpGo); Fill(vrt);
                    var vImg = vpGo.AddComponent(typeof(Image)) as Image;   // 透明,但 raycastTarget 让滚轮事件命中 → ScrollRect 才会滚
                    vImg.color = new Color(0f, 0f, 0f, 0f); vImg.raycastTarget = true;
                    vpGo.AddComponent(typeof(RectMask2D));

                    var contentGo = new GameObject("Content"); contentGo.transform.SetParent(vpGo.transform, false);
                    var crt = AddRT(contentGo); crt.anchorMin = new Vector2(0f, 1f); crt.anchorMax = new Vector2(1f, 1f);
                    crt.pivot = new Vector2(0.5f, 1f); crt.anchoredPosition = Vector2.zero;
                    sr.viewport = vrt; sr.content = crt;

                    var ordered = SortedPool();
                    int perRow = 6; float cw = 184f, ch = 286f, gx = 18f, gy = 22f;
                    int rows = (ordered.Count + perRow - 1) / perRow; if (rows < 1) rows = 1;
                    crt.sizeDelta = new Vector2(0f, gy + rows * (ch + gy));
                    float startX = -((perRow - 1) * (cw + gx)) / 2f;

                    bool spawnFail = false;
                    for (int k = 0; k < ordered.Count; k++)
                    {
                        int id = ordered[k][0], rem = ordered[k][1];
                        int row = k / perRow, col = k % perRow;
                        var cell = new GameObject("c" + id); cell.transform.SetParent(contentGo.transform, false);
                        var clrt = AddRT(cell);
                        clrt.anchorMin = new Vector2(0.5f, 1f); clrt.anchorMax = new Vector2(0.5f, 1f); clrt.pivot = new Vector2(0.5f, 1f);
                        clrt.sizeDelta = new Vector2(cw, ch);
                        clrt.anchoredPosition = new Vector2(startX + col * (cw + gx), -(gy + row * (ch + gy)));

                        // 卡面:游戏原生 IllustrationCardItem(完整卡面,含文字)
                        var holder = new GameObject("card"); holder.transform.SetParent(cell.transform, false);
                        var hrt = AddRT(holder); hrt.anchorMin = new Vector2(0.5f, 1f); hrt.anchorMax = new Vector2(0.5f, 1f);
                        hrt.pivot = new Vector2(0.5f, 1f); hrt.anchoredPosition = new Vector2(0f, 0f); hrt.sizeDelta = new Vector2(cw, ch - 42f);
                        // 整张卡面不吃射线:卡面子物体(卡图)被命中也会让 PointerEnter 冒泡到根触发放大,
                        // 只关根 Graphic 不够 → CanvasGroup.blocksRaycasts=false 一刀切掉整棵子树的射线。
                        var hcg = holder.AddComponent(typeof(CanvasGroup)) as CanvasGroup; hcg.blocksRaycasts = false;
                        try {
                            var ic = IllustrationCardItem.Spawn(holder.transform);
                            if (ic == null) spawnFail = true;
                            else {
                                ic.SetData(id);
                                // 关掉卡面 hover 放大/点击:cell 根 Graphic 不再接收射线(用户嫌悬浮变大丑)
                                var g = ic.transform.GetComponent(typeof(Graphic)) as Graphic;
                                if (g != null) g.raycastTarget = false;
                                var irt = ic.transform as RectTransform;
                                if (irt != null)
                                {
                                    irt.anchorMin = new Vector2(0.5f, 0.5f); irt.anchorMax = new Vector2(0.5f, 0.5f);
                                    irt.pivot = new Vector2(0.5f, 0.5f); irt.anchoredPosition = Vector2.zero;
                                    irt.localScale = new Vector3(POOL_CARD_SCALE, POOL_CARD_SCALE, 1f);
                                }
                                ic.CardInAnimation(false);
                            }
                        } catch (Exception e) { spawnFail = true; if (string.IsNullOrEmpty(s_poolErr)) s_poolErr = e.Message; }

                        // 剩余数字徽章(卡下方:深色圆底条 + 彩色数字)
                        bool empty = rem <= 0; bool low = rem > 0 && rem < POOL_ABUNDANT;
                        var badge = new GameObject("badge"); badge.transform.SetParent(cell.transform, false);
                        var bgr = AddRT(badge); bgr.anchorMin = new Vector2(0.5f, 0f); bgr.anchorMax = new Vector2(0.5f, 0f);
                        bgr.pivot = new Vector2(0.5f, 0f); bgr.anchoredPosition = new Vector2(0f, 0f); bgr.sizeDelta = new Vector2(88f, 36f);
                        var bImg = badge.AddComponent(typeof(Image)) as Image; bImg.raycastTarget = false;
                        bImg.color = empty ? new Color(0.26f, 0.10f, 0.10f, 0.9f)
                            : (low ? new Color(0.30f, 0.24f, 0.05f, 0.9f) : new Color(0.07f, 0.20f, 0.11f, 0.9f));
                        var numGo = new GameObject("n"); numGo.transform.SetParent(badge.transform, false);
                        var nrt = AddRT(numGo); Fill(nrt);
                        var nlbl = numGo.AddComponent(typeof(TextMeshProUGUI)) as TextMeshProUGUI;
                        if (f != null) nlbl.font = f; nlbl.fontSize = 25f; nlbl.alignment = TextAlignmentOptions.Center;
                        nlbl.raycastTarget = false; nlbl.enableWordWrapping = false;
                        nlbl.color = empty ? new Color(1f, 0.55f, 0.55f, 1f)
                            : (low ? new Color(1f, 0.88f, 0.35f, 1f) : new Color(0.62f, 1f, 0.72f, 1f));
                        nlbl.text = "剩 " + rem;
                    }

                    // 右侧三按钮:手牌 / 已空 / 危险,点击切换置顶模式(当前模式高亮)
                    var modeLabels = new string[] { "手牌", "已空", "危险" };
                    for (int mi = 0; mi < 3; mi++)
                    {
                        var btnGo = new GameObject("mode" + mi); btnGo.transform.SetParent(s_poolGo.transform, false);
                        var mrt = AddRT(btnGo); mrt.anchorMin = new Vector2(1f, 1f); mrt.anchorMax = new Vector2(1f, 1f);
                        mrt.pivot = new Vector2(1f, 1f); mrt.anchoredPosition = new Vector2(-14f, -72f - mi * 64f); mrt.sizeDelta = new Vector2(108f, 54f);
                        var mImg = btnGo.AddComponent(typeof(Image)) as Image;
                        mImg.color = (s_poolMode == mi) ? new Color(0.20f, 0.46f, 0.78f, 1f) : new Color(0.15f, 0.18f, 0.27f, 0.95f);
                        mImg.raycastTarget = true;
                        var mbtn = btnGo.AddComponent(typeof(Button)) as Button;
                        if (mi == 0) mbtn.onClick.AddListener(new UnityAction(PoolModeHand));
                        else if (mi == 1) mbtn.onClick.AddListener(new UnityAction(PoolModeEmpty));
                        else mbtn.onClick.AddListener(new UnityAction(PoolModeDanger));
                        var mlGo = new GameObject("t"); mlGo.transform.SetParent(btnGo.transform, false);
                        var mlrt = AddRT(mlGo); Fill(mlrt);
                        var mlbl = mlGo.AddComponent(typeof(TextMeshProUGUI)) as TextMeshProUGUI;
                        if (f != null) mlbl.font = f; mlbl.fontSize = 24f; mlbl.alignment = TextAlignmentOptions.Center;
                        mlbl.raycastTarget = false; mlbl.color = (s_poolMode == mi) ? Color.white : new Color(0.7f, 0.75f, 0.85f, 1f);
                        mlbl.text = modeLabels[mi];
                    }

                    if (spawnFail && string.IsNullOrEmpty(s_poolErr)) s_poolErr = "卡面prefab未就绪,稍候再按一次Tab";
                    tlbl.color = string.IsNullOrEmpty(s_poolErr) ? new Color(0.86f, 0.92f, 1f, 1f) : new Color(1f, 0.5f, 0.5f, 1f);
                    string modeName = s_poolMode == 1 ? "已空置顶" : (s_poolMode == 2 ? "危险(剩≤3)置顶" : "手牌置顶");
                    tlbl.text = string.IsNullOrEmpty(s_poolErr) ? ("本局卡池  ·  " + ordered.Count + " 种  ·  " + modeName + "  ·  其余剩少在前   (Tab 关闭)") : ("卡池: " + s_poolErr);

                    // 底部操作提示(帮助):告诉用户这个卡池页面怎么用
                    var tipGo = new GameObject("Tip"); tipGo.transform.SetParent(s_poolGo.transform, false);
                    var tiprt = AddRT(tipGo); tiprt.anchorMin = new Vector2(0f, 0f); tiprt.anchorMax = new Vector2(1f, 0f);
                    tiprt.pivot = new Vector2(0.5f, 0f); tiprt.anchoredPosition = new Vector2(0f, 3f); tiprt.sizeDelta = new Vector2(0f, 22f);
                    var tiplbl = tipGo.AddComponent(typeof(TextMeshProUGUI)) as TextMeshProUGUI;
                    if (f != null) tiplbl.font = f; tiplbl.fontSize = 17f; tiplbl.alignment = TextAlignmentOptions.Center;
                    tiplbl.raycastTarget = false; tiplbl.enableWordWrapping = false; tiplbl.color = new Color(0.55f, 0.62f, 0.75f, 1f);
                    tiplbl.text = "滚轮上下滚动   ·   右侧切换置顶(手牌/已空/危险)   ·   游戏内悬浮手牌按 D 换牌   ·   再按 Tab 关闭";

                    s_poolDirty = false;
                }
                s_poolGo.SetActive(true);
            } catch (Exception e) { s_poolErr = e.Message; }
        }

        static bool HasCJK(string s)
        { if (string.IsNullOrEmpty(s)) return false; for (int i = 0; i < s.Length; i++) { char c = s[i]; if (c >= 0x4E00 && c <= 0x9FFF) return true; } return false; }
        static TMP_FontAsset FindFont()
        {
            if (s_font != null) return s_font; TMP_FontAsset fb = null;
            foreach (var o in UnityEngine.Object.FindObjectsOfType(typeof(TextMeshProUGUI)))
            { var t = o as TextMeshProUGUI; if (t == null || t.font == null) continue; if (fb == null) fb = t.font; if (HasCJK(t.text)) { s_font = t.font; return s_font; } }
            s_font = fb; return s_font;
        }
        static TextMeshProUGUI MakeLayer(Transform c, float size, Color col, Vector2 off)
        {
            var go = new GameObject(off == Vector2.zero ? "fg" : "o"); go.transform.SetParent(c, false);
            var lbl = go.AddComponent(typeof(TextMeshProUGUI)) as TextMeshProUGUI;
            var f = FindFont(); if (f != null) lbl.font = f;
            lbl.fontSize = size; lbl.color = col; lbl.alignment = TextAlignmentOptions.Center;
            lbl.raycastTarget = false; lbl.enableWordWrapping = false;
            var rt = lbl.rectTransform; rt.anchorMin = Vector2.zero; rt.anchorMax = Vector2.one; rt.offsetMin = off; rt.offsetMax = off;
            return lbl;
        }
        static List<TextMeshProUGUI> Ensure(Transform vis, string tag, bool isLeft)
        {
            var ex = vis.Find(tag); var list = new List<TextMeshProUGUI>();
            if (ex != null) { for (int i = 0; i < ex.childCount; i++) { var t = ex.GetChild(i).GetComponent(typeof(TextMeshProUGUI)) as TextMeshProUGUI; if (t != null) list.Add(t); } return list; }
            var c = new GameObject(tag); c.transform.SetParent(vis, false);
            var crt = c.AddComponent(typeof(RectTransform)) as RectTransform;
            float size; Color col; Color black = new Color(0f, 0f, 0f, 1f);
            if (isLeft)
            {
                size = 26f; col = new Color(0.62f, 0.93f, 1f, 1f);
                crt.anchorMin = new Vector2(1f, 1f); crt.anchorMax = new Vector2(1f, 1f); crt.pivot = new Vector2(1f, 1f);
                crt.anchoredPosition = new Vector2(1f, -18f); crt.sizeDelta = new Vector2(72f, 38f);
            }
            else
            {
                size = 26f; col = new Color(1f, 0.88f, 0.42f, 1f);
                crt.anchorMin = new Vector2(0.5f, 1f); crt.anchorMax = new Vector2(0.5f, 1f); crt.pivot = new Vector2(0.5f, 1f);
                crt.anchoredPosition = new Vector2(0f, s_dmgY); crt.sizeDelta = new Vector2(120f, 34f);
            }
            for (int i = 0; i < OFF.Length; i++) list.Add(MakeLayer(c.transform, size, black, OFF[i]));
            list.Add(MakeLayer(c.transform, size, col, Vector2.zero));
            return list;
        }
        static void RemoveDmg(Transform vis) { var d = vis.Find(DMG); if (d != null) UnityEngine.Object.Destroy(((Component)d).gameObject); }
        static void SetText(List<TextMeshProUGUI> list, string txt) { for (int k = 0; k < list.Count; k++) list[k].text = txt; }
        static void ApplyPos(GameObject go, Vector2 pos)
        {
            if (go == null) return;
            var rt = go.GetComponent(typeof(RectTransform)) as RectTransform;
            if (rt != null && rt.anchoredPosition != pos) rt.anchoredPosition = pos;
        }

        // Create a screen-anchored 8-layer-outlined label under the root canvas.
        static GameObject MakeScreenLabel(string nm, Vector2 anchor, Vector2 pivot,
            Vector2 pos, Vector2 size, float fsize, Color col, out List<TextMeshProUGUI> layers)
        {
            layers = null;
            Canvas canv = null;
            foreach (var o in UnityEngine.Object.FindObjectsOfType(typeof(Canvas)))
            { var c = o as Canvas; if (c != null) { canv = c; if (c.transform.parent == null) break; } }
            if (canv == null) return null;
            var go = new GameObject(nm);
            go.transform.SetParent(canv.transform, false);
            var crt = go.AddComponent(typeof(RectTransform)) as RectTransform;
            crt.anchorMin = anchor; crt.anchorMax = anchor; crt.pivot = pivot;
            crt.anchoredPosition = pos; crt.sizeDelta = size;
            layers = new List<TextMeshProUGUI>();
            for (int i = 0; i < OFF.Length; i++) layers.Add(MakeLayer(go.transform, fsize, s_black, OFF[i]));
            layers.Add(MakeLayer(go.transform, fsize, col, Vector2.zero));
            return go;
        }

        // 左对齐的单元格描边层(MakeLayer 是居中版;造伤网格要左对齐才能逐列对齐)
        static TextMeshProUGUI MakeCellLayer(Transform c, float size, Color col, Vector2 off)
        {
            var go = new GameObject(off == Vector2.zero ? "fg" : "o"); go.transform.SetParent(c, false);
            var lbl = go.AddComponent(typeof(TextMeshProUGUI)) as TextMeshProUGUI;
            var f = FindFont(); if (f != null) lbl.font = f;
            lbl.fontSize = size; lbl.color = col; lbl.alignment = TextAlignmentOptions.Left;
            lbl.raycastTarget = false; lbl.enableWordWrapping = false; lbl.overflowMode = TextOverflowModes.Overflow;
            var rt = lbl.rectTransform; rt.anchorMin = Vector2.zero; rt.anchorMax = Vector2.one; rt.offsetMin = off; rt.offsetMax = off;
            return lbl;
        }

        // 造伤表格:s_total = 行(\n) × 单元格(\t)。每格是独立定位的 TMP,钉在固定列像素 x,
        // 逐列严格对齐(不依赖字体宽度 / 不用 <mspace>/<pos>,因为这套 TMP 都不认)。
        static void DrawTotal()
        {
            if (string.IsNullOrEmpty(s_total)) { if (s_totalGo != null) s_totalGo.SetActive(false); return; }
            string[] rows = s_total.Split('\n');
            int nrow = rows.Length, ncol = 1;
            string[][] cells = new string[nrow][];
            for (int r = 0; r < nrow; r++) { cells[r] = rows[r].Split('\t'); if (cells[r].Length > ncol) ncol = cells[r].Length; }

            // 维度变化 → 销毁重建;否则复用同一批单元格只改文字。
            if (s_totalGo != null && (s_totalRows != nrow || s_totalCols != ncol))
            { UnityEngine.Object.Destroy(s_totalGo); s_totalGo = null; s_totalCells = null; }

            if (s_totalGo == null)
            {
                var canv = FindRootCanvas(); if (canv == null) return;
                s_totalGo = new GameObject("BotTotal"); s_totalGo.transform.SetParent(canv.transform, false);
                var crt = AddRT(s_totalGo);
                crt.anchorMin = new Vector2(0.5f, 1f); crt.anchorMax = new Vector2(0.5f, 1f); crt.pivot = new Vector2(0.5f, 1f);
                crt.anchoredPosition = s_totalPos; crt.sizeDelta = new Vector2(ncol * TT_COLW, nrow * TT_LINEH);
                s_totalCells = new List<List<TextMeshProUGUI>>();
                var col = new Color(1f, 0.85f, 0.35f, 1f);
                float xBase = -(ncol * TT_COLW) / 2f + TT_COLW / 2f;   // 居中整块
                for (int r = 0; r < nrow; r++)
                    for (int c = 0; c < ncol; c++)
                    {
                        var cellGo = new GameObject("cell"); cellGo.transform.SetParent(s_totalGo.transform, false);
                        var rt = AddRT(cellGo);
                        rt.anchorMin = new Vector2(0.5f, 1f); rt.anchorMax = new Vector2(0.5f, 1f); rt.pivot = new Vector2(0.5f, 1f);
                        rt.anchoredPosition = new Vector2(xBase + c * TT_COLW, -r * TT_LINEH);
                        rt.sizeDelta = new Vector2(TT_COLW, TT_LINEH);
                        var layers = new List<TextMeshProUGUI>();
                        for (int k = 0; k < OFF.Length; k++) layers.Add(MakeCellLayer(cellGo.transform, TT_FS, s_black, OFF[k]));
                        layers.Add(MakeCellLayer(cellGo.transform, TT_FS, col, Vector2.zero));
                        s_totalCells.Add(layers);
                    }
                s_totalRows = nrow; s_totalCols = ncol;
            }
            if (s_totalGo == null || s_totalCells == null) return;
            s_totalGo.SetActive(true); ApplyPos(s_totalGo, s_totalPos);
            for (int r = 0; r < nrow; r++)
                for (int c = 0; c < ncol; c++)
                {
                    int idx = r * ncol + c; if (idx >= s_totalCells.Count) continue;
                    string txt = (c < cells[r].Length) ? cells[r][c] : "";
                    SetText(s_totalCells[idx], txt);
                }
        }

        static void DrawOpp()
        {
            if (string.IsNullOrEmpty(s_opp)) { if (s_oppGo != null) s_oppGo.SetActive(false); return; }
            if (s_oppGo == null)
                s_oppGo = MakeScreenLabel("BotOpp", new Vector2(0f, 1f), new Vector2(0f, 1f),
                    s_oppPos, new Vector2(380f, 40f), 24f, new Color(1f, 0.62f, 0.62f, 1f), out s_oppLayers);
            if (s_oppGo == null) return;
            s_oppGo.SetActive(true); ApplyPos(s_oppGo, s_oppPos); SetText(s_oppLayers, s_opp);
        }

        // Flashing danger warning (toggles visibility each tick ≈ 0.5s).
        static void DrawWarn(long n)
        {
            if (string.IsNullOrEmpty(s_warn)) { if (s_warnGo != null) s_warnGo.SetActive(false); return; }
            if (s_warnGo == null)
                s_warnGo = MakeScreenLabel("BotWarn", new Vector2(0.5f, 1f), new Vector2(0.5f, 1f),
                    s_warnPos, new Vector2(1000f, 48f), 32f, new Color(1f, 0.22f, 0.22f, 1f), out s_warnLayers);
            if (s_warnGo == null) return;
            ApplyPos(s_warnGo, s_warnPos);
            s_warnGo.SetActive((n % 2) == 0);
            SetText(s_warnLayers, s_warn);
        }

        static void HideScreen()
        {
            if (s_totalGo != null) s_totalGo.SetActive(false);
            if (s_oppGo != null) s_oppGo.SetActive(false);
            if (s_warnGo != null) s_warnGo.SetActive(false);
        }

        // True whenever the battle scene is up. We no longer require the battle
        // result to be settled locally: the skip re-syncs via GameStatusReq() from
        // the authoritative server (which already resolved the round before the
        // animation even plays), so showing/clicking from the moment the battle
        // appears is safe — no more "deal/换牌 lost" from an early click.
        static bool CanSkip()
        {
            try {
                var bm = BattleManager.Instance;
                if (bm == null) return false;
                return bm.currentScene == SceneType.斗法阶段;
            } catch (Exception) { return false; }
        }

        // Faithful skip, step 1 — exactly the game's own SkipBattleResultPanel path
        // (decompiled): unfreeze time + force-break every executing executer, then
        // mark a pending skip. The scene change + server re-sync happen in PumpSkip
        // once the executers have settled (the panel's `await WaitUntil` equivalent).
        static void DoSkip()
        {
            try {
                var bm = BattleManager.Instance;
                if (bm == null) return;
                // Crank time to Unity's max (100f) so the entrance/in-progress anim
                // RACES to the executer's next forceBreak checkpoint — otherwise the
                // break only lands after the entrance finishes ("waits for the battle").
                Time.timeScale = 100f;
                if (bm.allBattleExecuters != null)
                {
                    var list = bm.allBattleExecuters;
                    for (int i = 0; i < list.Count; i++)
                    { var be = list[i]; if (be != null && be.isExecuting) be.forceBreakExecuting = true; }
                }
                s_skipPending = true;   // PumpSkip 在 executer settle 后收尾
            } catch (Exception) { }
        }

        // Faithful skip, step 2 — the tail of SkipBattleResultPanel.OnHide(): once
        // every executer has finished its forced break, change scene back to
        // placement AND call GameStatusReq() so the SERVER re-sends the next round.
        // The force-break skips onEndNormal (the normal deal trigger), so without
        // GameStatusReq the placement is empty — no new cards, no 换牌次数. With it,
        // the server hands back the dealt board + swap charges exactly as normal.
        // ChangeSceneType's default (forceToIdle=true) also resets the idle pose.
        // 强断 executer 会略过 onEndNormal 里的道韵触发(对照 BattleManager 战斗结算):
        // 普通模式 daoYun==0 且 round==4/15,或持"额外选道韵"buff(10015) → 本轮该出道韵。
        static bool DaoyunDueAfterSkip(BattleManager bm)
        {
            try {
                var gs = bm.currentGameStatus;
                if (gs == null || !gs.SelfAlive() || gs.ForbidNormalProcess()) return false;
                if (gs.playerPrivateData.daoYun != 0) return false;     // 本轮已选过
                if (gs.round == 4 || gs.round == 15) return true;
                var pd = gs.GetSelfBattlePlayerData();
                return pd != null && pd.permanentBuffTempDatas != null
                    && pd.permanentBuffTempDatas.ContainsKey(10015);
            } catch (Exception) { return false; }
        }

        // 道韵选择面板当前是否在显示(玩家还在选)。
        static bool DaoyunPanelUp()
        {
            try {
                var bp = ILRPanelBase.FindILRPanel<BattlePanel>();
                var dp = bp != null ? bp.FindILRSubPanel<BattleDaoYunSelectionPanel>() : null;
                return dp != null && dp.panel.isShow && !dp.hiding;
            } catch (Exception) { return false; }
        }

        static void PumpSkip()
        {
            if (!s_skipPending) return;
            try {
                var bm = BattleManager.Instance;
                if (bm == null) { Time.timeScale = 1f; s_skipPending = false; return; }
                if (bm.allBattleExecuters != null)
                {
                    var list = bm.allBattleExecuters;
                    // 每 tick 持续强断所有在执行的 executer —— 含"点击时还没开始执行"的那些:
                    // 按钮刚出现就狂按时,这轮 executer 还在入场(isExecuting=false),DoSkip 的
                    // 一次性强断漏掉它们;旧逻辑只"等"不"断" → 它们在 100x 下完整跑完才 settle =
                    // 卡在斗法阶段一会儿。改成每 tick 都强断,漏网的也立刻被打断 → 必定跳掉。
                    bool anyExecuting = false;
                    for (int i = 0; i < list.Count; i++)
                    {
                        var be = list[i];
                        if (be != null && be.isExecuting) { be.forceBreakExecuting = true; anyExecuting = true; }
                    }
                    if (anyExecuting) { Time.timeScale = 100f; return; }
                }
                if (bm.currentScene == SceneType.斗法阶段)
                {
                    bool daoyunDue = DaoyunDueAfterSkip(bm);          // 切场景前判断这轮该不该出道韵
                    bm.ChangeSceneType(SceneType.修炼阶段);          // 跳出整场回摆牌(forceToIdle)
                    if (!bm.isSpectating) bm.GameStatusReq();        // server 重发下一轮发牌+换牌次数
                    if (daoyunDue) s_forceDaoyun = true;             // 进摆牌后由 ForceDaoyunPump 强拉道韵选择面板
                }
                Time.timeScale = 1f;
                s_skipPending = false;
            } catch (Exception) { Time.timeScale = 1f; s_skipPending = false; }
        }

        // 跳过吞掉了该回合的道韵 → 进入摆牌(修炼阶段)后强拉一次道韵选择面板。
        static void ForceDaoyunPump()
        {
            if (!s_forceDaoyun) return;
            try {
                var bm = BattleManager.Instance;
                if (bm == null) { s_forceDaoyun = false; return; }
                if (bm.currentScene != SceneType.修炼阶段) return;   // 等进摆牌(道韵在修炼阶段出)
                s_forceDaoyun = false;                              // 只触发一次
                if (!DaoyunDueAfterSkip(bm)) return;                // 已选/不该出
                if (DaoyunPanelUp()) return;                        // 面板已弹出 → 不重复请求
                bm.PendingDaoYunReq();                              // 强拉道韵选择面板
            } catch (Exception) { s_forceDaoyun = false; }
        }

        // A clickable 跳过战斗 button shown (top-right) only while a battle plays.
        static void DrawSkipButton()
        {
            if (!s_showSkip || !CanSkip()) { if (s_skipBtnGo != null) s_skipBtnGo.SetActive(false); return; }
            if (s_skipBtnGo == null)
            {
                Canvas canv = null;
                foreach (var o in UnityEngine.Object.FindObjectsOfType(typeof(Canvas)))
                { var c = o as Canvas; if (c != null) { canv = c; if (c.transform.parent == null) break; } }
                if (canv == null) return;
                s_skipBtnGo = new GameObject("BotSkipBtn");
                s_skipBtnGo.transform.SetParent(canv.transform, false);
                var rt = s_skipBtnGo.AddComponent(typeof(RectTransform)) as RectTransform;
                rt.anchorMin = new Vector2(1f, 1f); rt.anchorMax = new Vector2(1f, 1f); rt.pivot = new Vector2(1f, 1f);
                rt.anchoredPosition = s_skipPos; rt.sizeDelta = new Vector2(150f, 56f);
                var img = s_skipBtnGo.AddComponent(typeof(Image)) as Image;
                img.color = new Color(0.12f, 0.45f, 0.65f, 0.92f);
                img.raycastTarget = true;
                var btn = s_skipBtnGo.AddComponent(typeof(Button)) as Button;
                btn.onClick.AddListener(new UnityAction(DoSkip));
                var tgo = new GameObject("t"); tgo.transform.SetParent(s_skipBtnGo.transform, false);
                var lbl = tgo.AddComponent(typeof(TextMeshProUGUI)) as TextMeshProUGUI;
                var f = FindFont(); if (f != null) lbl.font = f;
                lbl.fontSize = 28f; lbl.color = new Color(1f, 1f, 1f, 1f);
                lbl.alignment = TextAlignmentOptions.Center; lbl.raycastTarget = false; lbl.text = "跳过战斗";
                var lrt = lbl.rectTransform;
                lrt.anchorMin = Vector2.zero; lrt.anchorMax = Vector2.one;
                lrt.offsetMin = Vector2.zero; lrt.offsetMax = Vector2.zero;
            }
            s_skipBtnGo.SetActive(true);
            ApplyPos(s_skipBtnGo, s_skipPos);   // 每 tick 重设 → 设置面板调位置实时生效
        }

        static void OnTick(long n)
        {
            try {
                DrawSkipButton();   // independent of placement state — shows during battle
                PumpSkip();         // finish a pending skip once executers settle
                ForceDaoyunPump();  // 跳过吞了道韵 → 进摆牌后强拉道韵选择面板
                var bp = ILRPanelBase.FindILRPanel<BattlePanel>();
                var cp = bp != null ? bp.FindILRSubPanel<CardPanel>() : null;
                if (cp == null) { HideScreen(); return; }   // out of a game → hide all screen labels
                PrewarmPool();   // 进对局后预热图鉴卡面 prefab 池,Tab 才能即时 Spawn 卡面

                // Count cards actually rendered on the placement board/hand. In
                // battle the placement cards aren't shown (only the battle arena),
                // so visible==0 ⇒ we're NOT in placement ⇒ hide the screen overlays.
                int visible = 0;
                var grids = cp.GetCardGrids();
                for (int i = 0; i < grids.Count; i++)
                {
                    var card = grids[i].GetCard();
                    if (card == null || card.cardConfig == null) continue;
                    var vis = card.movableRT; if (vis == null) continue;
                    if (vis.gameObject.activeInHierarchy) visible++;
                    // Per-card damage removed (user wants the whole-board total via
                    // DrawTotal). Keep only the deck-count (剩X) on each board card.
                    RemoveDmg(vis);
                    SetText(Ensure(vis, LEFT, true), LeftTxt(card.cardConfig.name));
                }
                var hand = cp.GetHandCards();
                for (int i = 0; i < hand.Count; i++)
                {
                    var card = hand[i];
                    if (card == null || card.cardConfig == null) continue;
                    var vis = card.movableRT; if (vis == null) continue;
                    if (vis.gameObject.activeInHierarchy) visible++;
                    RemoveDmg(vis);
                    SetText(Ensure(vis, LEFT, true), LeftTxt(card.cardConfig.name));
                }
                // Debounce: only hide after SUSTAINED no-visible-cards (~2s), so a
                // single-frame dip during placement animations doesn't flicker the
                // overlays. Battle lasts many seconds, so a 2s delay is invisible.
                if (visible == 0) s_noCard++; else s_noCard = 0;
                if (s_noCard >= 4) { HideScreen(); return; }   // sustained → in battle
                DrawTotal();
                DrawOpp();
                DrawWarn(n);
            } catch (Exception) { }
        }
        static string LeftTxt(string name)
        { if (!s_showLeft) return ""; int left; return s_remaining.TryGetValue(name ?? "", out left) ? ("剩" + left) : "剩?"; }

    }
}
