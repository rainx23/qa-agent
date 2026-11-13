# sim-visit-center（虚构模块｜P4 第五批隔离验收）

> **模拟声明**：本模块是 P4 第五批隔离验收使用的虚构知识模块，不对应任何真实业务模块、真实仓库或真实配置。所有 SHA、需求编号、BUG 编号、配置 Code 均为模拟值，不得作为真实业务事实引用。

## 1. 范围

- 业务对象：`sim-visit-list`（虚构「预约名单」页面）。
- 关联需求：`SIM-PRIOR-REQ-898877`、`SIM-PRIOR-REQ-880001`（虚构历史需求）。
- 本模块只服务于隔离验收，不进入 `knowledge/modules/` 正式知识目录，不影响真实业务模块六类正式 JSON。

## 2. 已存知识类别

| 文件 | 内容 |
|---|---|
| `business-rules.json` | `VC-BR-001` 正式可复用默认查询范围；`VC-BR-002` 候选；`VC-BR-003` 冲突待复核 |
| `interactions-fields.json` | `VC-IF-001` DEV 配置状态未知的快捷查询字段 |
| `quality-experience.json` | `VC-Q-001` 历史导出一致性经验（候选） |

## 3. 状态边界

- `formal_reusable` + `user_confirmed`：可作为历史预期依据，但仍受适用范围约束。
- `candidate_pending_verification`：只能作为候选线索，不得作为已确认预期。
- `review_required`：与本次需求证据冲突，保留双方来源，不得作为本次预期。
- `unknown`：当前无法证明，不据此增加已生效预期。
