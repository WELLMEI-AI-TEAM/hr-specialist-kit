# 原生应用连接与兼容诊断

本文件说明保留的hr_connect.py低层诊断能力。13个业务技能必须通过 [统一连接配置](../CONNECTORS.md) 的用户绑定查询通路，不能以本工具代替当前用户授权。

默认无需连接。所有连接必须显式启用、提供有效 API Key/应用密钥，并由用户要求读取该服务后才运行。不得为普通本地任务自动尝试环境中的密钥。密钥从配置指定的环境变量读取或由 `--prompt-key` 隐藏输入；没有命令行明文密钥参数，不写入配置、日志或结果。

## 支持范围

| kind | 身份字段与密钥 | 已实现只读资源 |
|---|---|---|
| dingtalk | client_id=AppKey；API Key=AppSecret | 获取应用 accessToken 后按 unionId 读取通讯录用户详情 |
| feishu | client_id=自建应用 App ID；API Key=App Secret | 获取 tenant_access_token 后读取通讯录用户列表/详情 |
| wecom | client_id=Corp ID；API Key=应用 Secret | 获取 access_token 后读取成员列表/简要列表/成员详情 |
| generic | API Key；自定义 HTTPS 服务及认证头 | 读取提供 API Key 认证的 HR SaaS 或企业网关 JSON GET 资源 |

“API Key”是此技能对接入密钥的统一名称，原生平台实际需要应用身份+应用密钥，不是把任意字符串填入通用 Header 就能接入。管理员仍需在各平台开通通讯录权限、应用可见范围与所需白名单。此技能不绕过原平台授权，不包含扫码登录或用户 OAuth。

## 配置与调用

复制 [connector.example.json](../assets/configs/connector.example.json) 到本地 `my-connector.json`，不要修改分发包中的默认禁用示例。填好必要字段，明确要读的数据范围后将 enabled 改为 true。用环境变量或在交互终端隐藏输入：

```powershell
python scripts/hr_connect.py pull --config my-connector.json --prompt-key --output outputs/users-page1.json
```

原生配置示例（只包含公开身份字段；仍默认关闭）：

```json
{"enabled":false,"kind":"feishu","client_id":"YOUR_APP_ID","api_key_env":"HR_FEISHU_API_KEY","path":"/open-apis/contact/v3/users","query":{"department_id":"0","page_size":50}}
```

```json
{"enabled":false,"kind":"wecom","client_id":"YOUR_CORP_ID","api_key_env":"HR_WECOM_API_KEY","path":"/cgi-bin/user/list","query":{"department_id":1,"fetch_child":0}}
```

```json
{"enabled":false,"kind":"dingtalk","client_id":"YOUR_APP_KEY","api_key_env":"HR_DINGTALK_API_KEY","path":"/v1.0/contact/users/REPLACE_WITH_UNION_ID","query":{}}
```

只允许预设官方主机上的上述只读路径。飞书分页可在下一次配置的 query 中提供 `page_token`；企业微信列表是否含子部门由 fetch_child 控制。每次只保存一个响应，**不自动遍历分页**，结果始终标记 `single_response_not_complete_sync`，不能声称“全量已同步”。钉钉本版需已知 unionId，不包含组织遍历。

## 通用 HR SaaS / 企业网关

需用户提供真实接口说明、HTTPS 主机和只读路径。`base_url` 只包含 scheme 和 host，`allowed_host` 必须精确匹配；参数放 query，密钥不得放 URL。默认 `Authorization: Bearer`；服务要求 `X-API-Key` 时设置 `auth_header: "X-API-Key"`、`auth_scheme: "raw"`。通用模式不接收原生平台主机，避免错误认证。

响应格式各厂商不同；工具保存脱敏 JSON 后，由 Agent 按真实接口文档映射字段至本地 CSV。保留来源快照与字段映射，不把单页数据当作完整员工表。没有厂商文档时不得编造端点。

## 请求和结果边界

授权请求只用于换取只读访问令牌；不创建业务记录。令牌仅驻留本次进程；企业微信原生 API 按平台协议将令牌用于 HTTPS 查询参数，错误输出不含 URL 或响应正文。拒绝跳转和无限重试，单次超时20秒、响应上限2 MiB。GET 仍需用户确认对应通用接口是只读语义。

输出现在也按共享规则隐藏常见薪酬、证件、联系方式字段并过滤已知密钥/令牌；自由文本脱敏不是完备DLP，且仍不提供当前用户行级授权。快照本身是人事数据，应保存在授权目录。HTTP 401/403、平台业务错误、超时、禁用或缺密钥时返回失败，不能降级成空名单或成功。结果已有文件时拒绝覆盖。

原生授权与资源响应已通过 mock 验证，尚无用户企业的真实凭据，未完成现场平台联调。接口权限和平台版本以实际企业配置及官方文档为准：

- 钉钉：[服务端开发文档](https://open.dingtalk.com/document/orgapp/overview-of-server-api)
- 飞书：[开发文档](https://open.feishu.cn/document/home/index)
- 企业微信：[服务端 API](https://developer.work.weixin.qq.com/document/path/90664)

这些链接供部署时核验，不能把未实时检索的说明称为最新平台事实。
