---
name: hr-employee-profile
description: 查询本人基本信息、任职、教育、技能、项目、履历、考核、证书、奖励与晋升；不查询其他员工档案。
metadata:
  version: "2.0.1"
---

# 员工档案

先读取 [HR共享规则](../../references/hr-shared-rules.md) 与 [查询契约](../../references/query-contract.md)。业务查询仅使用经过用户身份约束的查询引擎，不能将应用通讯录权限当作当前员工权限。

1. 将用户问题映射到本技能登记的场景，提取必要参数。时间词按用户时区解析为明确日期；“上个月”取完整自然月，“今天”取当天。缺少影响结果的编号/范围时补充询问，不随意扩大查询。
2. 用 `python ../../scripts/hr_query.py catalog --skill hr-employee-profile` 查看场景参数，再执行 `query --scenario 场景ID --params JSON --config 用户配置 --output 新目录`。路径相对于本技能目录，实际执行请先定位技能根目录并使用绝对路径；密钥由环境变量或隐藏输入提供。自然语言理解由宿主完成，脚本不声称是独立大模型。
3. 仅展示引擎返回的已脱敏字段，保留期间、范围、分页和来源。出现未授权/过期/权限不足/模块未开通/服务异常时按原状态说明，不改写成无数据。对 `partial` 提示还有下一页，按用户需要继续显式取页；不得无限轮询。
4. `guide` 场景仅给出引擎核验过的可信入口与导航路径。即使用户要求办理，也不能在此技能内正式提交、审批、发Offer、变更档案、创建或取消分析/搜寻任务。

未配置服务时可说明连接缺口或演示虚构数据；不能用示例代替真实人事结果。已有本地材料的起草/计算能力仍可经[套件入口](../../SKILL.md)使用，标明来源，不能假称已接入平台。

## 本技能判断规则

员工自助强制仅限本人。教育、技能、履历等来自实际记录，不推断未登记信息；考核结果只读，不自动评价员工。薪酬、证件、联系方式按共享分级规则隐藏。

## 可用场景

- `profile.basic`：本人基本信息
- `profile.employment`：本人当前任职
- `profile.education`：本人教育背景
- `profile.skills`：本人专业技能
- `profile.projects`：本人项目经历
- `profile.work_history`：本人工作履历
- `profile.assessments`：本人考核结果
- `profile.certificates`：本人证书执照
- `profile.awards`：本人表彰奖励
- `profile.promotions`：本人晋升结果
- `profile.contracts`：本人合同摘要
- `profile.changes`：本人任职变更记录
