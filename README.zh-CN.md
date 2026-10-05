# LootWeave

[English](README.md) · 简体中文

**以物品事实、角色构筑和版本化证据为依据，研究装备决策。**

LootWeave 是一个开源研究与设计项目，面向 Windows 本地装备决策助手。它希望解释物品怎样使用、是否适合某个构筑，以及为什么值得保留，无需玩家自行填写词条权重。

> **当前阶段：研究与开发。** 仓库包含复现工具、精选证据和实验性源码。唯一可执行的游戏知识包使用虚构数据；真实游戏建议与正式 Windows 版本尚未通过验收。

[开始使用](#开始使用) · [文档导航](#文档导航) · [参与贡献](CONTRIBUTING.md) · [路线图](docs/roadmap.md)

## 为什么做 LootWeave

物品价值取决于实际词条、完整构筑和使用目标。LootWeave 探索的工作流程包括：

- 记录已拥有的物品与构筑事实，并由用户手动确认 OCR 观察。
- 区分保留物品的理由与当前能否装备。
- 记录准备操作报价，单独说明资源或预算缺口，区分这些结果与机制结论。
- 比较完整构筑中的机制变化，并保留用于回放的输入和规则。
- 明确展示缺失或冲突的证据，阻止缺乏依据的结论。

## 当前状态

| 领域 | 已有范围 | 验收边界 |
| --- | --- | --- |
| 研究 | 精选 Deskrawl 证据与只读复现工具 | 需要合法取得的匹配源文件；静态解码不代表完整机制已验证 |
| 实验性流程 | 物品／构筑录入、已拥有物品与资源、准备操作报价与预算、SQLite 档案、字段差异与冻结回放 | 真实游戏 DPS 和保留／换装建议尚未验收 |
| 采集与 OCR | 持久保存未确认截图、逐行采用／忽略核对，以及手动映射已有／自定义词条 | 自动解析仅覆盖三个通用演示标签；真实游戏布局覆盖与独立真值复核仍待完成 |
| 规划 | 手动记录的经验／耗时试验与样本估计 | 不提供已验证的最优路线或最终物品掉落概率 |
| 运行时 | 默认完整启动（eager），可显式启用按需启动实验 | 预先声明的启动延迟比较未通过；可见 GUI 冷启动仍待验收 |
| Windows 打包 | 安装包与绿色版 ZIP 构建工具，以及预览版本的 CI 发布流程 | 可见 GUI 与两台干净机器上的安装／卸载尚未验收 |

规则按游戏、版本分支、构建、模式和赛季隔离：

| 游戏范围 | 状态 |
| --- | --- |
| `lootweave-fixture` | 完全虚构；`synthetic-leveling` 知识包可用于开发检查 |
| Deskrawl build `25690430` | 首个研究对象：Sorcerer 升级场景；研究包不含可执行规则 |
| Diablo II、III、IV | 未来研究对象；尚无通过验收的适配器 |

当前源码行为见[实现说明](docs/implementation.md)，有日期的结果与构建身份见[验证记录](docs/validation.md)。历史测试结果不能证明最新源码或其他构建已通过验收。

## 开始使用

浏览并检查仓库需要 **Git 和 Python 3.12 或更高版本**。以下命令不需要游戏文件或前端构建：

```powershell
git clone https://github.com/schorsch888/LootWeave.git
cd LootWeave
python -m unittest discover -s tests -v
python scripts/check_public_docs.py
python -m compileall -q scripts
```

测试会报告受环境限制而跳过的用例，请一并查看。检查通过仅说明所覆盖的仓库行为符合预期，不能证明游戏机制或发布条件已经验收。

- **了解设计：** 从[设计基线](docs/design.md)和[验收路线图](docs/roadmap.md)开始。
- **体验 Windows 预览版：** 查看[预览版说明](#体验-windows-预览版)，了解下载与数据保存方式。
- **体验实验性源码：** 按[开发指南](docs/development.md)准备环境、启动本地流程，并查看预期行为和故障排查。
- **复现研究：** 按[研究指南](docs/research.md)操作；匹配的游戏资源和外部工具需单独取得。

本地安装包和生成的构建产物不随仓库分发。验证记录中的路径用于标识本地产物，并非克隆仓库即可获得的下载文件。

## 体验 Windows 预览版

在 [GitHub Releases](https://github.com/schorsch888/LootWeave/releases) 查看可用的 MVP 预发布版本。选择同一版本的安装包或绿色版 ZIP，并使用随附的 `build-manifest.json` 与 `SHA256SUMS.txt` 核对源码身份和文件哈希。预览版处于实验阶段；真实游戏与两台干净机器上的验收仍待完成。

使用绿色版 ZIP 时，将完整压缩包解压到可写的本地文件夹，双击 `LootWeave.exe`。包内已包含 Python、WebView2 和 C++ 运行库。个人数据保存在相邻的 `data/` 文件夹；移动整个目录前退出程序，升级时保留 `data/`。安装版使用 `%LOCALAPPDATA%/LootWeave`。Windows OCR 需要已安装的语言能力，缺失时仍可手动录入。

[CI 工作流](.github/workflows/checks.yml) 在 Windows 打包成功后保留四个已验证发布文件七天。推送到 main 或手动选择 main 运行时，仅在浏览器／接口检查和 Windows 打包均通过后发布预览版。详见 [CI 与发布约定](docs/implementation.md#github-ci-and-releases)；工作流配置本身不能证明某次运行成功或已有版本发布。历史本地构建的独立身份见[验证记录](docs/validation.md)。

## 文档导航

| 文档 | 内容 |
| --- | --- |
| [开发指南](docs/development.md) | 源码环境、检查、Windows 构建与故障排查 |
| [实现说明](docs/implementation.md) | 当前源码行为、服务归属与接口约定 |
| [设计](docs/design.md) | 产品边界、数据模型、架构与隐私 |
| [路线图](docs/roadmap.md) | 里程碑、依赖与验收条件 |
| [研究指南](docs/research.md) | 证据目录、前置条件、复现方法与限制 |
| [验证记录](docs/validation.md) | 有日期的测量、构建身份、失败与未通过的验收条件 |
| [性能计划](docs/performance-plan.md) | 运行时实现状态与暂缓的工作 |
| [性能结果](docs/performance-results.md) | 已记录的实验、未通过的启动验收条件及保留的 eager 默认策略 |
| [贡献指南](CONTRIBUTING.md) | 文档约定、证据要求与审阅步骤 |

英文是主要文档语言；中文 README 与英文版本语义一致。

## 仓库结构

| 路径 | 内容 |
| --- | --- |
| [docs/](docs/) | 设计、开发、研究与验证指南 |
| [research/](research/) | 精选证据与来源记录 |
| [scripts/](scripts/) 和 [tests/](tests/) | 复现工具与仓库检查 |
| [fixtures/](fixtures/) 和 [knowledge-packs/](knowledge-packs/) | 合成示例、冻结回放输入与限定范围的知识包 |
| [frontend/](frontend/) | 按 Feature-Sliced Design 组织的实验性 React/TypeScript 前端 |
| [desktop/](desktop/) | Rust/Tauri Windows 宿主 |
| [services/](services/) | 按业务能力组织的 Python 服务，以及 OCR 基础设施 |
| [runtime.py](runtime.py) | 本地开发启动器 |

架构要求采用 Rust + Python、Windows 单 EXE 启动入口、FSD 前端与 DDD 后端微服务。当前宿主、框架、职责划分和打包方案仍需验证；详见[设计](docs/design.md#local-architecture)。

## 参与贡献与获取帮助

欢迎提交文档纠错、复现改进和范围明确的研究贡献。请先阅读[贡献指南](CONTRIBUTING.md)，再通过 [Issues](https://github.com/schorsch888/LootWeave/issues) 提问、报告问题或提出方案，并说明相关版本、证据、已执行的检查与剩余未知。

## 隐私与边界

数据默认在本地处理。项目不读取或修改玩家存档、不修改游戏文件、不注入游戏、不访问进程内存或 DMA、不控制游戏操作，也不自动处置物品。

请勿提交个人资料、真实角色快照、私人截图、凭据、玩家存档、原始游戏资源或下载工具。[公开规则](docs/design.md#privacy-and-publication)说明了可纳入仓库的内容以及必须留在本地的材料。

## 许可证

项目代码与文档采用 [Apache-2.0](LICENSE)。第三方游戏内容和工具保留各自条款；本许可证不授予其再分发权。
