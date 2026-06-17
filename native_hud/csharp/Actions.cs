using System;
using System.Reflection;
using System.Collections.Generic;
using System.Text;
using Proto;   // CardInfo, CardPosition

namespace YiXianBot
{
    // v6 — full surface, ALL via the game's own methods/registry (no gc.choose, no raw pact).
    // Board ops self-acquire CardPanel; discrete actions use BattleManager.Instance +
    // FindILRPanel; selection reads options via reflection on private item lists.
    public static class Bot8
    {
        public static string Ping() { return "BOT6-OK"; }

        static BattlePanel BP() { return ILRPanelBase.FindILRPanel<BattlePanel>(); }
        static CardPanel CP() { var bp = BP(); return bp == null ? null : bp.FindILRSubPanel<CardPanel>(); }

        // ── reads / diag ────────────────────────────────────────────────────────
        public static string ReadHand()
        {
            var cp = CP(); if (cp == null) return "err:no CardPanel";
            try { var h = cp.GetHandCards(); var sb = new StringBuilder("hand=");
                for (int i = 0; i < h.Count; i++) { if (i > 0) sb.Append('|'); sb.Append(i).Append(':').Append(h[i].cardInfo.id); }
                return sb.ToString(); } catch (Exception e) { return "EX:" + e.Message; }
        }
        public static string ReadBoard()
        {
            var cp = CP(); if (cp == null) return "err:no CardPanel";
            try { var g = cp.GetCardGrids(); var sb = new StringBuilder("board=");
                for (int i = 0; i < g.Count; i++) { var c = g[i].GetCard(); if (i > 0) sb.Append('|'); sb.Append(i).Append(':').Append(c == null ? -1 : c.cardInfo.id); }
                return sb.ToString(); } catch (Exception e) { return "EX:" + e.Message; }
        }
        public static string Diag()
        {
            var sb = new StringBuilder();
            try { sb.Append("bm=").Append(BattleManager.Instance != null); } catch (Exception e) { sb.Append("bmEX:").Append(e.Message); }
            try { var bp = BP(); sb.Append(" bp=").Append(bp != null);
                  if (bp != null) sb.Append(" cp=").Append(bp.FindILRSubPanel<CardPanel>() != null); } catch (Exception e) { sb.Append(" bpEX:").Append(e.Message); }
            return sb.ToString();
        }

        // ── board ops ───────────────────────────────────────────────────────────
        public static string Place(int handIdx, int gridIdx)
        {
            var cp = CP(); if (cp == null) return "err:no CardPanel";
            try { var hand = cp.GetHandCards(); var grids = cp.GetCardGrids();
                if (handIdx < 0 || handIdx >= hand.Count) return "err:handIdx OOB";
                CardItem card = hand[handIdx]; CardGrid g = null;
                if (gridIdx < 0) { for (int i = 0; i < grids.Count; i++) if (grids[i].GetCard() == null) { g = grids[i]; gridIdx = i; break; } if (g == null) return "err:no empty grid"; }
                else { if (gridIdx >= grids.Count) return "err:gridIdx OOB"; g = grids[gridIdx]; }
                cp.MoveToGrid(card, g); return "ok:place hand[" + handIdx + "]->grid[" + gridIdx + "]";
            } catch (Exception e) { return "EX:" + e.Message; }
        }
        public static string Evict(int gridIdx)
        {
            var cp = CP(); if (cp == null) return "err:no CardPanel";
            try { var grids = cp.GetCardGrids();
                if (gridIdx < 0 || gridIdx >= grids.Count) return "err:gridIdx OOB";
                var card = grids[gridIdx].GetCard(); if (card == null) return "err:grid empty";
                cp.MoveToHand(card); return "ok:evict grid[" + gridIdx + "]"; } catch (Exception e) { return "EX:" + e.Message; }
        }
        public static string Merge(int a, int b)
        {
            var cp = CP(); if (cp == null) return "err:no CardPanel";
            try { var hand = cp.GetHandCards();
                if (a < 0 || a >= hand.Count || b < 0 || b >= hand.Count) return "err:idx OOB";
                cp.TryUpgradeHandCard(hand[a], hand[b]); return "ok:merge [" + a + "]+[" + b + "]"; } catch (Exception e) { return "EX:" + e.Message; }
        }
        public static string Refine(int handIdx)
        {
            var cp = CP(); if (cp == null) return "err:no CardPanel";
            try { var hand = cp.GetHandCards();
                if (handIdx < 0 || handIdx >= hand.Count) return "err:handIdx OOB";
                var card = hand[handIdx]; if (card.cardInfo.position != CardPosition.Hand) return "err:not hand";
                cp.refineArea.RefineCard(card); return "ok:refine[" + handIdx + "]"; } catch (Exception e) { return "EX:" + e.Message; }
        }
        public static string Replace(int handIdx)
        {
            var cp = CP(); if (cp == null) return "err:no CardPanel";
            try { var hand = cp.GetHandCards();
                if (handIdx < 0 || handIdx >= hand.Count) return "err:handIdx OOB";
                var card = hand[handIdx]; if (card.cardInfo.position != CardPosition.Hand) return "err:not hand";
                cp.replaceArea.ReplaceCard(card); return "ok:replace[" + handIdx + "]"; } catch (Exception e) { return "EX:" + e.Message; }
        }

        // ── discrete: round flow (the game's OWN methods, proven) ───────────────
        public static string Breakthrough()   // 突破 → opens talent panel
        {
            try { if (BattleManager.Instance == null) return "err:no BM"; BattleManager.Instance.PendingTalentReq(); return "ok:breakthrough"; }
            catch (Exception e) { return "EX:" + e.Message; }
        }
        public static string Ready()           // 准备 → submit round
        {
            try { var bp = BP(); if (bp == null || bp.readyLayer == null) return "err:no readyLayer"; bp.readyLayer.PressReadyButton(); return "ok:ready"; }
            catch (Exception e) { return "EX:" + e.Message; }
        }
        public static string TriggerDaoYun()   // 触发道韵 → opens daoyun panel
        {
            try { if (BattleManager.Instance == null) return "err:no BM"; BattleManager.Instance.PendingDaoYunReq(); return "ok:triggerDaoYun"; }
            catch (Exception e) { return "EX:" + e.Message; }
        }

        // ── selection: 天衍 (read private items via reflection, TalentOnSelect=select+confirm) ──
        public static string ReadTalents()
        {
            var bp = BP(); if (bp == null) return "err:no bp";
            var tp = bp.FindILRSubPanel<TalentSelectionPanel>(); if (tp == null) return "err:no talentPanel";
            try {
                var fi = typeof(TalentSelectionPanel).GetField("m_TalentSelectionItems", BindingFlags.NonPublic | BindingFlags.Instance);
                var list = fi.GetValue(tp) as List<TalentSelectionItem>; if (list == null) return "err:list null";
                var sb = new StringBuilder("talents=");
                for (int i = 0; i < list.Count; i++) { if (i > 0) sb.Append('|'); sb.Append(i).Append(':').Append(list[i].talentId); }
                return sb.ToString();
            } catch (Exception e) { return "EX:" + e.Message; }
        }
        public static string SelectTalentByIndex(int index)
        {
            var bp = BP(); if (bp == null) return "err:no bp";
            var tp = bp.FindILRSubPanel<TalentSelectionPanel>(); if (tp == null) return "err:no talentPanel";
            try {
                var fi = typeof(TalentSelectionPanel).GetField("m_TalentSelectionItems", BindingFlags.NonPublic | BindingFlags.Instance);
                var list = fi.GetValue(tp) as List<TalentSelectionItem>;
                if (list == null || index < 0 || index >= list.Count) return "err:index OOB";
                int id = list[index].talentId; tp.TalentOnSelect(id);
                return "ok:talent[" + index + "] id=" + id;
            } catch (Exception e) { return "EX:" + e.Message; }
        }

        // ── selection: 道韵 (read items, set daoYun + private OnComfirmBtnClick via reflection) ──
        public static string ReadDaoyuns()
        {
            var bp = BP(); if (bp == null) return "err:no bp";
            var dp = bp.FindILRSubPanel<BattleDaoYunSelectionPanel>(); if (dp == null) return "err:no daoyunPanel";
            try {
                var fi = typeof(BattleDaoYunSelectionPanel).GetField("m_Items", BindingFlags.NonPublic | BindingFlags.Instance);
                var list = fi.GetValue(dp) as List<BattleDaoYunSelectionItem>; if (list == null) return "err:list null";
                var sb = new StringBuilder("daoyuns=");
                for (int i = 0; i < list.Count; i++) { if (i > 0) sb.Append('|'); sb.Append(i).Append(':').Append(list[i].cardId); }
                return sb.ToString();
            } catch (Exception e) { return "EX:" + e.Message; }
        }
        public static string SelectDaoyunByIndex(int index)
        {
            var bp = BP(); if (bp == null) return "err:no bp";
            var dp = bp.FindILRSubPanel<BattleDaoYunSelectionPanel>(); if (dp == null) return "err:no daoyunPanel";
            try {
                var fi = typeof(BattleDaoYunSelectionPanel).GetField("m_Items", BindingFlags.NonPublic | BindingFlags.Instance);
                var list = fi.GetValue(dp) as List<BattleDaoYunSelectionItem>;
                if (list == null || index < 0 || index >= list.Count) return "err:index OOB";
                int id = list[index].cardId;
                dp.daoYun = id;
                var mi = typeof(BattleDaoYunSelectionPanel).GetMethod("OnComfirmBtnClick", BindingFlags.NonPublic | BindingFlags.Instance);
                if (mi == null) return "err:confirm method not found";
                mi.Invoke(dp, null);
                return "ok:daoyun[" + index + "] id=" + id;
            } catch (Exception e) { return "EX:" + e.Message; }
        }
    
        // ── selection: 副职业 (CareerSelectionPanel; private OnSelected(idx)+OnComfirmBtnClick via reflection) ──
        public static string ReadCareers()
        {
            var bp = BP(); if (bp == null) return "err:no bp";
            var cp = bp.FindILRSubPanel<CareerSelectionPanel>(); if (cp == null) return "err:no careerPanel";
            try {
                var fi = typeof(CareerSelectionPanel).GetField("m_Datas", BindingFlags.NonPublic | BindingFlags.Instance);
                var list = fi.GetValue(cp) as List<CareerSelectionData>; if (list == null) return "err:list null";
                var sb = new StringBuilder("careers=");
                for (int i = 0; i < list.Count; i++) { if (i > 0) sb.Append('|'); sb.Append(i).Append(':').Append(list[i].career.ToString()).Append('(').Append((int)list[i].career).Append(')'); }
                return sb.ToString();
            } catch (Exception e) { return "EX:" + e.Message; }
        }
        public static string SelectCareerByIndex(int index)
        {
            var bp = BP(); if (bp == null) return "err:no bp";
            var cp = bp.FindILRSubPanel<CareerSelectionPanel>(); if (cp == null) return "err:no careerPanel";
            try {
                var fi = typeof(CareerSelectionPanel).GetField("m_Datas", BindingFlags.NonPublic | BindingFlags.Instance);
                var list = fi.GetValue(cp) as List<CareerSelectionData>;
                if (list == null || index < 0 || index >= list.Count) return "err:index OOB";
                var onSel = typeof(CareerSelectionPanel).GetMethod("OnSelected", BindingFlags.NonPublic | BindingFlags.Instance);
                onSel.Invoke(cp, new object[] { index });
                var confirm = typeof(CareerSelectionPanel).GetMethod("OnComfirmBtnClick", BindingFlags.NonPublic | BindingFlags.Instance);
                if (confirm == null) return "err:confirm not found";
                confirm.Invoke(cp, null);
                return "ok:career[" + index + "] = " + list[index].career.ToString();
            } catch (Exception e) { return "EX:" + e.Message; }
        }

        // ── selection: 天衍 = FateStrategyPanel ("选择天衍仙命"). items public; select by index + private confirm ──
        public static string ReadFates()
        {
            var bp = BP(); if (bp == null) return "err:no bp";
            var fp = bp.FindILRSubPanel<FateStrategyPanel>(); if (fp == null) return "err:no fatePanel";
            try {
                var items = fp.fateStrategyItems; if (items == null) return "err:items null";
                var sb = new StringBuilder("fates=");
                for (int i = 0; i < items.Count; i++) { if (i > 0) sb.Append('|'); sb.Append(i).Append(':').Append(items[i].strategyId); }
                return sb.ToString();
            } catch (Exception e) { return "EX:" + e.Message; }
        }
        public static string SelectFateByIndex(int index)
        {
            var bp = BP(); if (bp == null) return "err:no bp";
            var fp = bp.FindILRSubPanel<FateStrategyPanel>(); if (fp == null) return "err:no fatePanel";
            try {
                fp.currentSelectedIndex = index;
                var mi = typeof(FateStrategyPanel).GetMethod("OnConfirmButtonClick", BindingFlags.NonPublic | BindingFlags.Instance);
                if (mi == null) return "err:confirm not found";
                mi.Invoke(fp, null);
                return "ok:fate(天衍) idx=" + index;
            } catch (Exception e) { return "EX:" + e.Message; }
        }
}
}
