<div align="center">

# 🧩 LootWeave

**把装备、构筑和证据放进同一个本地工作台。**

[![仓库检查](https://github.com/schorsch888/LootWeave/actions/workflows/checks.yml/badge.svg?branch=main)](https://github.com/schorsch888/LootWeave/actions/workflows/checks.yml)
[![许可证：Apache 2.0](https://img.shields.io/badge/License-Apache_2.0-blue)](LICENSE)
[![平台：Windows x64](https://img.shields.io/badge/Platform-Windows_x64-0078D4)](docs/development.md#prerequisites)
[![阶段：实验性](https://img.shields.io/badge/Stage-Experimental-orange)](docs/roadmap.md)

[English](README.md) · **简体中文**

[📦 下载](https://github.com/schorsch888/LootWeave/releases) · [🚀 快速开始](#快速开始) · [📚 文档导航](#文档导航) · [🤝 参与贡献](CONTRIBUTING.md)

</div>

LootWeave 是一个面向装备决策的开源 Windows 原型。
它把实际物品数据、完整角色构筑和版本化证据联系起来。
玩家无需自行填写词条权重。

> **🧪 实验阶段：** 只有虚构知识包包含可执行的游戏规则。
> Deskrawl 是研究对象。真实游戏建议与正式 Windows 版本仍需验收证据。

## 为什么做 LootWeave

物品价值取决于实际词条、完整构筑和使用目标。
工作台将这些输入放在一起：

| 能力 | 可以做什么 |
| --- | --- |
| 🧩 **装备与构筑** | 记录已拥有的物品、技能、效果和资源。将实际装备与未来计划分开。 |
| 📷 **OCR 核对** | 查看截图和识别文本。逐行采用或忽略内容，再确认事实。 |
| 🔎 **比较与解释** | 查看字段差异、已有规则支持的机制变化，以及缺失证据。区分保留理由与装备资格。 |
| 🧰 **准备计划** | 记录已确认的方案和预算。查看已知成本、资源缺口与未知的前置条件。 |
| 🧭 **实测试验** | 记录实际经验值和完整耗时。比较条件一致的试验。 |
| 🔁 **结果回放** | 保留每次评估的输入、证据与规则版本。回放冻结结果。 |

准备计划覆盖装备、技能、天赋、巅峰、符文、仆从和临时效果。
准备可行性与游戏机制结果分开记录。计划不会修改实际构筑。
确认要求与结果阻断条件见[准备工作流](docs/implementation.md#core-workflow)。

## 工作流程

```mermaid
flowchart LR
    A["📝 文本或 OCR 观察"] --> B["👤 用户确认"]
    B --> C["📌 快照与规则版本"]
    C --> D["🔎 比较与回放"]
```

观察、已确认事实和推导结果分别保存。
缺失或冲突的证据会阻止缺乏依据的结论。
职责与数据流见[架构约束](docs/architecture.md)。

## 快速开始

### 体验 Windows 预览版

1. 从 [GitHub Releases](https://github.com/schorsch888/LootWeave/releases) 下载安装包或绿色版 ZIP。
2. 将文件哈希与同一版本的 `SHA256SUMS.txt` 比较。通过 `build-manifest.json` 确认源码身份。
3. 使用绿色版 ZIP 时，将完整压缩包解压到可写文件夹。打开 `LootWeave.exe`。

发布包包含 Python 运行时。绿色版 ZIP 还包含 WebView2 和 C++ 运行库。
绿色版数据保存在相邻的 `data/` 文件夹。安装版使用 `%LOCALAPPDATA%/LootWeave`。
移动文件夹前，请退出程序。替换程序文件时，请保留 `data/`。

Windows OCR 使用已安装的语言能力。OCR 不可用时，请手动录入。
构建与运行前提见[桌面开发指南](docs/development.md#build-the-windows-desktop)。
预览版处于实验阶段。

### 从源码运行

请先安装 **Git、Python 3.12+、Node.js 24+ 和 pnpm 11.19.0**。
环境要求见[开发指南](docs/development.md#prerequisites)。

```powershell
git clone https://github.com/schorsch888/LootWeave.git
cd LootWeave
pnpm --dir frontend install --frozen-lockfile --ignore-scripts
pnpm --dir frontend build
python runtime.py --data-dir .local/development
```

启动器会打开浏览器工作台，并把开发数据保存在 `.local/development`。
请保持终端打开。按 **Ctrl+C** 停止启动器及其工作进程。
请勿分享浏览器会话凭据。使用原生截图功能时，需要 Windows 桌面宿主。

新档案需要先录入装备与构筑事实。保存快照前，请确认这些事实。
可使用虚构示例查看可执行规则。
完整流程见[源码环境与故障排查](docs/development.md)。

### 检查仓库

以下检查使用 Git 和 Python，无需游戏文件或前端构建。

```powershell
python -m unittest discover -s tests -v
python scripts/check_architecture.py
python scripts/check_public_docs.py
python -m compileall -q scripts
```

请查看结果及因环境限制而跳过的检查。
修改前端、原生宿主或研究工具时，请执行相应的[组件检查](docs/development.md#validate-a-change)。

## 支持范围与验证

| 游戏范围 | 状态 |
| --- | --- |
| 🧪 `lootweave-fixture` | 虚构开发数据。`synthetic-leveling` 知识包包含可执行规则。 |
| 🔬 Deskrawl build `25690430` | Sorcerer 升级场景的研究包含 Frostwyrm 法杖静态依赖路径。研究包不含可执行规则，线上机制仍未验收。 |
| 🗺️ Diablo II、III、IV | 未来研究对象。尚无通过验收的适配器。 |

工作台提供显式选择模板、固定资料版本的只读装备依赖查询，展示来源关联与尚待核验的线上条件，查询不会改变已保存的事实。详见[实现说明](docs/implementation.md#contracts-and-invariants)。

规则按游戏、版本分支、构建、模式和赛季隔离。
真实游戏 DPS、最终掉落概率和全局最优路线尚未验证。
OCR 解析器覆盖三个通用演示标签。真实游戏布局覆盖与独立人工真值复核仍待完成。
可见 GUI 行为与两台干净 Windows 机器上的安装／卸载仍需验收证据。

运行时默认使用 `eager` 启动。
显式启用的按需启动实验没有通过预先声明的启动延迟比较。详见[性能结果](docs/performance-results.md)。

[验证记录](docs/validation.md)保存有日期的结果与构建身份。
历史检查不能证明最新源码已经验收。
记录中的本地构建路径不是下载链接。
[CI 与发布约定](docs/implementation.md#github-ci-and-releases)说明了预览版发布流程。

## 文档导航

| 从这里开始 | 内容 |
| --- | --- |
| 🚀 [开发指南](docs/development.md) | 环境、命令、检查、打包与故障排查 |
| 🧱 [架构约束](docs/architecture.md) | Rust/Python 职责、服务调用与存储边界 |
| 🧩 [设计](docs/design.md) | 产品范围、数据模型与证据要求 |
| 🗺️ [路线图](docs/roadmap.md) | 里程碑、依赖与验收条件 |
| 🔬 [研究指南](docs/research.md) | 证据、合法源文件前提与复现方法 |
| 🧪 [验证记录](docs/validation.md) | 已记录的测量、构建身份与未完成的验收条件 |
| 🤝 [贡献指南](CONTRIBUTING.md) | 贡献类型、公开规则与审阅步骤 |

更多细节：[源码实现](docs/implementation.md) · [性能计划](docs/performance-plan.md) · [性能结果](docs/performance-results.md)。
英文是主要文档语言。中文 README 与英文版本语义一致。

<details>
<summary>🗂️ 仓库结构</summary>

| 路径 | 内容 |
| --- | --- |
| [docs/](docs/) | 设计、开发、研究与验证指南 |
| [research/](research/) | 精选证据与来源记录 |
| [scripts/](scripts/) 和 [tests/](tests/) | 复现工具与仓库检查 |
| [fixtures/](fixtures/) 和 [knowledge-packs/](knowledge-packs/) | 合成示例、冻结输入与限定范围的知识包 |
| [frontend/](frontend/) | 采用 Feature-Sliced Design 的 React/TypeScript 前端 |
| [desktop/](desktop/) | Rust/Tauri Windows 宿主 |
| [services/](services/) | 按业务能力组织的 Python 服务，以及 OCR |
| [runtime.py](runtime.py) | 本地开发启动器 |

架构要求使用 Rust + Python、Windows 单 EXE 启动入口、FSD 前端和 DDD 微服务。
组件职责遵循[架构约束](docs/architecture.md)。

</details>

## 参与贡献与获取帮助

请先阅读[贡献指南](CONTRIBUTING.md)。
通过 [Issues](https://github.com/schorsch888/LootWeave/issues) 提问、报告问题或提出方案。
请提供适用版本、证据、检查结果与未知项。
文档纠错、复现改进和范围明确的研究都有助于项目。

## 隐私与边界

项目默认在本地处理数据。
项目不访问玩家存档，也不修改游戏文件。
项目不注入游戏，也不访问进程内存或 DMA。
项目不控制游戏操作，也不自动处置物品。

请在 issue 和 pull request 中使用虚构示例。
请勿公开凭据、私人截图、真实角色数据、玩家存档、原始游戏资源或下载工具。
共享材料必须遵循[公开规则](docs/design.md#privacy-and-publication)。

## 许可证

项目代码与文档采用 [Apache-2.0](LICENSE)。
第三方游戏内容和工具保留各自条款。本许可证不授予其再分发权。
