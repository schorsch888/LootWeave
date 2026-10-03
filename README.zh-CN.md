# LootWeave

[English](README.md) · 简体中文

把装备词条、角色构筑和游戏机制联系起来，帮助玩家判断物品怎样用、是否值得换装，以及为什么值得保留。

LootWeave 是一个开源项目，目标是构建 Windows 本地装备决策助手，无需玩家自行填写词条权重。首个研究对象为 Deskrawl，后续考虑 Diablo II、III、IV，各游戏规则按版本和模式隔离。

**项目仍处于研究与设计阶段。尚无可运行应用、EXE、OCR流程或装备评估服务。** 当前内容包括选定的机制研究、静态提取及独立验证工具，以及分阶段实现计划。

## 了解项目

| 入口 | 内容 |
| --- | --- |
| [设计（英文）](docs/design.md) | 产品范围、核心数据、架构、证据与隐私边界 |
| [Roadmap（英文）](docs/roadmap.md) | 依赖、交付物与阶段验收条件 |
| [研究指南（英文）](docs/research.md) | 公开证据、工具前提、复现命令与限制 |
| [AGENTS.md（英文）](AGENTS.md) | 仓库协作和公开资料约定 |

本地研究验证了 Deskrawl build `25690430` 的1,593个选中静态对象；这不代表完整游戏机制、玩家实际装备或最终战斗与掉落公式已验证。复现需要合法可用的同构建游戏文件，并重新生成本地中间产物。原始游戏资源、完整提取数据库和下载工具不随仓库分发。

## 开始使用仓库

准备 Git 与 Python。研究参考环境为 Python 3.12；文档预检仅依赖 Python 标准库与 Git，无需安装游戏。

```sh
git clone https://github.com/schorsch888/LootWeave.git
cd LootWeave
python scripts/check_public_docs.py
```

从[设计（英文）](docs/design.md)和[Roadmap（英文）](docs/roadmap.md)开始。静态数据复现请遵循[研究指南（英文）](docs/research.md)，其中的外部工具和游戏前提独立于上述快速检查。文档预检不能证明没有秘密，也不能验证游戏机制。

英文文档为规范来源，中文README为等价翻译。

## 仓库检查

运行与 [GitHub Actions工作流](.github/workflows/checks.yml)配置相同的检查：

```sh
python -m unittest discover -s tests -v
python scripts/check_public_docs.py
python -m compileall -q scripts
```

这些检查不需要游戏文件或研究依赖。工作流配置为在推送和Pull Request时运行，远程成功结果仍需单独核对；检查范围为公开边界与脚本语法，不代表产品行为或游戏公式已验证。

## 参与贡献

通过 [Issues](https://github.com/schorsch888/LootWeave/issues)讨论需求、补充带版本的公开来源，或提出集中改动。先阅读 [AGENTS.md（英文）](AGENTS.md)，说明依据、实际执行的检查和剩余未知；行为变化同步更新相关设计与验收条件。

请勿提交个人资料、真实角色快照、私人截图、凭据、玩家存档或原始游戏资源。复现脚本与选定脱敏证据在用途明确时可公开；重复草稿和私人生成资料留在本地。详见[公开边界（英文）](docs/design.md#privacy-and-publication)。

## 许可证

LootWeave代码与文档采用 [Apache-2.0](LICENSE)。该许可证不授予第三方游戏资源、下载工具或其他权利人内容的再分发权。
