# `_refs` — 编译用引用 DLL(本仓库不含)

仅当你要**自行编译** `native_hud/csharp/Hud.csproj` 时,才需要把弈仙牌 / Unity 的引用 DLL
放进此目录。`.gitignore` 已把 `*.dll` 挡在版本库外——**这些是游戏方版权材料,切勿提交或分发**。

需要的 DLL(从你自己的游戏安装里提取,通常在 `YiXianPai_Data/Managed/`):

| DLL | 来源 |
|-----|------|
| `DarkSun.HotUpdate.dll` | 弈仙牌 |
| `DarkSun.Utility.dll` | 弈仙牌 |
| `wProtobuf.dll` | 弈仙牌 |
| `UnityEngine.CoreModule.dll` 等 `UnityEngine.*` | Unity |
| `Unity.TextMeshPro.dll` | Unity |
| `UniRx.dll` / `UniTask.dll` | 第三方(随游戏分发) |

> 注:仓库已提供**预编译好的** `native_hud/_build/YiXianHud32.dll`(本项目源码的产物)。
> 只是**打包 / 运行 exe** 的话,完全不需要本目录——直接 `python build_hud.py` 即可。
