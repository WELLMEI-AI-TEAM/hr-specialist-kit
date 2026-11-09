# 数据查询引擎契约

本项目定义的**企业适配层契约**，不是钉钉、飞书、企业微信或某个HR SaaS的官方API。厂商端点需要按真实文档映射，不能把示例路径当作原生接口。

## 自然语言到场景

宿主Agent读取 [场景目录](../assets/catalog/scenarios.json)，选择最窄场景、提取条件，再调用 `scripts/hr_query.py`。当前有102个登记场景，含只读查询与入口引导；登记不代表某家企业已开通102个端点。`catalog --skill hr-attendance-leave` 可列参数、必填项、权限、展示字段与模式。`catalog` 不联网，不取真实人事数据。

相对日期按用户时区解析，当前用户默认Asia/Shanghai；2026-11-09说“上个月”应转为2026-10-01至2026-10-31，“今天”转为2026-11-09。CLI接收明确日期，不暗用服务器时区。“我的”不生成用户可控employee_id；身份从服务器获取。模糊职位、缺少详情编号等影响结果时澄清；不为普通查询收集无关资料。

## 配置

[query-connector.example.json](../assets/configs/query-connector.example.json) 默认关闭且场景映射为空。`identity_path` 和 `routes[场景ID]` 填已部署的只读GET端点；`routes` 只接受登记场景，不提供自由HTTP或SQL执行。调用时只从API Key环境变量或隐藏输入取密钥。导航URL另外受 `navigation_hosts` 限制。

## 服务端身份响应

通过HTTPS的API Key认证获取当前用户上下文：

```json
{
  "status": "ok",
  "data": {
    "subject_id": "SUBJECT-001",
    "employee_id": "EMP-001",
    "tenant_id": "TENANT-001",
    "roles": ["employee"],
    "permissions": ["self:read", "organization:read", "knowledge:read", "navigation:read"],
    "managed_department_ids": [],
    "managed_position_ids": []
  }
}
```

管理员身份不能保存在共享配置中作为每个人的身份。浏览器/宿主授权产生的用户会话应由适配层绑定到该用户API凭据；若只有应用级AppSecret，身份绑定不足，业务查询应拒绝。

## 场景请求

GET 请求发送登记场景参数与 `scenario,subject_id,tenant_id,scope`，并带 `X-Client-Request-Id`。这些身份参数仅用于核对，**服务端必须从认证重新建立身份并执行权限过滤，不能信任客户端参数授权**。敏感凭据只在认证Header，不在业务URL。服务必须确保登记端点为只读语义。

## 成功响应

```json
{
  "status": "ok",
  "request_id": "gateway-request-001",
  "authorization": {
    "subject_id": "SUBJECT-001",
    "tenant_id": "TENANT-001",
    "scope": "self",
    "permission": "self:read",
    "enforced": true
  },
  "records": [
    {"tenant_id":"TENANT-001","owner_employee_id":"EMP-001","type":"年假","balance":5,"unit":"天"}
  ],
  "page": {"has_more": false, "next_cursor": null}
}
```

所有记录必带tenant_id；本人记录必带owner_employee_id；团队记录必带department_id且在当前管理范围；仅经理招聘记录必带其负责的position_id。招聘待办另带owner_subject_id且必须匹配当前用户。任意一条越界整页阻断，不静默丢行后声称成功。

页必须明确has_more；有下一页须提供next_cursor。引擎单次读取一页，不自动循环；下一次按同一筛选加cursor。成功空列表且无下一页才是empty；空页但有下一页仍是partial。最后一页不代表此前所有页已取齐。汇总场景应由后端在完整授权过滤集上统计，并在summary内声明统计范围和口径。

响应字段只按场景fields投影、脱敏后进入输出。后端字段不匹配时要修适配层，不用非白名单字段绕过。人才任务job_status应区分queued/running/succeeded/failed/cancelled；查询成功不等于任务成功。source_url/entry_url等需在导航主机白名单，含token/code等凭据参数或非HTTPS的链接会被阻断。

## 错误响应与退出码

服务返回 `{"status":"permission_denied","message":"安全的业务原因","request_id":"..."}` 等结构。支持not_authorized/auth_expired/permission_denied/module_unavailable/service_error。message须先去除机密内容。HTTP401→auth_expired，403→permission_denied，其他HTTP/超时→service_error；不读取或复述任意HTTP错误正文。服务请求ID优先读取结构化响应或HTTP X-Request-Id，仅接受有限长度安全字符。

CLI成功ok/empty/partial退出0，其余状态退出2，且records为空。使用 `--output 新目录` 保存已脱敏result.json和report.md；不覆盖已有目录。失败输出是状态说明，不是成功快照。每次query最多身份请求+业务请求，不自动重试；没有密钥、权限不足或未映射场景时不发起业务读取。

## 显式异步状态轮询

仅用户要求持续查询时运行 `python scripts/hr_query.py poll --params '{"job_id":"实际任务编号"}' --config my-query-connector.json --max-attempts 3 --interval 5`。默认3次，上限10次、间隔1到30秒，每轮重新校验身份。任务成功/失败/取消、查询失败或授权过期立即停止；达到上限仍保留running/queued，并说明后台任务未取消。任务编号不匹配或未知状态阻断。此命令不会创建或取消后台任务。

## 本地演示与兼容

`--demo` 仅使用包内虚构fixture，无网络请求，不接受在线配置混用；输出始终含demo=true和演示提示。场景没有fixture时返回模块无演示数据，不编造记录。

旧 `hr_connect.py pull` 是应用级通讯录/通用接口诊断工具，不是当前员工的权限代理，不可供13个业务技能绕过查询契约。其输出现在也默认脱敏。旧 `hr_local.py` 的CSV检查与计算继续用于用户提供的本地资料，不宣称来源于已连接平台。
