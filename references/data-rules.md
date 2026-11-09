# 输入结构与计算口径

所有 CSV 均为 UTF-8（可带 BOM），第一行使用下列英文表头。额外列保留在源文件但不参与计算；脚本拒绝重复表头、缺列、缺单元格、非法日期和重复员工编号。空字符串与 0 含义不同，不替缺失金额自动补零。输出金额/百分数在 JSON 中用十进制字符串，避免浮点精度损失。

## 员工表：audit / metrics

表头见 [employees.csv](../assets/templates/employees.csv)。

| 字段 | 含义 |
|---|---|
| employee_id | 唯一员工编号，一人一个任职周期 |
| employee_name / department / position | 姓名、当前部门、岗位 |
| employment_type | 用户定义的用工类型，不据此自动判断劳动关系 |
| status | probation（试用）/active（在职）/left（已离职） |
| hire_date | 入职日，YYYY-MM-DD，必填 |
| probation_end / contract_end | 试用期结束、合同结束，可空但按检查规则提醒补充 |
| leave_date | 离职日，仅 left 必填；从该日开始不计在职 |

`audit`：当前在职者合同结束日在基准日+提醒天数（含）以内进入提醒；基准日前为 overdue，当天及未来为 due。已离职、尚未入职不生成到期提醒。试用提醒使用当前 `probation` 状态，因此不能用今天的状态重建过去试用身份。

`metrics`：期初=入职日早于月初且离职日为空或不早于月初；期末=入职不晚于月末且离职日为空或晚于月末。期间入职、离职分别计流量，同月入离职均计。验证关系：期初+入职−离职=期末。离职率=离职/((期初+期末)/2)×100%；平均人数为 0 时输出 null（不适用），不是 0%。样例 2026-10：期初 2、入职 2、离职 2、期末 2、离职率 100%。

输入需包含期间内全部任职记录，包括已离职人员。工具只能核对输入一致性，无法证明数据源完整。多次任职、部门历史和多合同需额外事件数据，本版不支持。

## 工资复核：payroll

[payroll.csv](../assets/templates/payroll.csv) 每人一行，所有数字非负且必填；无需某项时显式填 0。

| 字段 | 含义 |
|---|---|
| base_salary | 月固定工资；同时用作本示范模型的加班基数，需确认是否符合公司口径 |
| payable_days / paid_days | 月约定计薪天数 / 实际计薪天数；前者大于0，后者不超过前者 |
| ot_weekday_hours / ot_restday_hours / ot_holiday_hours | 已复核的各类应支付加班小时，不等同原始打卡时长 |
| bonus / allowance | 奖金、津贴 |
| employee_social / employee_housing / tax / other_deduction | 已核定个人社保、公积金、个税及其他扣款 |

固定工资=月固定工资×实际/约定计薪天数。加班工资=Σ(月固定工资/小时除数×分类加班小时×分类倍数)。固定工资、加班合计及其他金额分项分别四舍五入到分，再计算应发、扣款和实发；负实发不截断，标记复核。

规则 JSON 参照 [模拟规则](../examples/local/payroll-rules.json)：必须有 `mode`（simulation/confirmed）、`confirmed: true`、`source`、覆盖整月的有效期、指定折算方式、小时除数及三个加班倍数。`confirmed: true` 表示使用者确认本次采用该参数，不代表规则已经法务审核。示例的倍数不是自动适用的法律结论。

不自动计算累计个税、单位社保成本、请假扣薪、迟到罚款或经济补偿；不从考勤异常推导可扣薪资格。休假、补休、特殊工时、最低工资、离职结算等需要业务方先确定适用规则。

## 绩效计分：performance

[performance.csv](../assets/templates/performance.csv)：`employee_id,indicator,weight,target,actual,direction,evidence`。同员工指标唯一，权重合计必须恰为100。目标和权重大于0，实际值非负；目标为0的指标需另行定义评分标准。

高向 higher=实际/目标×100；低向 lower=目标/实际×100，低向实际为0时取上限120。每指标封顶120，按权重合计后保留2位。不自动排名、不生成奖金、不做末位淘汰。evidence 非空仅表示提供证据位置，不代表已核实；缺证据在输出明确标记。

## 状态与追溯

- ready：输入通过当前计算所需检查，不代表业务审批或合规认定。
- needs_review：有提醒、缺证据或本身属于待复核工作。
- simulation：采用示例/模拟规则，不能作正式工资。
- no_data：表头存在但没有记录，不视为通过。
- error（退出码2）：拒绝生成结果；原输入不变。成功生成草稿退出码0，不表示已批准。

结果保存来源文件名、SHA256、操作参数和 schema_version。源文件名可能含人名，分享前检查。CSV 文本以 `= + - @` 开头时增加单引号防止表格公式执行，JSON 保留原值用于追溯。
