# 业务知识库（P4）

`knowledge/modules/` 按用户/组织自己的业务模块划分，GitHub 只提供空目录占位。不存在业务模块时，P4 只读检索返回 `NO_MATCH`，P1/P2/P3 仍继续可独立完成的工作。

用户明确授权建设某个模块/页面/Tab 后，按 `skills/knowledge-management/SKILL.md` 和 `references/knowledge-update.md` 创建实际有内容的类别 JSON：`business-rules.json`、`pages-functions.json`、`interactions-fields.json`、`interfaces-configs.json`、`code-data-locator.json`、`quality-experience.json`。只创建当前真正有知识的类别，不批量创建空 JSON。

记录来源、状态与适用范围，严格区分用户确认、需求/源码事实、运行验证与待核实推断。个人业务知识不纳入公开仓库。不得从历史模拟夹具或别人的业务模块推断本组织正式业务口径。
