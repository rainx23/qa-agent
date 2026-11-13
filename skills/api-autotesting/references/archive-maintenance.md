# 输出、索引与历史资产维护

本文件承载接口自动化可读产物、项目级索引、执行证据及交付检查。由 SKILL.md 按任务路由加载。

## 输出、索引与历史资产维护

- 对话交付信息按本次任务类型与实际范围选择；相关证据由对应任务提供。不得把设计完成、保存成功、Debug 成功和正式 Run PASS 混为一谈。简要结论优先，详细证据按需提供。
- **需求绑定型正式产物**沿用 `output/【<模块>】/<需求编号>-<需求名称>/api-automation/<YYYYMMDD>-vN/`，Manifest 位于需求根目录 `versions/<YYYYMMDD>-vN/manifest.json`，与 P1/P2/P3 共用需求级版本序列；不另建接口自动化版本账本。模块目录名保留需求标题中第一个非空全角 `【...】` 标识（包括括号）；没有标识时使用 `【未分类】`。需求目录保留完整标题和括号。P1 的 Markdown+XMind 展示规范不机械套用于 ZeroRunner Case/执行报告。
- **项目级接口覆盖索引**统一保存在 `output/api-automation/index.json`，每接口独立维护于 `output/api-automation/interfaces/<API Code>.json`。这两类 JSON 是当前有效基线，不放在 `skills/api-autotesting/`，也不按每次执行创建快照。
- **需求关联的可读分析/设计产物**放在对应需求根目录的 `api-automation/<YYYYMMDD>-vN/`，并在 `versions/<YYYYMMDD>-vN/manifest.json` 中登记 `category: api-automation`；项目级索引仅关联需求产物、源码 SHA、Case/Report 等必要身份，不复制完整内容。
- 不复制完整源码、Git 历史、P3 完整分析产物、ZeroRunner 请求响应、Step 日志或完整平台报告；这些内容分别由源码仓库、既有需求产物或 ZeroRunner 平台保存。Markdown 用于可读分析/设计依据，JSON 用于轻量索引。
- 默认维护当前有效基线并增量更新对应接口 JSON，不为每次分析或执行创建整份历史快照。退役场景保留身份和必要追溯关系；不覆盖需求正式历史版本，不删除平台历史执行记录。

## 本地接口索引结构与当前/历史映射

- 本地接口索引必须区分当前与历史：顶层 `platform.case_id` 只指向唯一当前 Case，`case_ids` 只列当前入口，历史 ID 单独放在 `historical_case_ids`。
- `scenarios[].case_id/step_id` 保留来源/历史身份；用 `current_case_id/current_step_id/current_enabled` 记录当前合并映射，重复场景标记 `merged_into_step_no`，不得把历史报告误标为当前版本的执行证据。
- 本地接口索引中的当前/历史 Case 与 Step 映射字段以本节为唯一权威。平台 Case/Step 本身的组织和操作规则由 references/platform-execution.md 负责；平台操作同时更新本地索引时，必须在索引写入前读取本文件。

## 场景来源与需求变更追溯

- `scenarios[]` 增加稳定的 `scenario_key`（本地生成，如 `SCN-000001`），作为场景长期身份；平台重新保存后即使 Step ID 重建、Step 顺序变化或名称调整，也必须保留原 `scenario_key`，不得用平台 Step ID 充当稳定身份。
- `origin_type` 与本次变更动作分开记录：`INITIALIZATION` 表示该场景在接口首次建立可信自动化基线时引入；`REQUIREMENT_INCREMENT` 表示该场景由某个需求首次引入；`BASELINE_IMPORTED` 仅用于迁移已有历史资产但无法可靠追溯首次引入来源的场景，不得伪造需求编号或把未知来源写成已确认初始化。
- `origin_requirement_id` 记录首次引入该场景的需求编号：仅 `REQUIREMENT_INCREMENT` 必填；`INITIALIZATION`、`BASELINE_IMPORTED` 留空。首次来源不可因后续需求更新而改变。
- `last_changed_requirement_id` 记录追溯体系启用后，最近一次有证据的实质改变该场景请求、触发条件、断言或启停/退役状态的需求编号；仅 KEEP、重新执行、平台 Step ID 重建或仅同步报告结果，不算场景内容变更，不更新此字段。对于 `BASELINE_IMPORTED` 历史资产，字段为空表示迁移后尚无可确认的变更记录，不代表其历史上从未修改。
- `current_action` 继续表示当前平台合并/映射动作，不得拿它代替某次需求的 `ADD/UPDATE/KEEP/RETIRE/REVIEW`。接口 JSON 顶层用轻量 `requirement_updates[]` 按需求记录版本、状态、摘要/计划路径，以及各变更动作对应的 `scenario_key`；完整分析留在需求产物，不复制整份接口基线。
- 每个有接口自动化增量的需求版本，必须在 `api-automation/scenario-change-summary.md` 保存可读变更速览，并在根部 Manifest 登记 `category: api-automation`。摘要只写本次实际发生的 ADD/UPDATE/RETIRE/REVIEW 与必要 KEEP 说明；计划但未实施的项目单独列为待办，不能写成已新增。
- `index.json` 只需在 `latest_incremental_requirement` 中保留最新需求编号、版本及 `scenario-change-summary.md` 路径；完整需求历史由接口 JSON 的 `requirement_updates[]` 和各需求正式产物追溯，避免项目索引膨胀。

## 覆盖状态与数量口径

- `scenarios[]` 的数组长度表示当前本地场景记录数；平台 Step 数必须取当前 Case 的最新回读，并同时注明 Case ID/版本及启用、禁用数量。场景记录数、历史来源记录数和当前平台 Step 数是不同口径，不得共用一个无范围说明的“总数”。
- 为兼容历史索引而保留的 `total_steps` 等旧字段，必须增加明确的历史范围/版本说明；同时提供当前场景记录数与当前平台 Step 数，不能让历史数字继续被解释为当前值。
- `coverage_review`、`boundaries` 等汇总结论属于由场景和执行证据派生的状态；当请求、断言、启停状态或正式报告更新时，必须同步检查并更新所有相关汇总项。旧结论可以保留，但必须标明历史请求/Case 版本/报告范围，不得继续作为当前覆盖结论。
- 场景最近一次成功报告不一定属于当前 Case 版本。状态摘要必须注明证据对应的 Case 版本和报告 ID；当前版本 `NOT_RUN_AFTER_UPDATE` 与上一版本最近一次成功结果必须分别表达，不能将旧版本成功冒充当前版本已执行。
- `coverage_review.groups[]` 中**每个覆盖组**都必须维护 `evidence_scope`，不得只给本轮重点整改组补充。组内有多个历史 Case/Report 时逐条列出，不得用一个“最新报告”概括所有来源；组内没有正式执行证据时明确记录空集合/无记录，不推断成功。
- evidence_scope 至少区分：当前接口 Case 版本及其执行状态、最近一次基线正式报告及逐场景结果映射、当前版本 Debug 报告、历史正式报告、历史 Debug 报告、无法映射的报告引用、未取得当前基线正式结果的场景，以及真实业务数据验证状态。- 报告版本必须绑定**该报告实际执行时的 Case 版本**。不得把当前 `platform.case_version` 反向套给旧报告；正式报告的 Case/版本可从报告与 Case 关联证据确认，Debug 报告未记录版本时必须写 `UNKNOWN`，不能从当前 Case 快照猜测。
- 正式报告与 Debug 报告必须分开记录；报告级整体 PASS/FAIL 不得替代组内 Step 结果。组内逐场景结果需通过稳定 `scenario_key`、Step 序号及结果 ID 关联，保留 SUCCESS/FAILURE，不将重复合并场景重复计为独立结果。- 当前 Case 版本的 Debug 报告单独放入 `current_version_debug_reports`，并且只有需求更新记录/平台快照明确关联该版本时才能填写版本；不得混入 `historical_debug_reports`，也不得把 Debug SUCCESS 写成正式 Run SUCCESS。
- 当前版本尚未执行时，每个覆盖组均应明确当前 Case ID/版本、`NOT_RUN_AFTER_UPDATE` 和空的当前版本正式报告；旧版本结果只能作为历史基线证据。没有结果记录的场景标明 `NO_LATEST_FORMAL_RESULT`，不能据此断言从未执行。
- 报告引用无法映射到 Case 或版本时，保留报告 ID 并显式标记 `UNKNOWN`；这表示证据范围已如实披露，不得为了消除 UNKNOWN 而编造版本，也不得把缺少版本信息的历史记录删除。


## 执行与交付检查

交付检查只核查本次任务实际涉及的部分，不要求每次任务都提供全部类型的证据：

- 若本次涉及接口身份、源码分析、场景设计或增量更新，检查接口身份/目标版本、相关前后端证据、场景覆盖去向和回归范围。
- 若本次涉及请求构造或断言，检查请求契约、UAT 目标、必要认证处理及断言依据。
- 若本次涉及 ZeroRunner Case/Step 操作、Debug、正式 Run 或报告判定，检查相应平台操作边界及本次真实报告证据。
- 若本次涉及本地索引、历史映射或归档，检查索引对象、当前/历史字段映射、必要变更、历史保留及文件写入结果。
- **仅维护索引/归档的任务**只需检查本次索引对象、字段结构/映射、变更边界、历史保留和写入结果；不要求补充无关源码证据、场景覆盖、请求断言或执行报告。

以上检查用于 AI 自主复核，不构成由脚本替代业务判断的固定门禁。缺少证据时局部标记 UNKNOWN/BLOCKED/NOT_VERIFIED，交付其余可信结果，不编造 PASS，也不因非关键缺证无条件阻断全部工作。
