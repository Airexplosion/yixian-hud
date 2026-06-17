# 弈仙牌 game-api 活体验证报告 — 2026-06-16

`YiXianApi.dll` 注入运行中的游戏,逐个实机调用(`validate.py` + `apicall.py`)。

环境:practice 对局;先在**修炼阶段(摆牌)**跑非战斗子集,再在**斗法阶段(战斗)**验战斗链路。

| API | 验证 | 实测返回 / 说明 |
|---|---|---|
| `battle.skip` | ✔ 斗法阶段实测 | `ok:dispatched` → 跳回摆牌(`scene.current`=0)+ 发牌 + 角色归位(用户画面确认,与 Hud31 一致) |
| `battle.force_break` | ✔ 经 skip 链路 | skip 内部即 `forceBreakExecuting`,随 skip 一并验证 |
| `battle.is_battling` | ✔ 实测 | 战斗中 `ok:1`,摆牌中 `ok:0` |
| `scene.change` | ✔ 经 skip 链路 | skip 内部 `ChangeSceneType(修炼阶段)` 实测生效(scene 由 1→0);直调 API 返回 `ok:<scene>` |
| `scene.current` | ✔ 实测 | 摆牌 `ok:0`、战斗 `ok:1` |
| `game_status.req` | ✔ 实测 | `ok:requested` |
| `network.auto_select` | ✔ 实测 | `ok:dispatched:ping=3` |
| `network.analyze` | ✔ 实测 | `ok:dispatched:ping=3` |
| `network.optimize` | ✔ 实测 | `ok:dispatched`(会重载 Home,有打断性) |
| `state.round` | ✔ 实测 | `{"round":1}` |
| `state.self` | ✔ 实测 | `{"life":100,"maxHp":40,"tiPo":0,"level":1}`(第1回合合理值) |

## 修复记录

- `state.round`/`state.self` 初次实测 `not found`:无参方法误标 `call_str`(按 string 参数找方法)。改 `call_s`(空参)后实测通过。`call`=入参类型 / `ret`=返回解析,两者独立。

## 复现

```bash
# 非战斗子集(在摆牌阶段 attach 运行)
YX_ATTACH=1 python native_hud/api/validate.py

# 战斗链路(在斗法阶段)
YX_ATTACH=1 python native_hud/bridge/apicall.py YiXianBot.BattleApi IsBattling   # -> ok:1
YX_ATTACH=1 python native_hud/bridge/apicall.py YiXianBot.BattleApi Skip          # -> 跳回摆牌
```
