# QA Agent｜通用测试工程

一份可供 ChatGPT、Codex、CodeBuddy 等 Agent 读取的 Markdown/JSON 工程规则。AI 自主承担需求理解、测试设计、业务 Oracle 和影响分析；Python 仅处理必要的确定性文件与校验。**本地与 GitHub 使用同一份工程代码，不维护第二套发布代码。**

## 能力

| Skill | 功能 | 额外条件 |
|---|---|---|
| P1 `skills/testcase-design/SKILL.md` | 需求分析、Oracle、Markdown、XMind、Manifest、用例增量 | 用户提供需求正文即可；平台读取与导入是可选项 |
| P2 `skills/code-impact-analysis/SKILL.md` | 开发提测、Bug 根因、代码变更影响与人工核对 | 有效 Git 仓库/源码；配置、血缘及缺陷平台可选 |
| P3 `skills/sql-design/SKILL.md` | 按独立预期设计找数 F、验证 V 与人工验证 SQL | 真实业务口径和表字段证据；不强制数据库连接 |
| P4 `skills/knowledge-management/SKILL.md` | 业务知识按需检索、明确授权后增量维护 | 可从空知识库开始 |
| `skills/api-autotesting/SKILL.md` | 可选接口场景与自动化回归 | 创建/Debug/正式 Run 需已授权的平台 MCP |

统一入口为 `AGENTS.md`；Agent 根据自然语言任务按需读取对应 Skill 和 references，不要求专有 Skill Runtime。克隆工程不自动赋予 Agent 对磁盘、业务 Git、MCP、数据库或平台的访问权限。

## 安装与本地配置

环境建议 Python 3.11+，需要分析远端源码时使用 Git CLI；当前 Python 核心工具主要依赖标准库。

1. 克隆本仓库到用户自选工作目录，并允许所用 Agent 读取工程文件。
2. P1 可直接处理完整需求文本；没有平台 MCP 不影响核心用例设计。
3. P2 如需业务仓库定位，从 `config/repositories.example.json` 复制为本地 `config/repositories.json` 并填写真实仓库路径、remote 和类型；**保留其数组 Schema**。也可以在任务中直接提供可核实的仓库路径。
4. 如果需要为当前组织定义生产/集成引用、配置 MCP、默认 SQL 方言或接口测试平台，从 `config/organization-profile.example.json` 复制为本地 `config/organization-profile.json` 并填入本组织的真实约定。分支名缺少证据时不得猜测；SQL 未配置时的 Presto 仅为可说明的默认假设。
5. 将选用的需求平台、缺陷平台、配置中心、血缘服务或接口测试 MCP 连接到当前 Agent 客户端。平台不可用时，仅停止依赖该平台的部分，不伪称运行结果。

Windows PowerShell 可用：

```powershell
Copy-Item config/repositories.example.json config/repositories.json
Copy-Item config/organization-profile.example.json config/organization-profile.json
```

真实配置、认证信息、业务数据均留在本地，不写进公开模板。平台凭据由客户端或私有安全配置提供。

## 自然语言示例

- “分析这个需求（附需求正文）”：只分析，不自动生成正式用例。
- “根据需求编写正式测试用例”：P1 独立 Oracle、用例和正式归档。
- “开发已经提测，这些是提测点和目标 Git 分支”：P2 双向追踪代码与业务影响。
- “为需求设计找数和验数 SQL”：P3 设计只读 SQL，由用户按权限执行并回传结果。
- “为这个业务模块建立知识”：P4 在明确授权范围内维护知识。
- “为该接口建立自动化回归”：可选 API 自动化，依实际平台连接与授权开展。

## 目录与正式归档

- `skills/`：公开 Skill、references、工具、测试与合成测试夹具，必要的 JSON、SQL、XMind、模拟发布锁需要随代码发布。
- `knowledge/modules/`：个人/组织知识模块；Git 只保留空目录占位，实际模块在用户授权后创建。
- `output/【模块】/<需求编号>-<原始完整标题>/`：正式需求归档。Manifest 位于 `versions/<YYYYMMDD-vN>/manifest.json`，对应产物按需放在 `testcases/<版本>/`、`analysis/<版本>/`、`sql/<版本>/`、`api-automation/<版本>/`；不预建空分类目录。
- `output/api-automation/`：接口自动化项目级索引。
- `.qa-work/`：候选稿及分析临时证据；`platform-sync/`：独立平台回执（见其 README）。
- `implementation/`、`artifacts/` 和本地个人决策记录仅为私有维护资料，不是公开 Skill 的运行依赖。

本地可能安装了不公开的组织专用 Skill（如行权限配置）；仅文件实际存在时才可调用，公开仓库不包含企业专用页面或自动化实现。

## 工程测试

工程根目录执行：

```powershell
python -B -m unittest discover -s skills/testcase-design/tests -p "test_*.py"
python -B -m unittest discover -s skills/code-impact-analysis/tests -p "test_*.py"
python -B -m unittest discover -s skills/sql-design/tests -p "test_*.py"
```

工程测试、静态分析、产物校验、数据库/平台真实执行、业务验收分别报告，不相互代替。MCP 断连及业务资料缺失时说明可继续范围和未证实结论。

## GitHub 发布安全

仅提交通用入口与 Skills、配置模板、合成测试夹具和规则说明；真实 `output/`、`.qa-work/`、`implementation/`、`artifacts/`、`knowledge/modules/<业务模块>/`、本地配置、平台回执、私人决策与专用 Skill 不进入 Git。**`.gitignore` 不保护手动压缩整个文件夹的行为**，向外部审查者提供 ZIP 时必须只收录允许发布的候选文件，额外校验其中没有敏感内容。

未经明确授权，不修改业务仓库代码、不执行生产 SQL、不导入或写平台、不 Commit 或 Push。
