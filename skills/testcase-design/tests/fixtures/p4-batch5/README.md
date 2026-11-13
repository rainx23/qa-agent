# P4 第五批｜P1 消费 P4 知识并完成隔离正式交付（虚构样本）

> **模拟声明**：本目录内全部需求、知识、Case ID、版本、配置 Code、BUG 与 SHA 均为虚构内容，仅用于 P4 第五批未闭合验收的隔离测试。不得作为真实业务事实、真实需求归档或正式知识引用。

## 1. 目的

验证以下事项（不修改 `output/` 正式归档、不修改 `knowledge/modules/global-cost/` 六类正式 JSON）：

1. P1 `testcase-design` 在需求分析阶段按需只读检索 P4 知识，并真实复用 `formal_reusable` 业务规则作为补充预期。
2. P4 的候选（`candidate_pending_verification`）、冲突（`review_required`）、未知（`unknown`）不进入已确认用例预期。
3. P1 现有发布工具完成 `inspect → publish → validate` 完整闭环，覆盖首次交付、增量交付、Case ID、Revision、SHA、历史继承与增量保护。
4. P4 不可用或知识损坏时，P1 仍可独立完成需求驱动的设计，且不跳过结构/Oracle/XMind 校验。

## 2. 目录结构

| 路径 | 说明 |
|---|---|
| `requirement-900001.md` | 虚构需求正文（Oracle 来源 S1） |
| `knowledge/modules/sim-visit-center/` | 虚构 P4 知识模块（未被写入，仅只读消费） |
| `archive/output/900001-【模拟】…/` | 隔离的需求归档根目录（含 `.qa-publish-*.lock` 发布锁） |
| `archive/output/900001-【模拟】…/20261107-v1/` | 首次正式交付：Markdown、XMind、Oracle |
| `archive/output/900001-【模拟】…/20261107-v2/` | 增量正式交付：Markdown、XMind（Oracle 继承 v1） |
| `archive/output/900001-【模拟】…/20261107-v3/` | O11 语义整改：Markdown、Oracle、XMind（保留 v1/v2 历史） |

## 3. 复现命令（工程根目录执行）

```powershell
$req = "skills/testcase-design/tests/fixtures/p4-batch5/archive/output/900001-【模拟】访客预约中心-预约名单来源标签与重复预约校验"
python -B skills/testcase-design/tools/manifest.py inspect $req
python -B skills/testcase-design/tools/manifest.py validate $req
python -B skills/testcase-design/tools/xmind.py "$req/20261107-v3/testcases/testcases.md" "$req/20261107-v3/testcases/testcases.xmind" --verify
```

## 4. 状态边界

- 当前有效用例：12 条（v1 12 条；v2 修订 1 条 + 新增 1 条；v3 修订 3 条 + 退役 1 条，历史身份保留）。
- 工程校验：`STRUCTURE_PASS`、`XMIND_READBACK_PASS`、`MANIFEST_PUBLISH_PASS`、`MANIFEST_HISTORY_PASS`。
- 运行态验证：`NOT_RUN`（未执行页面/接口/数据库）。
- 业务验收：`NOT_RUN`（虚构需求不存在真实业务验收）。
- XMind 桌面渲染：`desktop_open_verified=false`。
- 真实 P4 正式知识、真实多模块检索、AI 自主写入知识：本轮 `NOT_RUN`。

## 5. v3 O11 语义整改（2026-11-07）

- O11 从正式义务移入 Oracle 未决事项：需求确认未识别来源在列表显示“未知来源”，但未确认它必须成为下拉筛选项。
- O4 仅核对四种明确来源的筛选项文案与对应列表文案一致；已知来源筛选仍覆盖未识别来源的排除结果。
- 当前有效用例 12 条，历史退役 1 条；v3 修订 3 条（Revision 1→2），退役 Case ID 为 `QA-900001-2715c029c9`，原身份及历史版本保留。
- v3：`MANIFEST_PUBLISH_PASS`、`MANIFEST_HISTORY_PASS`；XMind 生成及独立回读 PASS。桌面渲染、页面/API/数据库运行与真实业务验收仍 `NOT_RUN`。


## 6. 增量拒绝探针（2026-11-07）

- 三种增量拒绝探针的已脱敏的命令回执、退出码、前后 SHA 和版本目录快照见 incremental-rejection-probes-20261107.json。
- 全部探针在独立临时副本执行；拒绝后历史仍为 v1/v2/v3，完整验签 PASS；未修改本目录正式 v1/v2/v3 归档。


## 7. P4 不可用时 P1 降级交付（2026-11-07）

- 完整隔离场景见 p4-unavailable-900002/：故意损坏相关 P4 JSON，实际得到 KNOWLEDGE_UNAVAILABLE；P1 仅依据需求 S1 完成 8 项 Oracle、8 条用例及 XMind/Manifest 首次正式发布。
- 隔离版本为 20261107-v1；结构、XMind、发布、历史验签及发布后独立回读均 PASS。已脱敏的命令记录与原 SHA 证据见 p4-unavailable-900002/p4-unavailable-p1-delivery-evidence.json。
- Codex 首轮独立验收为 NEED_FIX（仅 staging 暂存残留）；四份暂存文件及空目录已清理，实施方只读复核通过，等待 Codex 最终复验。真实业务、页面/API/数据库、XMind 桌面渲染和平台导入未验证。
