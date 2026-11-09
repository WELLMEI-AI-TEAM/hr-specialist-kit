---
name: hr-specialist
description: HR专家套件入口，路由员工自助与招聘协作的人事查询和业务入口引导；覆盖档案、考勤假期、组织、审批、企业制度、招聘需求、职位、人才、应聘者、招聘待办及洞察，按源系统当前用户权限读取并脱敏展示。
metadata:
  version: "2.0.1"
---

# HR专家

包含13项业务技能和一份内部共享规则，覆盖员工自助与招聘协作。根入口负责路由；完整套件共享脚本、参考规则和模板，不单独复制子技能文件。

执行前读取 [HR共享规则](references/hr-shared-rules.md)；正式业务取数读取 [连接配置](CONNECTORS.md) 与 [查询契约](references/query-contract.md)。只读查询与办理入口引导，不代替源系统正式审批、录入或任务操作。API Key/应用密钥仍是服务接入前提，身份、角色和行级范围必须由用户绑定的源服务确认。

## 选择技能

| 主线 | 技能 | 适用请求 |
|---|---|---|
| 基础 | [数据查询](skills/hr-data-query/SKILL.md) | 自动匹配场景、提取条件和结构化回答 |
| 员工自助 | [员工档案](skills/hr-employee-profile/SKILL.md) | 我的任职、教育、技能、绩效履历、证书、晋升 |
| 员工自助 | [考勤休假](skills/hr-attendance-leave/SKILL.md) | 我的迟到漏卡、排班、假期及调休余额 |
| 员工自助 | [组织架构](skills/hr-organization/SKILL.md) | 管理用途下的部门负责人、HRBP、层级及团队编制 |
| 员工自助 | [审批查询](skills/hr-approvals/SKILL.md) | 我的待办/已办、在途/结束审批及流程节点 |
| 员工自助 | [企业知识库](skills/hr-knowledge/SKILL.md) | 检索制度、政策、流程、手册及来源版本 |
| 员工自助 | [办事入口](skills/hr-service-entry/SKILL.md) | 找请假、补卡、入职等可点击业务入口 |
| 招聘协作 | [招聘需求管理](skills/hr-requisition/SKILL.md) | 需求列表、HC、负责人、到岗时间及进展 |
| 招聘协作 | [职位管理](skills/hr-position/SKILL.md) | 职位搜索、JD、资格、人数、脱敏薪资和申请量 |
| 招聘协作 | [人才搜寻](skills/hr-talent-search/SKILL.md) | 人才条件查询、AI推荐、任务状态与发起/取消入口 |
| 招聘协作 | [应聘者跟进](skills/hr-applicant-tracking/SKILL.md) | 申请阶段、面试中、待发Offer、待入职核对 |
| 招聘协作 | [招聘待办](skills/hr-recruiting-todos/SKILL.md) | 我的待筛选简历、待评价/参加面试及日程 |
| 招聘协作 | [招聘洞察](skills/hr-recruitment-insights/SKILL.md) | 招聘卡点、重点岗位、转化复盘与分析任务入口 |

## 执行流程

1. 从 [102个登记场景](assets/catalog/scenarios.json) 选择最窄场景，使用对应业务技能提取参数。自然语言理解由宿主Agent完成，脚本执行确定性的校验和查询。相对时间按用户时区转为明确日期；默认中文示例使用Asia/Shanghai。缺少影响结果的编号或范围时再澄清。
2. 通过 `scripts/hr_query.py query` 执行身份校验、权限过滤和取数。员工自助仅本人；组织与团队需明确管理用途和范围；招聘按HR/HRBP/负责职位授权。不得用旧的应用通讯录工具绕过用户权限。
3. 按实际状态回答：未连接/未授权、过期、无权限、模块不可用、空结果、部分页、异常分别说明。异常保留request_id，缺少时使用明确标为客户端生成的client_request_id。不猜测数据，不无限轮询。
4. 只展示已脱敏白名单字段，说明对象、期间、筛选和授权范围。制度须引用版本与来源；链接须经可信主机白名单验证。guide模式只给入口，不说已提交/发起/取消/发Offer。

脚本路径相对于套件根目录，执行时定位技能目录并使用绝对路径：

```powershell
python scripts/hr_query.py catalog --skill hr-approvals
python scripts/hr_query.py query --scenario approval.pending --config my-query-connector.json --output outputs/my-approvals
python scripts/hr_query.py query --scenario attendance.balance --demo --output outputs/demo-balance
```

没有真实连接时，提供 [连接配置入口](CONNECTORS.md)，不得把演示数据当作员工实际记录。宿主已提供OAuth连接器时才可能浏览器授权；本技能文件不提供通用OAuth回调服务。

## 保留的本地能力

用户明确提供本地文件或要求文档草拟时，仍可使用 [本地数据计算](references/data-rules.md)、[招聘文稿](references/recruitment.md)、[入转调离](references/lifecycle.md)、[绩效培训沟通](references/people-operations.md) 和 [模板](assets/templates/index.md)。这些是离线辅助，不属于真实平台查询；工资规则需明确确认，示例保留simulation，结果不能视为正式审批或发薪。用户未要求本地处理时，不用CSV样例替代平台结果。

可重复验收及当前限制见 [验收说明](references/acceptance.md)。不得声称已验证竞品私有实现、真实企业连接或所有宿主的菜单行为。
