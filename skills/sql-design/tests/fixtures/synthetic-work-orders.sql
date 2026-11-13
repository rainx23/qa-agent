/*
author: Rainx
create time: 2026-11-07 01:52:00+08:00
description: P3 单条 SQL 多场景模拟；仅供静态设计与隔离归档验收，不得执行数据库
database: synthetic_qa.*（虚构模拟数据源）
execution_engine: Presto (default assumption)
sql_dialect: Presto
oracle: synthetic-work-orders.md 第1节，模拟业务确认；非被测实现 SQL
conditions: state = 'CLOSED'（模拟请求），is_deleted = 0（模拟后端固定过滤）
unknown: team_scope（未确认，严禁编造；不得用于真实页面数据核对）
case_ref: SIM-TC-* 为虚构索引，不是 P1 正式 Case ID
parse_compatibility: NOT_VERIFIED
*/

-- SQL-01 | VP-01, VP-02, VP-03 | SIM-TC-01, SIM-TC-02, SIM-TC-03
-- 一次执行返回真实样本及独立预期。
-- F：找出每个业务组至少一张有多条操作记录的有效工单，event_count > 1 为样本成立证据。
-- V：按工单粒度计算工单数、金额合计和平均金额；按事件粒度计算有效工单的操作记录数。
-- 样本筛选只限制最终返回的工单样本，不缩小 V 的完整业务组计算范围。
with v_valid_orders as (
    select
          t1.order_id
        , t1.group_code
        , t1.amount
    from synthetic_qa.work_order t1
    where 1 = 1
      and t1.state = 'CLOSED'        -- 模拟请求条件
      and t1.is_deleted = 0         -- 模拟后端业务条件
)
, v_event_stats as (
    select
          t1.order_id
        , count(t1.event_id) as event_count  -- 每张工单的操作记录数
    from synthetic_qa.work_order_event t1
    group by t1.order_id
)
, v_group_order_metrics as (
    select
          t1.group_code
        , count(distinct t1.order_id) as order_count  -- 有效去重工单数
        , sum(t1.amount) as total_amount               -- 每张有效工单金额只计一次
    from v_valid_orders t1
    group by t1.group_code
)
, v_group_event_metrics as (
    select
          t1.group_code
        , sum(coalesce(t2.event_count, 0)) as expected_event_count  -- 有效工单关联的操作记录总数
    from v_valid_orders t1
    left join v_event_stats t2
      on t1.order_id = t2.order_id
    group by t1.group_code
)
, v_group_metrics as (
    select
          t1.group_code
        , t1.order_count
        , t1.total_amount
        , case
            when t1.order_count = 0 then null
            else round(cast(t1.total_amount as double) / t1.order_count, 2)
          end as expected_avg_amount
        , t2.expected_event_count
    from v_group_order_metrics t1
    left join v_group_event_metrics t2
      on t1.group_code = t2.group_code
)
, v_ranked_samples as (
    select
          t1.order_id
        , t1.group_code
        , t2.event_count
        , row_number() over (
              partition by t1.group_code
              order by t1.order_id
          ) as sample_rank
    from v_valid_orders t1
    join v_event_stats t2
      on t1.order_id = t2.order_id
    where t2.event_count > 1
)
, v_selected_samples as (
    select
          t1.order_id
        , t1.group_code
        , t1.event_count
    from v_ranked_samples t1
    where t1.sample_rank = 1
)
select
      'VP-01,VP-02,VP-03' as scenario_ids       -- 本行覆盖的模拟验证场景
    , t1.order_id as page_search_order_id       -- 模拟页面可查询的工单 ID
    , t1.group_code as business_group_code     -- 业务组，定位页面汇总行
    , t1.event_count as sample_event_count     -- 样本成立证据：该工单操作记录数大于 1
    , t2.order_count as expected_order_count   -- 独立预期：业务组有效工单数
    , t2.total_amount as expected_total_amount -- 独立预期：业务组有效工单金额合计
    , t2.expected_avg_amount                   -- 独立预期：业务组工单平均金额
    , t2.expected_event_count                  -- 独立预期：业务组有效工单操作记录总数
from v_selected_samples t1
join v_group_metrics t2
  on t1.group_code = t2.group_code
order by
      t1.group_code
    , t1.order_id
limit 100;
