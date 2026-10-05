# LootWeave

[English](README.md) · 简体中文

把装备词条、角色构筑和游戏机制联系起来，帮助玩家判断物品怎样用、是否值得换装，以及为什么值得保留。

LootWeave 是一个开源的 Windows 本地装备决策助手原型，无需玩家自行填写词条权重。仓库目前包含可运行的本地开发实现；唯一可执行的游戏知识包是合成夹具。Deskrawl 是研究对象，Diablo II、III、IV 仍是未来候选，并按版本和模式隔离规则。

## 当前源码核心流程

录入表单现在支持护肩、披风，以及宝石等镶嵌来源。更改或删除镶嵌来源会重置效果核对状态；旧来源、作用者、效果与证据引用会保留。

当前源码启动后显示空白真实档案。结构化表单记录具有唯一 ID 的持有物品、带证据的材料／货币余额，以及玩家核对的技能学习／撤销或装备改造报价。资源、报价和预算均有对应 FSD 表单。报价保留原状态、预计结果、context 与职业、等级／技能上限／解锁要求、成本或未知成本、证据和待确认项。未来计划引用报价 ID，可设置非负整数资源上限。评估器 `0.1.7` 汇总已选报价的已知成本并显示材料缺口和预算超额，同时保留技能真实等级、作用者和效果；未知成本、解锁、版本／输入变化、随机结果或未选入的配套报价均不能视为可行。准备条件可行性与游戏机制结论分开报告。投影仅用于未来计划，不改变当前装备或 build hash。旧档案不会自动补出资源或报价；SQLite 保持 schema v1，无需迁移。Deskrawl 仍为 research-only，DPS 和保留／换装建议均未验收。

**当前本地 Windows 安装包为 `dist/LootWeave-MVP-0.1.0-20261005-preparation-windows-x64-setup.exe`（226,029,750 字节；SHA-256 `cb5574695c048d0754616258136af84577d9f87cd0d2a06fae89f493b7fca9fc`），由源码提交 `2c08e023b6767a0c5ca732abfe941286a84aeefb` 构建，包含 evaluator 0.1.7 和 PR #3 runtime integration，默认仍为 eager。虚构数据下 Rust headless/frozen worker 检查 8 项通过（9.0852 秒），覆盖三状态、资源／预算合计 12、预算 10 超额 2、未知余额为 null、SQLite 档案和评估重启持久化、每个结果重启前后各回放十次且实际装备不变。两轮生命周期 13 项通过（37.175 秒）。524 个 bundle 文件均通过哈希校验，3 个前端文件与 production build 逐字节一致。构建耗时 723.625 秒；Rust 单元检查 31 项通过、3 项忽略（47.164 秒），这三项是 supervisor.rs 子进程 fixture，其他测试通过 --ignored 显式调用；GUI 验收仍未完成，不能由这些忽略项推断。此前四个安装包保持不变。以上是已完成的本地检查；远端 CI 与合并状态记录在本阶段 PR 中。M1/M3 真实机制、GUI、OCR 人工 holdout 和双机发行验收仍未通过。**

此前 `20261005-equipment` 安装包的 `eb1995dc` 宿主通过 `scripts/check_desktop.py --cycles 2` 的 13 项后台生命周期检查（34.563 秒），包括两次正常启动／退出、六项服务故障清理、宿主强制退出后的 Job 回收、重启恢复、重启及来源故障下的冻结回放、实例锁和备份／恢复。34.563 秒为整个检查脚本的耗时，不是启动延迟指标；该检查未测量可见 GUI。 此前源码与安装包证据保留在 [PR #4](https://github.com/schorsch888/LootWeave/pull/4)。

## 运行性能实验

[预先声明的运行实验](docs/performance-experiment.md)、[结果](docs/performance-results.md)和[选定的脱敏批次](fixtures/runtime-performance/README.md)保留了每组 20 次尝试。显式按需模式源码 `7afdd6e` 将启动后无界面的空闲私有提交内存降至 76.6 MiB，对照组最大值约为 105 MiB；但手动流程完成 P95 为 4.924 秒，未达到 <3.698 秒的要求。主要门槛未通过，因此两个启动器仍默认 eager；`--startup-policy on-demand` 仅作为显式实验选项。Knowledge 延迟解析、OCR 辅助进程复用和生产 JavaScript 拆包继续暂缓。这些测量批次早于当前真实装备流程，也没有测量可见桌面启动。

完整装备流程集成源码 `96c6374` 的匹配开发构建通过了各 20 次 eager 和显式按需生命周期／故障循环，以及 20 次隐藏被动 WebView 循环。产物身份、历史 `2034deed`／`ddbfa853` 结果与限制在[验证记录](docs/validation.md#complete-equipment-integration-96c6374)中分别列出。这些本地产物不替换已交付安装包，也不能确立发布验收。

## 了解项目

| 入口 | 内容 |
| --- | --- |
| [实现说明（英文）](docs/implementation.md) | 当前实现、开发环境与验收边界 |
| [验证记录（英文）](docs/validation.md) | 源码与旧构建的实测范围及未通过的发布条件 |
| [设计（英文）](docs/design.md) | 产品范围、核心数据、架构、证据与隐私边界 |
| [Roadmap（英文）](docs/roadmap.md) | 依赖、交付物与阶段验收条件 |
| [研究指南（英文）](docs/research.md) | 公开证据、工具前提、复现命令与限制 |

React/TypeScript 前端按 feature-sliced 目录组织于 `frontend/src/{app,pages,features,entities,shared}`。Rust/Tauri Windows 宿主位于 `desktop`。profile、knowledge、evaluation、planning 和 OCR 的 Python 服务以独立 HTTP 进程运行，并使用 SQLite 存储。根目录的 `contracts`、`storage` 和 `transport` 模块提供通用基础设施；gateway 不包含领域规则。

实现支持已确认的完整快照修订、将 OCR 原始观察与用户确认数据分开、解释整件替换，并可回放冻结的评估。采集成功后，核对面板会按原始像素显示 BMP 区域，原图区支持键盘滚动，并保留未经校正的 OCR 原文供对照。数字解析会拒绝分裂或残缺数字以及科学计数法片段，同时保留原文、符号和单位。原生 OCR 行文本会映射回原始文本并保留全局跨度；字段绑定到对应来源行，跨行重复字段标记为歧义，缺失或无法映射的原生行不会生成解析字段。可读的主识别结果仍是数值来源；一致的英文识别记录为 `numeric_corroboration`，只有实际恢复不可读数字时才使用 `numeric_source`。带空格的小数片段会被拒绝，使带明确单位的完整不可读主识别词项可与独立英文数字结果核对；若有分歧仍标记为歧义，所有观察仍须人工确认。更改游戏范围、采集来源、窗口绑定、区域或语言，或开始新的采集，都会清除旧图像及观察关联并要求重新确认，同时保留手动输入的文本。只有匹配当前范围和检测代次的窗口检测响应才会更新窗口列表。planning 可比较实测总经验值和完整耗时，并提供带 Wilson 95% 区间的观察采样估计。试验可手动填写实际起止角色等级，或单独填写巅峰经验类型及其起止等级，并记录覆盖相同范围的累计实际经验与完整耗时。系统只比较确认范围一致的记录；任一试验输入变化都会清除旧排名，并要求重新确认一致性。若试验保存成功但比较失败，使用相同数据重试会沿用原 trial ID。系统报告记录到的结果，不推断掉落或最优地图。

新试验的经验和等级须处于精确整数范围，并产生有限的经验率。无法可靠计算的历史测量保留原始存储内容，标记为待确认并排除排名；超出计算范围的汇总同样保持待确认。相同原始输入的重试沿用 trial ID，不受派生分类变化影响，并发保存不会产生重复记录。微小的正经验率仍显示为非零值。

## 使用 Windows MVP

当前安装包为 `dist/LootWeave-MVP-0.1.0-20261005-preparation-windows-x64-setup.exe`。安装后即可使用持有资源、准备报价和未来构筑流程；数据保存在 SQLite，不会修改游戏。此前四个安装包作为历史构建保留。

新安装包以空白档案启动。记录材料／货币数量，核对技能或装备准备报价，再将报价加入未来计划，以查看声明的可行性、成本、资源缺口和预算超额。未知要求仍保持未知。这些结果不建立游戏机制或推荐。真实 GUI、真实游戏采集、OCR 人工 holdout 和双机发行验收仍未通过。

## 本地运行

要求：原生 OCR 与桌面打包需使用 Windows；Node.js 24 或更高版本；pnpm 11.19.0；服务使用 Python 3.12 或更高版本（本机验证使用 3.12.14，CI 使用 3.13.16）。Python 运行时服务没有第三方运行依赖。先安装前端依赖并构建，再启动本地开发运行时：

```powershell
pnpm --dir frontend install --frozen-lockfile
pnpm --dir frontend build
python runtime.py
```

Deskrawl 实时采集已加入进程、窗口检查和显式选择。区域使用客户区相对坐标，并倒计时提示手动切回游戏；检测不代表版本或机制已验证。没有启动游戏时，文本输入和历史重放仍可使用。`scripts/check_native_ui.py` 是仅存在于仓库的开发工具，用于隐藏、不可获得焦点的被动 DOM／IPC 检查，不执行键盘、鼠标或焦点操作，不随安装包分发。当前 Rust-only 宿主改动已包含在安装包中。隐藏状态下的 readiness 不代表可见绘制、真实游戏窗口采集成功、键盘可达性、冷启动 GUI P95 或两机验收。

Windows OCR 使用操作系统原生模型。安装英文（`en-US`）和简体中文（`zh-Hans-CN`）语言支持即可启用两种语言；若模型不可用或 OCR 失败，用户仍可手动输入并确认物品文本。

在 Windows x64 上打包桌面应用，先安装锁定版本的构建依赖并构建前端：

```powershell
python -m pip install -r requirements-build.txt
pnpm --dir frontend build
python scripts/build_desktop.py
```

脚本会生成本地 PyInstaller sidecar 目录并构建 Rust 宿主。`--installer` 生成内置 Python 和离线 WebView2 组件的 NSIS 安装包。本机打包和后台流程检查不代表两台干净机器的发布验收已经通过。

## 游戏支持与验收

唯一可执行的知识包是 `synthetic-leveling` 版本 `1.0.0`，其作用范围是合成游戏 ID `lootweave-fixture`；其中数据完全虚构，不代表任何真实游戏。Deskrawl build `25690430` Sorcerer leveling 仍为 `research_only`。版本化的 `deskrawl-sorcerer-leveling` 研究包在 `0.6.0-research` 中新增了选定的 Frostwyrm 静态／原生代码、原始 metadata 镜像归属、模块方法指针和选定注册表地址引用证据；六个显式研究版本均可用，旧版本字节保持不变，各版本的 `rules` 均为空。只读验证器核验源身份、选定静态轨迹和方法槽／镜像归属／token 指针和选定注册表尾部／地址引用；注册代码执行与原生分派、在线行为及完整装备／卸下生命周期仍未通过验收，M1 尚未验收。目前不支持 Deskrawl 或 Diablo II、III、IV 作为游戏。

合成 OCR 留出集 holdout-v7 在当前适配器冻结后生成，包含 200 个区域、600 个关键字段，覆盖 2 种语言、5 种缩放和 4 种质量条件。测得 572/600（95.33%）正确、28 个拒识或缺失字段、0 个未标歧义错误，完整请求 P95 为 1.780 秒。英文为 299/300（99.67%），中文为 273/300（91%）；低对比度和降采样组分别为 93.33% 和 92.67%。总体数值目标已达到，M2 仍未验收：这组数据仅包含三个通用合成字段，真实游戏／布局覆盖和独立人工真值复核仍待完成，所有观察仍须人工确认。

当前 OCR 可用一次有超时限制的英文数字局部补读，每次最多裁剪三个区域。原图、原文、可读主数值、显式正负号、单位和读数冲突继续保留；候选读数相互矛盾时，须有一致的局部补读才能解除歧义。补读失败会保留主观察供人工核对。15 项数字局部补读回归包含真实 WinRT 两区域／三区域批处理、显式符号冲突和补读失败检查。

新评估使用评估器 `0.1.7`。引擎 `0.1.0` 至 `0.1.6` 的 42 个合成历史案例各自回放十次，保持原输出；历史回放不代表新游戏机制已验收。

公开的 [v7 证据](fixtures/ocr-critical-fields-v7/README.md)包含全部原始输入、原生观察和 30 个数字补读区域。200 张 BMP 的哈希及完整清单字节均已精确复现，冻结解析器可回放每条观察。新增 7 项证据回归覆盖观察状态／图像身份篡改、缺失或变更的区域、原始词语映射及虚增汇总。[历史 v6 证据](fixtures/ocr-critical-fields-v6/README.md)保持不变；已查看的数据集不能作为后续算法的新验收集。

整合源码的完整本机 Python 回归包含 468 项：467 项通过、1 项 Windows 符号链接权限用例跳过（51.576 秒）。直接前端检查通过：core 24 项、快照确认 19 项（含临时 Profile SQLite）、运行时 16 项、评估卡片 32 项和 Planning 27 项；TypeScript／Vite 及架构检查也通过。上述源码检查与 `75163eff` 本地安装包的 17 项核心／13 项生命周期检查范围不同；该包不含后来整合的按需运行时代码。可见 GUI、真实游戏机制和两台干净机器验收仍未通过。此前隐藏子进程退出超时的记录保留在[验证记录（英文）](docs/validation.md)；[PR #4](https://github.com/schorsch888/LootWeave/pull/4) 保留上一安装包的原验证范围。

研究基线验证了 Deskrawl build `25690430` 中选出的 1,593 个静态对象；这不代表完整游戏机制、玩家实际装备词条或最终战斗与掉落公式已验证。复现需要合法可用的同构建游戏文件，并重新生成本地中间产物。原始游戏资源、完整提取数据库和下载工具不随仓库分发。

## 仓库检查

在仓库根目录运行：

```powershell
python -m unittest discover -s tests -v
python scripts/check_architecture.py
python scripts/check_public_docs.py
python scripts/validate_ocr_holdout.py
python scripts/validate_ocr_holdout.py --version v7
python -m compileall -q services scripts contracts.py storage.py transport.py service.py gateway.py runtime.py version.py
pnpm --dir frontend check:core
pnpm --dir frontend build
node scripts/check_evaluation_render.mjs
```

这些检查验证仓库约定和前端构建；不能证明游戏机制、真实截图上的 OCR 质量或干净机器安装已通过验收。完整 Rust/Tauri 测试依赖生成的桌面资源。Windows 上可使用 `python scripts/check_window_guards.py`，利用缓存的 Rust 依赖独立测试实际采集模块，无需重编译 Tauri 宿主。

英文文档为规范来源，中文 README 与其语义一致。可通过 [Issues](https://github.com/schorsch888/LootWeave/issues) 提交有明确范围的改动，并说明证据、已执行的检查和剩余未知。请勿提交个人资料、真实角色快照、私人截图、凭据、玩家存档或原始游戏资源。详见[公开边界（英文）](docs/design.md#privacy-and-publication)。

## 许可证

LootWeave 代码与文档采用 [Apache-2.0](LICENSE)。该许可证不授予第三方游戏资源、下载工具或其他权利人内容的再分发权。
