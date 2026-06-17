# YiXianHUD — 弈仙牌同域注入 HUD

在弈仙牌(YiXianPai)游戏内直接叠加显示的辅助 HUD,基于网络封包记牌(不截屏、不识图):

- **记牌器** — 每张牌牌库剩余数(卡上「剩X」)
- **造伤预估** — T1–T8 八回合伤害(solo / 对打对手两种模式)
- **对手命/修预估** + **危险牌警告**
- **跳过战斗** — 一键跳过战斗动画回到摆牌
- **卡池浏览(Tab)** — 游戏内完整卡牌图集 + 各牌剩余 + 手牌/已空/危险切换置顶
- **悬浮换牌(D)** — 鼠标悬浮手牌按 D 直接换牌
- 注入文字位置、快捷键均可在设置面板自定义

## ⚠️ 本仓库不含任何游戏官方文件

不包含弈仙牌 / Unity 的任何 DLL、反编译代码或受版权保护的游戏资源。

- 仓库已提供**本项目源码编译出的** `native_hud/_build/YiXianHud32.dll`,所以**打包 / 运行 exe 不需要任何游戏文件**。
- 如需自行编译 C# 注入层(`native_hud/csharp`),要自备游戏 / Unity 的引用 DLL,放到 `native_hud/_refs/`(见该目录 `README`)。这些是游戏方版权材料,请勿提交或分发。

## 下载使用

到 [Releases](../../releases) 下载 `YiXianHUD.exe`(由 GitHub Actions 自动打包,自带 node,无需额外环境)。

1. **关闭**弈仙牌
2. 双击 `YiXianHUD.exe`,首次会让你选 `YiXianPai.exe`
3. 游戏经 frida 启动并注入 HUD,进对局后自动显示
4. 托盘 / 设置窗口可开关各元素、调位置、改快捷键

## 从源码打包

需 Python 3.11 + Node 20:

```bash
pip install pyinstaller frida blackboxprotobuf msgpack pystray pillow
python build_hud.py        # 产出 YiXianHUD.exe
```

## 发布

打 tag 即自动构建并发布到 Releases:

```bash
git tag v1.0.0
git push origin v1.0.0
```

## 致谢

- 记牌核心 / yisim 伤害引擎 — 本项目早期形态 [yixian-card-counter](https://github.com/Airexplosion/yixian-card-counter)
- 注入框架 — [frida](https://frida.re) + [frida-il2cpp-bridge](https://github.com/vfsfitvnm/frida-il2cpp-bridge)

## 免责声明

本项目仅供学习与个人研究。修改游戏运行行为可能违反游戏服务条款,使用风险自负。
