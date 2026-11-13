# P4 不可用时 P1 降级交付验证（虚构样本）

本目录仅用于验证 P4 知识不可用时，P1 是否仍能依据需求独立完成 Oracle、Markdown、XMind、Manifest 正式交付。全部需求、业务对象、Case ID 与产物均为虚构。

- 需求正文：requirement-900002.md
- P4 故障夹具：knowledge/modules/sim-visit-center/business-rules.json（故意损坏的 JSON）
- P1 暂存产物：已清理；正式产物仅保留于 archive/output/
- 隔离正式归档：archive/output/
- 不修改工程 output/、正式知识、Skill、业务代码。


## 2. 实际交付与复核

- P4 故障：business-rules.json 为故意损坏的 JSON，读取结果 KNOWLEDGE_UNAVAILABLE；P1 不使用其中内容。
- Oracle：8 项业务义务，仅引用需求来源 S1；先形成 Oracle，再设计用例。
- P1 正式隔离版本：20261107-v1，8 条用例、2 个分组、8 个步骤；Case ID 唯一，Revision=1。
- 工程结果：STRUCTURE_PASS、XMIND_READBACK_PASS、MANIFEST_PUBLISH_PASS、MANIFEST_HISTORY_PASS。
- 证据：p4-unavailable-p1-delivery-evidence.json；SHA-256 为 d7a84f5b6165569cf51f1aa6d01847034ed4e05eaf64c5ff4f018feb0ad92089。
- 独立复现（工程根目录）：
  - python -B skills/testcase-design/tools/manifest.py validate "skills/testcase-design/tests/fixtures/p4-batch5/p4-unavailable-900002/archive/output/900002-【模拟】访客预约中心-预约来源标签与筛选"
  - python -B skills/testcase-design/tools/xmind.py "skills/testcase-design/tests/fixtures/p4-batch5/p4-unavailable-900002/archive/output/900002-【模拟】访客预约中心-预约来源标签与筛选/20261107-v1/testcases/testcases.md" "skills/testcase-design/tests/fixtures/p4-batch5/p4-unavailable-900002/archive/output/900002-【模拟】访客预约中心-预约来源标签与筛选/20261107-v1/testcases/testcases.xmind" --verify
- 本结果仅为虚构样本工程验证；业务运行、XMind 桌面渲染、平台导入未验证。


## 3. Codex 首轮验收整改（2026-11-07）

- Codex 首轮结论 NEED_FIX，仅因 staging/ 留有四份临时文件；未要求重做设计或重新发布。
- 已删除 staging/oracle.json、testcases.md、testcases.xmind、publish-spec.json，并移除空 staging/ 目录。
- 三份产物副本删除前均与正式 20261107-v1 对应文件逐字节一致；正式版本、需求、P4 故障夹具及原始执行证据保留。
- 原始执行证据 SHA-256 未变化：d7a84f5b6165569cf51f1aa6d01847034ed4e05eaf64c5ff4f018feb0ad92089。
- 清理后由实施方只读复核 Manifest 历史、XMind 回读及 Markdown/Oracle 结构；Codex 最终复验待执行。
