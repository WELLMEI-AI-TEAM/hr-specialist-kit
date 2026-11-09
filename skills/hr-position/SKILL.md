---
name: hr-position
description: 搜索有权访问的招聘职位，查看JD、职责、任职资格、人数、脱敏薪资范围、地点和申请量。
metadata:
  version: "2.0.1"
---

# 职位管理

先读取 [HR共享规则](../../references/hr-shared-rules.md) 与 [查询契约](../../references/query-contract.md)。业务查询仅使用经过用户身份约束的查询引擎，不能将应用通讯录权限当作当前员工权限。

1. 将用户问题映射到本技能登记的场景，提取必要参数。时间词按用户时区解析为明确日期；“上个月”取完整自然月，“今天”取当天。缺少影响结果的编号/范围时补充询问，不随意扩大查询。
2. 用 `python ../../scripts/hr_query.py catalog --skill hr-position` 查看场景参数，再执行 `query --scenario 场景ID --params JSON --config 用户配置 --output 新目录`。路径相对于本技能目录，实际执行请先定位技能根目录并使用绝对路径；密钥由环境变量或隐藏输入提供。自然语言理解由宿主完成，脚本不声称是独立大模型。
3. 仅展示引擎返回的已脱敏字段，保留期间、范围、分页和来源。出现未授权/过期/权限不足/模块未开通/服务异常时按原状态说明，不改写成无数据。对 `partial` 提示还有下一页，按用户需要继续显式取页；不得无限轮询。
4. `guide` 场景仅给出引擎核验过的可信入口与导航路径。即使用户要求办理，也不能在此技能内正式提交、审批、发Offer、变更档案、创建或取消分析/搜寻任务。

未配置服务时可说明连接缺口或演示虚构数据；不能用示例代替真实人事结果。已有本地材料的起草/计算能力仍可经[套件入口](../../SKILL.md)使用，标明来源，不能假称已接入平台。

## 本技能判断规则

分别给出职位状态、职责、资格、招聘人数、地点与申请量；职位薪资范围遵循脱敏策略。未配置厂商接口时不编造职位数据或API端点。

## 可用场景

- `position.search`：按名称编码状态分类检索职位
- `position.detail`：职位详情和JD
- `position.responsibilities`：岗位职责
- `position.qualifications`：任职资格
- `position.openings`：招聘人数和空缺
- `position.salary_range`：职位薪资范围按策略脱敏
- `position.locations`：工作地点
- `position.applications_count`：职位申请数量
