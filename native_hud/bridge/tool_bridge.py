# -*- coding: utf-8 -*-
"""Same-domain data bridge (replaces the proxy+web tool, keeps yisim):
  · StateReader (frida hook ProtobufParser) → addon.process_msgpack → state_queue   [REUSED]
  · runtime.start_consumer → Counter/OpponentTracker → build_view_model → push(vm)   [REUSED]
  · push(vm): real remaining → HUD.SetRemaining ; opponent → HUD.SetOpponent
  · yisim marginal loop (Node) → HUD.SetMarginal
Run alongside the game. Ctrl-C to stop (HUD persists in-game)."""
import sys, os, json, time, threading, subprocess
from pathlib import Path
import frida

# ── Paths (repo-relative; override build artefacts via env) ───────────────────
# REPO = this checkout's root (…/native_hud/bridge/tool_bridge.py → parents[2]).
# Build products (frida-compiled agents + dotnet-built C# DLLs) are NOT in the
# repo (copyright / gitignored); default them to native_hud/_build and let env
# vars point elsewhere. NOTHING is hardcoded to a developer machine anymore.
REPO = Path(__file__).resolve().parents[2]
NATIVE = REPO / "native_hud"
BUILD = Path(os.environ.get("YX_HUD_BUILD", NATIVE / "_build"))
for _p in (REPO, REPO / "proxy", REPO / "autoplay" / "inject"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import runtime                       # reused (build_view_model/Counter/OpponentTracker)
import state_queue as _sq
from state_queue import new_game_event, round_ended_event
from statereader import StateReader  # reused frida hook → addon

AGENT   = os.environ.get("YX_AGENT_GLUE",    str(BUILD / "bot_glue3.agent.js"))
CAPTURE = os.environ.get("YX_AGENT_CAPTURE", str(BUILD / "capture.agent.js"))
HUD     = os.environ.get("YX_HUD_DLL",       str(BUILD / "YiXianHud19.dll"))
SIM     = os.environ.get("YX_SIM_DLL",       str(BUILD / "YiXianSimData.dll"))
NODE_MARGINAL = str(NATIVE / "bridge" / "yisim_marginal.js")
HUD_T = "YiXianBot.Hud19"; SIM_T = "YiXianBot.SimData"

# ── HUD frida session ──
_hud_session = frida.attach("YiXianPai.exe")
_hud = _hud_session.create_script(open(AGENT, encoding="utf-8").read())
_hud.load(); _ex = _hud.exports_sync
_ex.load_bot(open(HUD, "rb").read()); _ex.load_bot(open(SIM, "rb").read())
for _t in ["Hud","Hud2","Hud3","Hud4","Hud5","Hud6","Hud7","Hud8","Hud9","Hud10","Hud11","Hud12","Hud13","Hud14","Hud15","Hud16","Hud17","Hud18","BotUI","BotUI2"]:
    try: _ex.call_s("YiXianBot."+_t, "Hide", [])
    except Exception: pass
print("Show HUD:", _ex.call_s(HUD_T, "Show", []))
_hud_lock = threading.Lock()

def hud_str(method, s):
    with _hud_lock:
        try: return _ex.call_str(HUD_T, method, s)
        except Exception as e: return {"err": str(e)}

def my_consumer(push):
    from proxy_view import build_view_model, Counter, OpponentTracker
    import addon as _addon
    counter = Counter(); opp_tracker = OpponentTracker()
    last_round = [0]
    while True:
        try: state = _sq.state_queue.get(timeout=0.5)
        except Exception: continue
        rn = int(getattr(state, "round_num", 0) or 0)
        # 新局: StartGameResp触发, 或(练习赛)回合数从>1跳回<=1
        if new_game_event.is_set() or (last_round[0] > 1 and rn <= 1):
            try: new_game_event.clear()
            except Exception: pass
            counter.reset(); opp_tracker.reset()
            print("[reset] 新局 counter重置 (round %d->%d)" % (last_round[0], rn), flush=True)
        last_round[0] = rn
        if round_ended_event.is_set():
            try: round_ended_event.clear()
            except Exception: pass
        try:
            counter.observe(state); opp_tracker.observe(state)
            vm = build_view_model(state, counter=counter, last_battle=_addon.last_battle, opp_tracker=opp_tracker)
            push(vm)
        except Exception as e:
            print("[consumer] %s" % e, flush=True)

# ── consumer push: remaining (+ opponent later) ──
_latest = {"vm": None}
def push(vm):
    try:
        _latest["vm"] = vm
        rem = (vm.get("counter") or {}).get("remaining") or {}
        zl = {k:v for k,v in rem.items() if "震雷" in k or "震雷剑" in k}
        if zl: print("[push] 震雷剑 remaining=%s reroll_events=%d" % (zl, len(__import__('addon').reroll_events)), flush=True)
        print("[push] vm keys=%s remaining=%d sample=%s" % (list(vm.keys()), len(rem), list(rem.items())[:4]), flush=True)
        if rem:
            # The HUD matches CardConfig.name EXACTLY, but `remaining` keys are
            # canonical (merged pair name + mixed ·/• separators). Expand to
            # every name-form the HUD could look up so it never shows "剩?" for
            # a card whose count we actually know. (See proxy_view doc.)
            from proxy_view import remaining_with_aliases
            payload = remaining_with_aliases(rem)
            r = hud_str("SetRemaining", "|".join("%s:%s" % (k, v) for k, v in payload.items()))
            print("[push] SetRemaining %d keys->%d aliases -> %s" % (len(rem), len(payload), r), flush=True)
    except Exception as e:
        print("push err:", e, flush=True)

# ── yisim marginal ──
def parse_board(s):
    out = []
    if not s or s.startswith("ERR"): return out
    for part in s.split("|"):
        f = part.split(",")
        if len(f) >= 3:
            out.append({"slot": int(f[0]), "name": f[1], "level": int(f[2]) if f[2] else 1})
    return out

def marginal_loop():
    while True:
        try:
            vm = _latest["vm"]
            me = (vm or {}).get("me") or {}
            board = me.get("board") or []          # [{name,level}|null...] 真实等级
            talents = me.get("fates") or []        # 仙命/天衍
            if any(c for c in board):
                payload = json.dumps({"board": board, "talents": talents}, ensure_ascii=False)
                p = subprocess.run(["node", NODE_MARGINAL], input=payload.encode("utf-8"),
                                   capture_output=True, timeout=20)
                res = json.loads(p.stdout.decode("utf-8", "replace") or "{}")
                marg = res.get("marginal", {})
                print("[marg] full=%s marginal=%s talents=%d" % (res.get("full"), marg, len(talents)), flush=True)
                if marg:
                    hud_str("SetMarginal", "|".join("%s:%s" % (k, v) for k, v in marg.items()))
            time.sleep(1.5)
        except Exception as e:
            print("marg err:", e); time.sleep(2)

def main():
    _cnt = [0]
    def _onmsg(d, t):
        _cnt[0]+=1
        if _cnt[0] % 30 == 1: print("[hook] msg#%d dir=%s type=%s qsize=%d" % (_cnt[0], d, t, __import__('state_queue').state_queue.qsize()), flush=True)
        if not hasattr(_onmsg, "_seen"): _onmsg._seen=set()
        key=(d,t)
        if key not in _onmsg._seen:
            _onmsg._seen.add(key); print("[type] dir=%s type=%s" % (d,t), flush=True)
        if any(k in (t or "") for k in ("Replace","Reroll","Refine","Card")):
            print("[event] dir=%s type=%s reroll_events=%d" % (d, t, len(__import__('addon').reroll_events)), flush=True)
    sr = StateReader(CAPTURE, on_update=_onmsg)
    sr.start()
    print(">>> StateReader 已挂 (协议hook → counter)")
    threading.Thread(target=lambda: my_consumer(push), daemon=True).start()
    threading.Thread(target=marginal_loop, daemon=True).start()
    print(">>> bridge running (剩X真值 + 边际造伤), Ctrl-C 停 <<<", flush=True)
    try:
        while True: time.sleep(1)
    except KeyboardInterrupt:
        pass
    sr.stop(); _hud_session.detach()

if __name__ == "__main__":
    main()
