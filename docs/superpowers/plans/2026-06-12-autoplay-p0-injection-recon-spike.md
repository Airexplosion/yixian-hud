# 自动摆牌 P0:注入打通 + 侦察 spike 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在运行中的 YiXianPai.exe(Unity 2020.3 IL2CPP)上,用 frida-il2cpp-bridge 实测回答三个 make-or-break 问题——能否注入、能否从内存实时读对战状态、能否调用客户端自身的放牌方法并让 UI 同步——并验证 BepInEx 6 IL2CPP 生产工具链能加载;产出《侦察发现》文档供 P1–P6 计划使用。

**Architecture:** 侦察阶段用 Frida(frida-python + frida-il2cpp-bridge 编译成 agent)附加到游戏进程,枚举/hook/调用 il2cpp 方法,秒级迭代;待读法与动作方法验证清楚后,再在 BepInEx 插件里固化(本计划只验证 BepInEx 能加载,固化属于 P1+)。

**Tech Stack:** Frida(frida-tools、frida-compile)、frida-il2cpp-bridge、Node/npm(编译 agent)、BepInEx 6 (BepInEx.Unity.IL2CPP)、Il2CppDumper 产物(`il2cpp_recon/dump/dump.cs`,已存在)。

**前置事实(已侦察,见 spec §3):** 游戏进程 `YiXianPai.exe`,装于 `F:\SteamLibrary\steamapps\common\YiXianPai\`;IL2CPP;无反作弊;网络 Colyseus;大厅态 `GameRoomState/GamePlayer`;对战态为内存中 `LC.Google.Protobuf` 消息;`dump.cs`(31MB)已生成于 `C:\Users\zd117\Desktop\yxp辅助\il2cpp_recon\dump\`。

**本计划的"测试"形态:** 注入/侦察任务无法做传统单测,其**验证 = 对运行中的游戏跑探针脚本并观察输出/画面**。每个任务给出可运行脚本 + 明确的预期观察。少数纯逻辑产物(GameState 归一化、发现文档)用常规断言。

**工作目录:** 侦察相关代码与产物放仓库外 `C:\Users\zd117\Desktop\yxp辅助\autoplay_recon\`(不进 git),避免污染仓库;最终《侦察发现》文档写入仓库 `docs/superpowers/notes/`。

---

## Task 1: Frida 工具链与侦察目录

**Files:**
- Create: `C:\Users\zd117\Desktop\yxp辅助\autoplay_recon\` (目录)
- Create: `C:\Users\zd117\Desktop\yxp辅助\autoplay_recon\package.json`

- [ ] **Step 1: 建侦察目录并初始化 npm**

Run (PowerShell):
```powershell
$recon = "C:\Users\zd117\Desktop\yxp辅助\autoplay_recon"
New-Item -ItemType Directory -Force -Path $recon | Out-Null
Set-Location $recon
npm init -y
npm install frida-il2cpp-bridge @types/frida-gum frida-compile typescript
```
Expected: `node_modules/` 出现,`package.json` 含 `frida-il2cpp-bridge`、`frida-compile`。

- [ ] **Step 2: 安装 frida-python / frida-tools(用复用的 .venv)**

Run:
```powershell
Set-Location "C:\Users\zd117\Desktop\yxp辅助\yixian-card-counter"
.\.venv\Scripts\python.exe -m pip install frida frida-tools
.\.venv\Scripts\python.exe -c "import frida; print('frida', frida.__version__)"
```
Expected: 打印 frida 版本号(无 ImportError)。

- [ ] **Step 3: 确认游戏在运行**

Run:
```powershell
Get-Process YiXianPai -ErrorAction SilentlyContinue | Select-Object Id, ProcessName
```
Expected: 列出 `YiXianPai` 及其 PID。若无 → 提示用户启动游戏后再继续(本阶段全程需要游戏运行)。

- [ ] **Step 4: 提交工具链记录(仓库内 notes,不含 recon 代码)**

Create `docs/superpowers/notes/.gitkeep`(占位,确保目录存在),然后:
```powershell
Set-Location "C:\Users\zd117\Desktop\yxp辅助\yixian-card-counter"
New-Item -ItemType Directory -Force -Path docs\superpowers\notes | Out-Null
New-Item -ItemType File -Force -Path docs\superpowers\notes\.gitkeep | Out-Null
git add docs/superpowers/notes/.gitkeep
git commit -m "chore: 建 P0 侦察 notes 目录"
```
Expected: 提交成功。

---

## Task 2: 编译并运行最小 il2cpp-bridge agent —— 确认能注入

**Files:**
- Create: `autoplay_recon/agents/00_hello.ts`
- Create: `autoplay_recon/tsconfig.json`
- Create: `autoplay_recon/run.ps1`(编译+附加的便捷脚本)

- [ ] **Step 1: 写 tsconfig**

Create `autoplay_recon/tsconfig.json`:
```json
{
  "compilerOptions": {
    "target": "es2020",
    "module": "commonjs",
    "lib": ["es2020"],
    "types": ["frida-gum"],
    "strict": false,
    "esModuleInterop": true
  }
}
```

- [ ] **Step 2: 写最小 agent —— 打印 il2cpp 域里的镜像列表**

Create `autoplay_recon/agents/00_hello.ts`:
```typescript
import "frida-il2cpp-bridge";

Il2Cpp.perform(() => {
  console.log("[hello] il2cpp domain ok; assemblies:");
  for (const asm of Il2Cpp.domain.assemblies) {
    console.log("  " + asm.name);
  }
});
```

- [ ] **Step 3: 写编译+附加脚本**

Create `autoplay_recon/run.ps1`:
```powershell
param([Parameter(Mandatory=$true)][string]$Agent)
$recon = "C:\Users\zd117\Desktop\yxp辅助\autoplay_recon"
Set-Location $recon
# 编译 TS -> 单文件 agent.js
& ".\node_modules\.bin\frida-compile" "agents\$Agent.ts" -o "_agent.js"
if ($LASTEXITCODE -ne 0) { Write-Error "frida-compile failed"; exit 1 }
# 附加到游戏并加载 agent(无 --runtime 选项即可)
& "C:\Users\zd117\Desktop\yxp辅助\yixian-card-counter\.venv\Scripts\frida.exe" -n YiXianPai.exe -l "_agent.js" --runtime=qjs
```
说明:`--runtime=qjs`(QuickJS)对 frida-il2cpp-bridge 兼容性最好。`frida.exe` 进入交互 REPL,agent 的 console.log 会打印出来;观察后输入 `exit` 退出。

- [ ] **Step 4: 运行并观察 —— 注入是否成功**

Run:
```powershell
& "C:\Users\zd117\Desktop\yxp辅助\autoplay_recon\run.ps1" -Agent 00_hello
```
Expected: 打印 `[hello] il2cpp domain ok; assemblies:` 后跟一串程序集名(应含游戏主程序集与 `LucidSight.Runtime.ColyseusSDK` 等)。
- ✅ 成功 = 证明能注入、il2cpp 域可访问。把打印的程序集名记进发现文档(下一步)。
- ❌ 若报错(如 il2cpp 未就绪)→ 在 `Il2Cpp.perform` 前游戏需已进入主菜单(metadata 已加载);重试或等游戏加载完。

- [ ] **Step 5: 记录程序集列表到发现文档**

Create `docs/superpowers/notes/2026-06-12-p0-findings.md`,先写入:
```markdown
# P0 侦察发现

## 注入
- frida-il2cpp-bridge 注入:成功 / 失败 = <填>
- il2cpp 程序集列表:
  <粘贴 00_hello 输出>
```
Commit:
```powershell
Set-Location "C:\Users\zd117\Desktop\yxp辅助\yixian-card-counter"
git add docs/superpowers/notes/2026-06-12-p0-findings.md
git commit -m "docs(p0): 注入成功 + 程序集列表"
```

---

## Task 3: 定位游戏类所在镜像 + 找到 GameClient/状态根

**Files:**
- Create: `autoplay_recon/agents/01_find_classes.ts`
- Modify: `docs/superpowers/notes/2026-06-12-p0-findings.md`

- [ ] **Step 1: 写 agent —— 跨所有镜像搜索目标类并打印其字段**

Create `autoplay_recon/agents/01_find_classes.ts`:
```typescript
import "frida-il2cpp-bridge";

const TARGETS = ["GameClient", "GameRoomState", "GamePlayer", "GameGroupState"];

function findClass(name: string): Il2Cpp.Class | null {
  for (const asm of Il2Cpp.domain.assemblies) {
    try {
      const klass = asm.image.tryClass(name);
      if (klass) return klass;
    } catch (_) {}
  }
  return null;
}

Il2Cpp.perform(() => {
  for (const t of TARGETS) {
    const k = findClass(t);
    if (!k) { console.log(`[miss] ${t}`); continue; }
    console.log(`[found] ${t}  image=${k.image.name}`);
    for (const f of k.fields) {
      console.log(`    field ${f.type.name} ${f.name} @0x${f.offset.toString(16)} static=${f.isStatic}`);
    }
    for (const m of k.methods) {
      console.log(`    method ${m.returnType.name} ${m.name}(${m.parameterCount}) @${m.virtualAddress}`);
    }
  }
});
```
注意:`tryClass` 不存在时用 `image.class` 包 try/catch;以实际 frida-il2cpp-bridge 版本 API 为准(若 `tryClass` 报错,改用 `try { asm.image.class(name) } catch {}`)。

- [ ] **Step 2: 运行并观察**

Run:
```powershell
& "C:\Users\zd117\Desktop\yxp辅助\autoplay_recon\run.ps1" -Agent 01_find_classes
```
Expected: 打印 `GameClient` / `GameRoomState` / `GamePlayer` 所在 image 名 + 字段/方法清单。重点关注 `GameClient` 上是否有持有 `ColyseusRoom`/当前对战态的字段或单例访问入口。

- [ ] **Step 3: 找 GameClient 单例实例**

追加 agent `autoplay_recon/agents/02_gameclient_instances.ts`:
```typescript
import "frida-il2cpp-bridge";

function findClass(name: string): Il2Cpp.Class | null {
  for (const asm of Il2Cpp.domain.assemblies) {
    try { const k = asm.image.class(name); if (k) return k; } catch (_) {}
  }
  return null;
}

Il2Cpp.perform(() => {
  const gc = findClass("GameClient");
  if (!gc) { console.log("no GameClient"); return; }
  // 堆里枚举所有 GameClient 实例(应只有一个,单例)
  const insts = Il2Cpp.gc.choose(gc);
  console.log(`GameClient instances: ${insts.length}`);
  for (const inst of insts) {
    for (const f of gc.fields) {
      if (f.isStatic) continue;
      try { console.log(`  ${f.name} = ${inst.field(f.name).value}`); } catch (_) {}
    }
  }
});
```
Run: `& "...\run.ps1" -Agent 02_gameclient_instances`
Expected: 找到 1 个 GameClient 实例,打印其字段值(从中找到指向 Room / 对战态 / 本地玩家的字段)。

- [ ] **Step 4: 记录发现**

把 Task3 的 image 名、GameClient 字段(尤其指向 Room/对战态的)、单例枚举结果写入 `2026-06-12-p0-findings.md` 的「## 状态根」一节,commit:
```powershell
git add docs/superpowers/notes/2026-06-12-p0-findings.md
git commit -m "docs(p0): 定位 GameClient/GameRoomState 及单例"
```

---

## Task 4: 实时读对战状态(牌面/手牌)—— 验证"内存读实时态"

**Files:**
- Create: `autoplay_recon/agents/03_read_state.ts`
- Modify: `docs/superpowers/notes/2026-06-12-p0-findings.md`

> 前提:Task3 已找到从 GameClient(或某状态管理单例)到「本地玩家对战态」的字段路径。对战态是 `LC.Google.Protobuf` 消息——可能挂在某 manager 上,也可能需 hook 反序列化。本任务两条路都试,取先跑通者。

- [ ] **Step 1: 路 A —— 直接顺指针读对战态**

Create `autoplay_recon/agents/03_read_state.ts`(占位路径按 Task3 实测填 `<...>`):
```typescript
import "frida-il2cpp-bridge";

function findClass(name: string): Il2Cpp.Class | null {
  for (const asm of Il2Cpp.domain.assemblies) {
    try { const k = asm.image.class(name); if (k) return k; } catch (_) {}
  }
  return null;
}

Il2Cpp.perform(() => {
  const gc = findClass("GameClient")!;
  const inst = Il2Cpp.gc.choose(gc)[0];
  // 按 Task3 实测的字段名顺藤摸瓜到对战态对象,例如:
  // const battle = inst.field("<battleStateField>").value as Il2Cpp.Object;
  // 打印它的字段(找 board/hand/hp/qi 等)
  // for (const f of battle.class.fields) {
  //   try { console.log(`${f.name} = ${battle.field(f.name).value}`); } catch (_) {}
  // }
  console.log("TODO: 用 Task3 实测的字段路径填好上面注释");
});
```

- [ ] **Step 2: 路 B —— hook protobuf 反序列化捕获对战态**

若路 A 拿不到稳定指针,改 hook 客户端处理 ROOM_DATA 的入口。先在 `dump.cs` 里定位候选(已知 `ProtobufData{type,data}` + Colyseus `Room.OnMessage`):
```powershell
# 在 dump 里找处理消息/反序列化的方法名候选
Set-Location "C:\Users\zd117\Desktop\yxp辅助\il2cpp_recon\dump"
Select-String -Path dump.cs -Pattern "OnMessage|ParseMessage|HandleData|Deserialize|MergeFrom" | Select-Object -First 30
```
Expected: 列出候选方法。挑最像「按 type 分发对战消息」的,在 agent 里 `Il2Cpp.Interceptor` hook 它,打印 type 字符串 + 解析后的对象,确认能拿到对战态。

- [ ] **Step 3: 运行 + 边玩边读,验证实时性**

进入一局对战(人机/练习),运行选定的读法 agent,每秒打印一次当前牌面/手牌:
```powershell
& "C:\Users\zd117\Desktop\yxp辅助\autoplay_recon\run.ps1" -Agent 03_read_state
```
Expected: 打印的牌面/手牌**与游戏画面一致**,且你在游戏里放/收牌时打印**实时跟着变**。

- [ ] **Step 4: 与代理解码对拍**

同一局,对照现有代理解码出的 view-model(可同时跑 `.\.venv\Scripts\python.exe app.py` 的 replay 或现有记牌器),逐项核对牌名/数量/血/灵气一致。
Expected: 关键字段一致(允许时序上内存读更超前)。

- [ ] **Step 5: 记录读法**

把可用的读法(路 A 字段路径 或 路 B hook 点)、对战态类名与关键字段偏移、对拍结果写入发现文档「## 读状态」,commit:
```powershell
git add docs/superpowers/notes/2026-06-12-p0-findings.md
git commit -m "docs(p0): 实时读对战态的可用路径 + 对拍一致"
```

---

## Task 5: 定位放牌动作方法(hook 学习其签名)—— make-or-break 上半

**Files:**
- Create: `autoplay_recon/agents/04_hook_place.ts`
- Modify: `docs/superpowers/notes/2026-06-12-p0-findings.md`

- [ ] **Step 1: 在 dump 里枚举放牌候选方法**

Run:
```powershell
Set-Location "C:\Users\zd117\Desktop\yxp辅助\il2cpp_recon\dump"
Select-String -Path dump.cs -Pattern "MoveCard|PlaceCard|OnDrop|OnCardDrop|DragCard|PutCard|SetCard|MoveCardReq|InsertCard|OnDrag" | Select-Object -First 40
```
Expected: 一批候选方法名(C# UI/controller 层)。记下最像「手牌→牌面放置」的 3–5 个候选(类名.方法名)。

- [ ] **Step 2: hook 候选方法,人工放一次牌,看哪个触发**

Create `autoplay_recon/agents/04_hook_place.ts`(候选名按 Step1 填):
```typescript
import "frida-il2cpp-bridge";

const CANDIDATES: Array<[string, string]> = [
  // ["<ClassName>", "<MethodName>"],   // 按 Step1 填入候选
];

function findClass(name: string): Il2Cpp.Class | null {
  for (const asm of Il2Cpp.domain.assemblies) {
    try { const k = asm.image.class(name); if (k) return k; } catch (_) {}
  }
  return null;
}

Il2Cpp.perform(() => {
  for (const [cls, mtd] of CANDIDATES) {
    const k = findClass(cls);
    if (!k) { console.log(`[miss class] ${cls}`); continue; }
    const methods = k.methods.filter((m) => m.name === mtd);
    for (const m of methods) {
      try {
        m.implementation = function (...args: any[]) {
          console.log(`[HIT] ${cls}.${mtd}(${m.parameterCount}) args=[${args.join(", ")}]`);
          return m.invoke(this, ...args);   // 透传,不改行为
        };
        console.log(`[hooked] ${cls}.${mtd} params=${m.parameterCount}`);
      } catch (e) { console.log(`[hook fail] ${cls}.${mtd}: ${e}`); }
    }
  }
});
```

- [ ] **Step 3: 运行 hook,在游戏里手动拖一张手牌到牌面**

Run: `& "...\run.ps1" -Agent 04_hook_place`,然后在游戏里**手动放一张牌**。
Expected: 某个候选打印 `[HIT] ...args=[...]` → 这就是放牌入口。记下:类名、方法名、参数个数与各参数的值(对应手牌槽位/目标格位等)。多放几张不同位置,推断参数语义。

- [ ] **Step 4: 记录放牌方法签名**

把命中的放牌方法(类.方法、参数语义:如 `(srcZone, srcSlot, dstZone, dstSlot)` 还是 `(handIndex, boardIndex)`)写入发现文档「## 放牌方法」,commit。

---

## Task 6: 程序化调用放牌方法 —— make-or-break 下半(UI 是否同步)

**Files:**
- Create: `autoplay_recon/agents/05_call_place.ts`
- Modify: `docs/superpowers/notes/2026-06-12-p0-findings.md`

- [ ] **Step 1: 写 agent —— 主动调用放牌方法放一张手牌**

Create `autoplay_recon/agents/05_call_place.ts`(类名/方法名/实例获取/参数按 Task5 实测填):
```typescript
import "frida-il2cpp-bridge";

function findClass(name: string): Il2Cpp.Class | null {
  for (const asm of Il2Cpp.domain.assemblies) {
    try { const k = asm.image.class(name); if (k) return k; } catch (_) {}
  }
  return null;
}

// 暴露一个 rpc,手动触发一次放牌,便于观察画面
rpc.exports = {
  place(handSlot: number, boardSlot: number) {
    Il2Cpp.perform(() => {
      const cls = findClass("<PlaceClass>")!;
      const inst = Il2Cpp.gc.choose(cls)[0];     // 或按 Task3 的单例路径取
      const m = cls.method("<PlaceMethod>");      // 必要时按参数个数选重载
      console.log(`calling place(${handSlot}, ${boardSlot})`);
      m.invoke(inst, handSlot, boardSlot);        // 参数顺序/类型按 Task5
      console.log("called");
    });
  },
};
```
配套 Python 触发器 `autoplay_recon/call_place.py`:
```python
import frida, sys
pid = [p.pid for p in frida.enumerate_processes() if p.name == "YiXianPai.exe"][0]
session = frida.attach(pid)
with open("_agent.js", "r", encoding="utf-8") as f:
    script = session.create_script(f.read(), runtime="qjs")
script.on("message", lambda m, d: print("MSG", m))
script.load()
hand = int(sys.argv[1]); board = int(sys.argv[2])
script.exports_sync.place(hand, board)
input("已调用,观察游戏画面后回车退出...")
```

- [ ] **Step 2: 编译 agent**

Run:
```powershell
Set-Location "C:\Users\zd117\Desktop\yxp辅助\autoplay_recon"
& ".\node_modules\.bin\frida-compile" "agents\05_call_place.ts" -o "_agent.js"
```
Expected: 生成 `_agent.js`,无编译错误。

- [ ] **Step 3: 进对战准备阶段,程序化放一张牌,观察画面**

确保游戏在某局的摆牌阶段、手里有牌。Run:
```powershell
& "C:\Users\zd117\Desktop\yxp辅助\yixian-card-counter\.venv\Scripts\python.exe" call_place.py 0 0
```
Expected(**这是整个 P0 的核心观察**):
- ① 游戏**接受**该放置(那张手牌出现在 0 号牌面格)。
- ② 关键:UI 是否**立即**反映?
  - 立即变 → 客户端做乐观更新 ⟹ ActionExecutor 调它即可,最理想。
  - 仅在服务器广播后变(短暂延迟但最终一致、无错乱)→ 仍可用,ActionExecutor 的读回校验改为"等广播后"。
  - 出现错乱/卡死/被服务器拒 → 说明该方法不是正确的客户端入口,回 Task5 换候选。

- [ ] **Step 4: 用 Task4 的读法读回,确认状态一致**

放置后立即跑 `03_read_state` 读法(或在 agent 里放置后直接读),确认内存态里 0 号格 = 刚放的牌、手牌少一张。
Expected: 状态读回与预期一致。

- [ ] **Step 5: 记录结论(P0 结案)**

把核心结论写入发现文档「## 执行语义(make-or-break 结论)」:放牌方法可调用 ✓/✗、UI 同步方式(乐观/等广播/错乱)、读回校验时序建议。Commit:
```powershell
git add docs/superpowers/notes/2026-06-12-p0-findings.md
git commit -m "docs(p0): 放牌方法可程序化调用 + UI 同步结论"
```

---

## Task 7: 验证 BepInEx 6 IL2CPP 生产工具链能加载

**Files:**
- Create: `F:\SteamLibrary\steamapps\common\YiXianPai\` 下的 BepInEx 文件(由安装包解压)
- Create: `autoplay_recon/bepinex/HelloPlugin/`(最小插件工程)
- Modify: `docs/superpowers/notes/2026-06-12-p0-findings.md`

> 与 Frida 侦察并行/其后做都行;目的仅是证明**生产路径**(BepInEx + Il2CppInterop)能在本游戏跑起来,为 P1+ 把侦察结论固化做准备。本任务不写业务逻辑。

- [ ] **Step 1: 下载 BepInEx 6 IL2CPP (win-x64) 并解压到游戏根**

Run:
```powershell
$recon = "C:\Users\zd117\Desktop\yxp辅助\autoplay_recon"
Set-Location $recon
gh release download -R BepInEx/BepInEx --pattern "*Unity.IL2CPP-win-x64*.zip" --dir $recon --clobber
# 解压到游戏目录
$zip = Get-ChildItem "$recon\*Unity.IL2CPP-win-x64*.zip" | Select-Object -First 1
Expand-Archive -Path $zip.FullName -DestinationPath "F:\SteamLibrary\steamapps\common\YiXianPai" -Force
```
Expected: 游戏根出现 `BepInEx/`、`winhttp.dll`、`doorstop_config.ini`。

- [ ] **Step 2: 首启游戏生成 Il2CppInterop 程序集**

手动启动游戏(Steam 或直接 `YiXianPai.exe`),等其加载到主菜单后关闭。
Run(验证生成物):
```powershell
Get-ChildItem "F:\SteamLibrary\steamapps\common\YiXianPai\BepInEx\interop\*.dll" -ErrorAction SilentlyContinue | Measure-Object | Select-Object Count
```
Expected: `interop/` 下生成了上百个 interop DLL(含游戏程序集的托管包装)。`BepInEx/LogOutput.log` 存在。
- ❌ 若首启失败/无 interop → 检查 BepInEx 版本是否为 IL2CPP 变体、`BepInEx/config/BepInEx.cfg` 的 `[IL2CPP] UnityVersion` 是否需手填 `2020.3.49`。

- [ ] **Step 3: 写最小 BepInEx 插件(只打日志)**

Create `autoplay_recon/bepinex/HelloPlugin/HelloPlugin.csproj`:
```xml
<Project Sdk="Microsoft.NET.Sdk">
  <PropertyGroup>
    <TargetFramework>net6.0</TargetFramework>
    <AssemblyName>YiXianAuto.Hello</AssemblyName>
    <LangVersion>latest</LangVersion>
    <RestoreAdditionalProjectSources>https://nuget.bepinex.dev/v3/index.json</RestoreAdditionalProjectSources>
  </PropertyGroup>
  <ItemGroup>
    <PackageReference Include="BepInEx.Unity.IL2CPP" Version="6.0.0-be.*" IncludeAssets="compile" />
  </ItemGroup>
</Project>
```
Create `autoplay_recon/bepinex/HelloPlugin/Plugin.cs`:
```csharp
using BepInEx;
using BepInEx.Unity.IL2CPP;
using BepInEx.Logging;

[BepInPlugin("yixianauto.hello", "YiXianAuto Hello", "0.0.1")]
public class HelloPlugin : BasePlugin
{
    public override void Load()
    {
        Log.LogInfo("[YiXianAuto] hello plugin loaded — il2cpp interop ready");
    }
}
```

- [ ] **Step 4: 构建插件并放入 plugins**

Run:
```powershell
Set-Location "C:\Users\zd117\Desktop\yxp辅助\autoplay_recon\bepinex\HelloPlugin"
dotnet build -c Release
Copy-Item ".\bin\Release\net6.0\YiXianAuto.Hello.dll" "F:\SteamLibrary\steamapps\common\YiXianPai\BepInEx\plugins\" -Force
```
Expected: 构建成功,DLL 拷入 `BepInEx/plugins/`。

- [ ] **Step 5: 启动游戏,确认插件加载日志**

启动游戏,等进主菜单后关闭。Run:
```powershell
Select-String -Path "F:\SteamLibrary\steamapps\common\YiXianPai\BepInEx\LogOutput.log" -Pattern "YiXianAuto"
```
Expected: 日志里出现 `[YiXianAuto] hello plugin loaded — il2cpp interop ready`。
- ✅ = 生产工具链验证通过。

- [ ] **Step 6: 记录 BepInEx 验证结果**

把 BepInEx 版本、interop 生成情况、插件加载日志写入发现文档「## BepInEx 工具链」,commit。

---

## Task 8: P0 结案 —— 汇总发现 + 给 P1 的输入

**Files:**
- Modify: `docs/superpowers/notes/2026-06-12-p0-findings.md`

- [ ] **Step 1: 写「## 结论与对 P1 的输入」小节**

在发现文档末尾汇总(基于实测填写):
- 注入:Frida ✓;BepInEx ✓。
- 读状态:采用路 A/路 B = <填>;对战态根 = `<类名/字段路径>`;关键字段偏移表。
- 放牌:方法 = `<类.方法(参数语义)>`;UI 同步 = 乐观/等广播;读回校验时序 = <填>。
- 对 P1 的输入:StateReader 用哪种读法、需要绑定哪些 il2cpp 类;ActionExecutor 首个动作的精确调用配方。
- 仍未知/留给 P2 的:其余动作方法(换牌/合成/突破/选项)的定位待 P2 逐个做。

- [ ] **Step 2: 提交并收尾**

```powershell
Set-Location "C:\Users\zd117\Desktop\yxp辅助\yixian-card-counter"
git add docs/superpowers/notes/2026-06-12-p0-findings.md
git commit -m "docs(p0): 侦察结案 — 读法/放牌/工具链结论 + P1 输入"
```
Expected: P0 完成。下一步据此为 P1(StateReader)写详细计划。

---

## P0 验收(Definition of Done)

- [ ] Frida 注入成功,能枚举 il2cpp 类。
- [ ] 能从内存**实时**读到牌面/手牌,且与代理解码对拍一致。
- [ ] 找到放牌方法,能**程序化调用**放一张牌,且明确了 UI 同步语义(乐观/等广播/不可用)。
- [ ] BepInEx 6 IL2CPP 插件能加载并打日志。
- [ ] 全部结论写入 `docs/superpowers/notes/2026-06-12-p0-findings.md`,作为 P1–P6 计划的事实输入。

## 之后(不在本计划内)

P0 拿到真实读法/方法/偏移后,再分别写:**P1 StateReader**、**P2 ActionExecutor(其余动作)**、**P3 yisim Node 边车 + SimClient**、**P4 大脑移植**、**P5 IMGUI overlay**、**P6 整局全自动 + 安全** 的详细计划。每个计划都产出可独立验证的软件。
