# P1 StateReader 侦察

## 入站状态解码点(已实测)
- `ProtobufParser.DecodeFromBase64(System.String typeName, System.String base64)` (2 参版) 承载**全部入站消息**。
  - 实测捕获:`ReplaceCardResp`(换牌响应)、`Pong`(心跳)、`BattleResult`(战斗结果)。
  - `DecodeFromProtobufData(ProtobufData)` **不用于入站**(挂了也不亮)。
  - 泛型 `Decode(byte[])` / `DecodeFromBase64(string)` 1 参版虚地址为 NULL(未实例化),跳过。
- hook 写法:`.implementation` + `NativeFunction(virtualAddress,'pointer',[argc+2 个 pointer])` 转发
  (callArgs = [this.handle, ...args.map(a=>a.handle), method.handle])。注意先判 `virtualAddress.isNull()` 跳过泛型。

## StateReader 方案(确定)
- hook `DecodeFromBase64(typeName, base64)` → onEnter 读 `(typeName, base64)` 两个字符串 →
  base64 即原始 protobuf,**复用现成 `proxy/decoder.py` 解码** → 归一成 GameState。
- 真·实时(客户端解码当下)、进程内、复用已验证解码器、不碰 ILRuntime 反射。
- 待办:① 抓一个完整状态消息(GameStatus 类)的 base64,用现有解码器解出来对拍代理;
  ② 列全入站消息类型谱(GameStatus/各 Resp/BattleResult…)。

## 🟢 StateReader 端到端验证成功(实测)
- 入站消息类型谱(一回合切换捕获):`GameStatus`(3348B,完整状态)/ `PlayerData`(658B)/ `LifeRankStatus`(290B)/ `ReplaceCardResp` / `RefineCardResp` / `Pong`。
- **GameStatus = 完整牌面/手牌状态消息**;`DecodeFromBase64(typeName, base64)` 的 base64 即原始 protobuf。
- 验证:把注入抓到的 `GameStatus.bin`(3348B)喂给现有 `proxy/game_state.parse_game_state(blackboxprotobuf.decode_message(raw))`:
  - 解出 round=17、8 名玩家,每人 board(8)+ hand 全部正确(player0 stellarwind = 自己)。
  - 即注入 hook 的字节 → 现有解码管道 → 完整 GameState,**零改动复用**。
- ⟹ **StateReader 实现路径锁定**:
  1. agent hook `DecodeFromBase64`,`send({type, base64})` 给 Python;
  2. Python 按 type 路由:`GameStatus`→parse_game_state;`PlayerData`/`*Resp`/`BattleResult`→对应 shadow_state apply_*;
  3. 复用现有 shadow_state + proxy_view 维护运行态并产出 GameState。
- 验证脚本:`autoplay_recon/validate_statereader.py`;捕获器:`autoplay_recon/run_capture.py` + `agents/08_capture.ts`。

## 🟢🟢 P1 完成:实时 StateReader 跑通(双向)
- agent 双向 hook:`DecodeFromBase64`(入站)+ `EncodeToProtobufData`(出站,读返回的 ProtobufData{type,data})。
- Python 把每条 `{dir,type,base64}` 构造成 `mp=["data",{type,data}]`,调 **现有 `addon.process_msgpack(mp, from_client=(dir=="out"))`** —— 完全复用代理的分派 + shadow_state + game_state,零改写。
- 实测(对局中,round 21):
  - 入站 GameStatus/PlayerData → shadow RESET/刷新,牌面手牌正确;自动识别 user UID。
  - 出站 MoveCardReq → **板面逐张实时更新**(撤回的牌实时回手牌);RefineCardReq/Resp → 炼化 + 修为实时(修为+1=120…)。
  - shadow_state 全程维护**真实时状态**,与画面一致。
- 真·实时、进程内、免代理、无脱节(读客户端自身动作,非注入伪造)。
- 原型代码:`autoplay_recon/statereader_live.py` + `agents/08_capture.ts`(待 P4 接线时移植进 autoplay 包)。
- ⟹ StateReader 方案完全验证;后续仅为工程化(把原型并入仓库 autoplay 包 + 接 PlayerData 的修为/数值字段细化)。
