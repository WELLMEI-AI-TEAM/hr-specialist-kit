# 连接器配置

套件业务技能需要可验证当前用户身份和权限的HR SaaS/企业适配层。保留此前约定：**提供API Key/应用密钥才允许联网**。无连接时给出缺口和配置入口；用户明确提供本地资料时仍可使用离线模板与计算，不伪造实时数据。

## 两种接入层次

| 接入 | 当前实现 | 权限边界 |
|---|---|---|
| 用户绑定的HR查询适配层 | API Key + 身份响应 + 场景路由 + 行级检查 + 字段脱敏 | 13个业务技能的正式查询通路；须由企业部署并映射真实厂商API |
| 钉钉/飞书/企业微信原生应用连接 | 旧版应用令牌换取与有限通讯录GET | 应用可见范围，不能当作登录员工权限或全模块连接器 |

HR SaaS没有统一API。审批、招聘、档案、绩效、假期、组织、知识库等端点要根据实际厂商开放范围配置；未映射模块返回module_unavailable。本项目提供可运行的适配层客户端和契约，不提供不存在的通用厂商端点。原生平台支持情况见 [原生连接说明](references/connectors.md)。

## API Key接入

1. 复制 [query-connector.example.json](assets/configs/query-connector.example.json) 为 `my-query-connector.json`。
2. 企业服务管理员按 [查询契约](references/query-contract.md) 实现/配置身份端点和场景只读映射，填写真实HTTPS主机与精确allowed_host。
3. 填入identity_path、需要的routes和可信导航主机。配置不允许明文密钥、本地角色或员工身份覆盖。
4. 用户明确要连接后设enabled=true，从HR_QUERY_API_KEY读取凭据或在交互终端使用--prompt-key。

```powershell
python scripts/hr_query.py query --scenario approval.pending --config my-query-connector.json --prompt-key --output outputs/my-approvals
```

环境变量应通过本地密钥管理或隐藏输入设置，不把密钥粘进聊天、命令行参数、仓库或共享配置。每个API凭据须绑定当前用户，不能给所有员工共用HR管理员密钥。数据源继续执行其权限与模块可见范围，客户端不能放大。

## 浏览器授权及回调

本项目本身没有宿主OAuth安装协议或公开回调服务，**不会宣称安装后自动拉起浏览器授权**。如果目标客户端已提供平台OAuth连接器，可由客户端启动官方授权页，并将用户会话绑定到查询适配层；API Key门仍由本套件服务调用满足。

生产接入时由平台管理员注册真实client_id、最小权限及准确redirect_uri；回调地址须与平台登记一致。宿主/服务端校验state、防重放、授权码和PKCE（平台支持时），密钥保存在服务端；不得用任意第三方回调站点代收令牌。未配置回调时不要拼造授权链接，可指向客户端实际连接设置或本文件。实际注册地址和有效期以所选厂商/宿主文档为准。

## 失效与故障

| 状态 | 处理 |
|---|---|
| not_connected | 尚未启用/配置；展示配置入口，不取数 |
| not_authorized | 缺API Key/用户绑定，先授权 |
| auth_expired | 提示重新授权，停止本次请求，不重复轮询 |
| permission_denied | 展示经净化的权限说明，不说没有数据 |
| module_unavailable | 模块未开通/映射缺失，不说没有数据 |
| empty | 授权查询成功且无记录，注明筛选和范围 |
| partial | 尚有分页，仅展示当前页 |
| service_error | 稍后重试，提供服务request_id或标明client_request_id |
| contract_error | 身份/范围/分页响应不完整，阻止展示并检查适配层 |

每次query最多身份GET+资源GET，不自动重试或刷新令牌；明确使用poll时每轮重新校验身份，默认3轮，上限10轮。默认超时20秒、最大响应2MiB、拒绝HTTP跳转。多页需要明确继续读取，任务状态默认单次查询；用户明确要求轮询时才有界poll，遇授权失效、失败响应或任务终态立即停止。

尚未获得真实企业服务凭据、HR SaaS厂商文档和目标宿主OAuth注册信息，因此当前验证采用虚构数据、mock及本地HTTP契约测试；不声称平台现场联调或浏览器授权已经通过。
