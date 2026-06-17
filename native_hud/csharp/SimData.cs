using System;
using System.Text;
using Proto;

namespace YiXianBot
{
    // Read the live board for yisim: "slot,name,level|..." (empty slot => "slot,,").
    // level = cardConfig.rarity + 1 (upgrade tier). Slot order matches CardGrid index.
    public static class SimData
    {
        public static string ReadBoardSim()
        {
            try {
                var bp = ILRPanelBase.FindILRPanel<BattlePanel>();
                var cp = bp != null ? bp.FindILRSubPanel<CardPanel>() : null;
                if (cp == null) return "";
                var grids = cp.GetCardGrids();
                var sb = new StringBuilder();
                for (int i = 0; i < grids.Count; i++)
                {
                    if (i > 0) sb.Append('|');
                    var card = grids[i].GetCard();
                    if (card == null || card.cardConfig == null) { sb.Append(i).Append(",,"); continue; }
                    var cfg = card.cardConfig;
                    sb.Append(i).Append(',').Append(cfg.name).Append(',').Append(cfg.rarity + 1);
                }
                return sb.ToString();
            } catch (Exception e) { return "ERR:" + e.Message; }
        }
    }
}
