# HR专家套件

覆盖员工自助与招聘协作的人事管理技能套件：用自然语言查询授权范围内的人事信息，检索企业制度，找到业务办理入口。

包含 **13 项业务技能、102 个登记场景、16 组虚构演示**，配套权限检查、字段脱敏、查询工具和本地人事模板。以完整技能包交付，适合通过 SkillHub 分发到支持 `SKILL.md` 的 Agent 客户端。

> 所有在线业务场景均为只读查询或入口引导。真实数据需配置用户绑定的企业服务并提供 API Key；102 个登记场景表示客户端支持范围，实际可用模块取决于企业接口、授权和开通情况。

[技能入口](SKILL.md) · [连接配置](CONNECTORS.md) · [SkillHub 发布说明](docs/PUBLISHING.md) · [验收说明](references/acceptance.md) · [Apache-2.0 许可证](LICENSE)

## 适用角色

| 角色 | 常见用途 |
|---|---|
| 普通员工 | 查本人档案、审批、打卡、假期余额；找制度和办事入口 |
| HR / HRBP | 查看招聘需求、职位、人才推荐、应聘者进展及招聘洞察 |
| 用人经理 / 团队负责人 | 按管理权限查看组织编制、负责职位、招聘待办与面试日程 |

## 包含的技能

| 主线 | 技能 | 能力说明 |
|---|---|---|
| 基础 | [数据查询](skills/hr-data-query/SKILL.md) | 场景匹配、参数提取、身份与权限校验、结构化回答 |
| 员工自助 | [员工档案](skills/hr-employee-profile/SKILL.md) | 本人基本信息、任职、教育、技能、项目、工作与绩效履历、证书、奖励、晋升 |
| 员工自助 | [考勤休假](skills/hr-attendance-leave/SKILL.md) | 假期及调休余额、打卡异常、排班、加班、公出、出差、休假记录 |
| 员工自助 | [组织架构](skills/hr-organization/SKILL.md) | 管理用途下的部门负责人、HRBP、组织层级、编制使用与团队概览 |
| 员工自助 | [审批查询](skills/hr-approvals/SKILL.md) | 本人待办、已办、在途及结束审批，流程节点和审批人 |
| 员工自助 | [企业知识库](skills/hr-knowledge/SKILL.md) | 按关键词、分类及时间检索制度、政策、流程和手册，保留版本与出处 |
| 员工自助 | [办事入口](skills/hr-service-entry/SKILL.md) | 匹配 HR 服务菜单，返回可信办理链接与导航路径 |
| 招聘协作 | [招聘需求管理](skills/hr-requisition/SKILL.md) | 需求列表、HC、负责人、期望到岗时间及需求级进展 |
| 招聘协作 | [职位管理](skills/hr-position/SKILL.md) | 职位搜索、JD、职责、资格、人数、脱敏薪资范围、地点及申请量 |
| 招聘协作 | [人才搜寻](skills/hr-talent-search/SKILL.md) | 人才条件查询、服务端 AI 推荐结果、分页获取、任务状态与有界轮询 |
| 招聘协作 | [应聘者跟进](skills/hr-applicant-tracking/SKILL.md) | 申请阶段、待处理简历、面试中名单、待发 Offer、待入职核对 |
| 招聘协作 | [招聘待办](skills/hr-recruiting-todos/SKILL.md) | 本人的待筛选简历、待评价面试、待参加面试与近期日程 |
| 招聘协作 | [招聘洞察](skills/hr-recruitment-insights/SKILL.md) | 招聘进展、卡点、重点岗位、阶段量、Offer 到岗转化及分析入口 |

内部 [HR 共享规则](references/hr-shared-rules.md) 由业务技能读取，不注册独立技能菜单。根入口负责路由，技能清单见 [suite.json](suite.json)。

人才搜寻的发起/取消、面试质量分析和竞品分析的发起均提供源系统入口；正式操作在源系统完成。

## 安装与快速体验

### 1. 导入完整技能包

在 SkillHub 的发布或导入入口上传 `hr-specialist-2.0.1.zip`，或按目标 Agent 客户端支持的方式导入本项目完整目录。包内根目录应直接包含 `SKILL.md`。

请保留 `skills/`、`scripts/`、`references/`、`assets/` 和 `examples/` 的相对结构。子技能依赖共享资源，不应只复制某一份子技能 `SKILL.md`。支持多技能发现的宿主可识别子技能，单入口宿主可通过根技能路由；`@`、`/` 菜单和具体调用语法以宿主为准。

### 2. 运行无需密钥的演示

环境要求：**Python 3.10+**。业务脚本仅使用 Python 标准库，无需安装额外 Python 包；Agent 宿主需允许读取技能文件和运行本地脚本。

在项目根目录执行：

```powershell
# 查看考勤休假场景和可用参数，不联网
python scripts/hr_query.py catalog --skill hr-attendance-leave

# 运行虚构假期余额演示，不联网
python scripts/hr_query.py query --scenario attendance.balance --demo --output outputs/demo-balance
```

打开 `outputs/demo-balance/report.md` 查看报告，或读取同目录的 `result.json`。所有演示均明确标注 `demo: true`；查询工具拒绝覆盖已有结果目录，重复体验时请换用新目录。

### 3. 连接真实业务服务

先阅读 [CONNECTORS.md](CONNECTORS.md)，将 [业务查询配置示例](assets/configs/query-connector.example.json) 复制为本地 `my-query-connector.json`，由企业管理员配置真实主机、当前用户身份端点和场景映射。默认配置关闭，且不包含可直接调用的企业接口。

服务配置就绪后，在交互终端隐藏输入 API Key：

```powershell
python scripts/hr_query.py query --scenario approval.pending --config my-query-connector.json --prompt-key --output outputs/my-approvals
```

也可通过配置指定的环境变量提供密钥。密钥不放入聊天、命令行明文参数、配置文件或上传包。

## 可以怎样提问

导入技能并连接已授权服务后，可直接向 Agent 提问：

- 帮我查下我有哪些待办审批？
- 我上个月有没有迟到，或者忘记打卡？
- 我还有几天年假？
- 公积金提取政策是什么？请附制度版本和出处。
- 我负责的在招职位现在整体进展怎么样？
- 我今天有几场面试？分别是几点？
- 找一批 3–5 年经验、本科及以上、有 B 端产品项目经验的候选人。

自然语言理解和日期解析由宿主 Agent 完成，Python 工具按登记场景执行校验和查询。查询结果会注明授权范围、筛选条件、分页状态和来源；“上个月”等时间按用户时区解析。

## 系统接入范围

| 接入方式 | 当前提供的能力 | 配置要求 |
|---|---|---|
| HR SaaS / 企业查询适配层 | 当前用户身份、场景查询、权限证据与结果展示 | 用户绑定的 API Key，以及符合 [查询契约](references/query-contract.md) 的只读端点 |
| 钉钉 / 企业微信 / 飞书原生应用连接 | 应用令牌获取、限定通讯录接口的只读诊断 | 应用身份、应用密钥及平台授权；详见 [原生连接说明](references/connectors.md) |
| 本地文件 | 模板起草、档案检查、工资复核、绩效计分和基础人事指标 | 用户提供的文件和明确规则；无需业务服务连接 |

原生应用的可见范围不能代替当前员工的数据权限。审批、招聘、绩效、假期等完整业务查询需通过企业适配层映射到实际厂商接口；未配置或未开通的模块会明确提示不可用。

浏览器 OAuth 授权依赖目标宿主和企业的平台注册配置。本项目提供客户端技能与查询工具，尚未包含通用 OAuth 回调服务；真实企业平台与宿主授权流程尚未现场联调。

## 权限、脱敏与异常处理

- **本人范围**：员工自助仅查本人；当前身份由已授权服务返回，不接受本地角色或员工身份覆盖。
- **管理范围**：组织与团队查询需明确管理用途、管理角色及所管部门权限；用人经理招聘查询限负责职位；招聘待办限当前用户。
- **敏感数据**：仅展示场景允许的字段，默认隐藏薪酬明细、证件、银行卡和联系方式；企业服务仍需执行自身字段分级及自由文本净化。
- **办理边界**：查询和入口引导不等于审批、正式录入、发薪、发 Offer 或任务创建/取消。
- **可追溯性**：结果保留安全的服务请求 ID；服务未提供时，明确使用客户端生成的追踪 ID。

| 情况 | 返回行为 |
|---|---|
| 未连接 / 未授权 | 给出连接缺口和配置入口，不猜测业务数据 |
| 授权失效 | 提示重新授权，停止本次请求 |
| 权限不足 / 模块未开通 | 说明实际状态，不改写为“没有记录” |
| 查询成功无记录 | 明确当前范围和条件下无记录 |
| 存在下一页 | 标记部分结果，不据单页推断整体情况 |
| 服务异常 / 契约不符 | 保留追踪信息并停止展示无效结果 |

完整规则见 [HR 共享规则](references/hr-shared-rules.md)。

## 本地模板与计算

[模板目录](assets/templates/index.md) 提供招聘、入转调离、绩效培训和员工沟通模板，以及员工台账、工资和绩效空白 CSV。虚构计算样例位于 `examples/local/`。

```powershell
python scripts/hr_local.py audit --input examples/local/employees.csv --as-of 2026-11-01 --output outputs/local-audit
```

本地工具支持档案提醒、月度人数与离职率、规则明确的工资复核和绩效计分。金额使用十进制计算，模拟规则保留 `simulation` 状态；字段、公式和适用限制见 [数据口径](references/data-rules.md)。

## 项目结构

```text
hr-specialist-kit/
├── README.md                 产品介绍、安装和使用
├── SKILL.md                  套件路由入口
├── CONNECTORS.md             业务服务连接说明
├── suite.json                套件版本和业务技能清单
├── LICENSE                   Apache-2.0
├── agents/                   套件界面元数据
├── skills/                   13 项业务子技能
├── references/               运行时共享规则、契约及业务工作法
├── assets/
│   ├── catalog/              场景注册表
│   ├── configs/              默认禁用的连接配置示例
│   └── templates/            可复制的业务模板和空白表
├── examples/
│   ├── local/                本地计算虚构样例
│   └── queries/              只读查询虚构样例
├── scripts/                  查询、计算、脱敏和打包工具
├── tests/                    自动化回归与契约测试
├── docs/                     SkillHub 发布说明
├── dist/skillhub/             生成的 ZIP、校验和及文件清单
└── outputs/                  本地运行结果
```

`dist/` 与 `outputs/` 是生成目录，不作为技能源文件打包。

## 开发、验证与发布

```powershell
# 运行本地计算、权限、脱敏、错误处理和契约测试
python -B -m unittest discover -s tests -v

# 生成 SkillHub 上传包
python scripts/package_skill.py
```

当前版本 **2.0.1**，发布物位于 `dist/skillhub/`：

- `hr-specialist-2.0.1.zip`：完整技能包，根目录直接包含 `SKILL.md`。
- `hr-specialist-2.0.1.zip.sha256`：ZIP 校验和。
- `hr-specialist-2.0.1.manifest.json`：版本与逐文件 SHA256 清单。

打包工具按固定文件白名单收集资源，检查版本、引用闭合及技能文件编码，排除隐藏文件、密钥配置、IDE/Git 元数据和运行结果。发布操作、上架内容建议和验收步骤见 [SkillHub 发布说明](docs/PUBLISHING.md)。

仓库保留标准 `LICENSE`；SkillHub 上传包自动将其导出为 `LICENSE.txt`，并同步调整包内文档链接，避免无扩展名文件被拒绝。许可证内容保持原样。

测试验证范围与尚需现场验证的事项见 [验收说明](references/acceptance.md)。生成上传包不代表已通过 SkillHub 审核或完成真实企业接口联调。
