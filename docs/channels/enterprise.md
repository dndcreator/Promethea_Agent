# 飞书、钉钉和企业微信

这三个渠道都使用官方应用/机器人接口，进入与 QQ、Telegram 相同的身份、队列和 Agent 执行链。当前只实现文本收发，不提供附件、语音、互动卡片、群消息审批、跨平台广播或第三方租户代运营。

## 共用部署步骤

1. 先确认本地 Web 对话可用。准备受信任证书的公网 HTTPS 域名，将启用平台的回调路径转发到 Promethea 的 **HTTP 服务**，不是 Gateway WebSocket 端口。
2. 在根 `.env` 填写本页对应参数，重启后端。不要将凭证放入个人模型设置、插件 JSON 或 Git。
3. 代理保留原始 body、平台认证头和查询参数，限制 body 为 1 MB；不要记录正文、签名头、查询串或 access token。后端需要直连各平台官方 API，当前不会自动读取系统代理或 PAC。
4. 在平台控制台配置回调、所需权限和应用可见范围，发布应用到测试组织。平台账号认证、企业管理权限和应用审核不能由 Promethea 绕过。
5. 登录 Promethea，打开 **设置 → 消息平台**，为对应平台生成绑定码；将完整 `/bind ...` 私聊发给应用/机器人。刷新状态确认已绑定后发送普通文本。
6. 按[接入总览](README.md#验收)检查重复回调、解绑隔离、审批和中断恢复。`delivered` 只表示平台接受发送，不表示成员已读。

示例 Nginx 入口（以飞书为例）：

```nginx
location = /api/channels/feishu/webhook {
    client_max_body_size 1m;
    access_log off;
    proxy_pass http://127.0.0.1:8000;
    proxy_set_header Host $host;
    proxy_set_header X-Forwarded-Proto https;
}
```

将 `8000` 改为实际 HTTP 监听端口。为其他平台配置各自的精确路径；企业微信不能阻断 GET，也不要丢弃查询串。入口应按部署环境增加速率限制，不要把整个后台公开到互联网。

## 飞书应用机器人

在[飞书开放平台](https://open.feishu.cn/)创建**企业自建应用**，开启机器人能力，获取以下参数：

```dotenv
CHANNELS__FEISHU__ENABLED=true
CHANNELS__FEISHU__APP_ID=cli_your_app_id
CHANNELS__FEISHU__APP_SECRET=replace_with_app_secret
CHANNELS__FEISHU__VERIFICATION_TOKEN=replace_with_verification_token
CHANNELS__FEISHU__ENCRYPT_KEY=replace_with_encrypt_key
```

在“事件与回调”配置 **Encrypt Key** 和“将事件发送至开发者服务器”，地址为：

```text
https://你的域名/api/channels/feishu/webhook
```

本实现要求加密回调；明文 token 模式不接收。网址验证解密后返回 challenge；普通事件另校验原始 body 的签名和时间戳、Verification Token、AppID。只接收 `im.message.receive_v1` 中来自用户的文本，不把机器人消息再送回 Agent。

在平台为应用开通“接收用户发给机器人的单聊消息”、所需群消息接收权限，以及“以应用的身份发消息”等对应权限，订阅 `im.message.receive_v1`。权限名称和审批要求以控制台为准；发布应用并确认测试成员在可用范围内。回复通过原消息 `message_id` 的 reply API 发送，保留所在聊天/话题；不使用自定义群 Webhook。

群聊默认不启用。确有需要时配置专用本地账号和允许发送者的 `open_id`：

```dotenv
CHANNELS__FEISHU__GROUPS={"oc_your_chat_id":{"user_id":"dedicated_local_user_id","allowed_senders":["ou_allowed_sender"]}}
```

这个本地账号不得已有个人平台绑定；只有其允许成员的消息能进入。开通“所有群消息”权限意味着 Agent 可能收到非 @ 消息，运营方应按实际目的选择最小接收权限。

官方参考：[接收事件与签名](https://open.feishu.cn/document/server-docs/event-subscription-guide/event-subscription-configure-/encrypt-key-encryption-configuration-case)、[接收消息事件](https://open.feishu.cn/document/server-docs/im-v1/message/events/receive)、[回复消息](https://open.feishu.cn/document/server-docs/im-v1/message/reply)。加密格式另对照[官方 SDK](https://github.com/larksuite/oapi-sdk-go/blob/v3_main/event/event.go)。当前不支持 Lark 国际域名或应用商店多租户授权。

## 钉钉企业机器人

在[钉钉开放平台](https://open.dingtalk.com/)创建企业内部应用，添加机器人能力，使用 **HTTP 模式**接收消息（不是只支持推送的自定义群机器人）：

```dotenv
CHANNELS__DINGTALK__ENABLED=true
CHANNELS__DINGTALK__APP_KEY=your_app_key
CHANNELS__DINGTALK__APP_SECRET=replace_with_app_secret
CHANNELS__DINGTALK__ROBOT_CODE=your_robot_code
CHANNELS__DINGTALK__CORP_ID=your_enterprise_corp_id
```

设置机器人消息接收地址：

```text
https://你的域名/api/channels/dingtalk/webhook
```

发布机器人并授权测试成员访问，开通企业机器人单聊消息发送权限；需群聊时再开通群消息发送权限并把机器人加入测试群。接收端使用官方 `timestamp` / `sign` 头校验，窗口收紧为 5 分钟；另核对 `robotCode`、`senderCorpId`。平台 payload 必须提供 `senderStaffId`，单聊回复使用这个企业成员 ID，不把 `conversationId` 错当成成员 ID。

**签名边界：** 钉钉此 HTTP 协议的 HMAC 只包含时间戳和 AppSecret，不包含正文。HTTPS 和代理的保密、完整性是必需条件。不要暴露签名头或把不可信转发服务放在回调链中；消息正文也不提供任意出站 URL 授权。本实现忽略 `sessionWebhook`，使用固定官方 OpenAPI 发送，不访问回调中提供的地址。

群聊默认关闭；开启方式：

```dotenv
CHANNELS__DINGTALK__GROUPS={"cid_your_open_conversation_id":{"user_id":"dedicated_local_user_id","allowed_senders":["allowed_staff_id"]}}
```

只处理群中 @ 机器人的文本和白名单内成员。群账号同样不能借用个人身份，群内不能批准敏感工具。单聊和群聊分别调用 `robot/oToMessages/batchSend`、`robot/groupMessages/send`，使用 `sampleText`，平台返回 `processQueryKey` 才确认已接受。

官方参考：[接收消息协议](https://open.dingtalk.com/document/robots/receive-message)、[内部应用访问凭证](https://open.dingtalk.com/document/orgapp/obtain-the-access_token-of-an-internal-app)、[官方生成 SDK 的收发接口](https://github.com/alibabacloud-go/dingtalk/blob/master/robot_1_0/client.go)。当前不实现 Stream 长连接、跨企业用户及外部群；这些不以占位开关呈现。

## 企业微信自建应用

在[企业微信管理后台](https://work.weixin.qq.com/)创建**自建应用**，设置可见成员和接收消息服务器。不是“添加到群聊”的单向群机器人，也不是个人微信登录。

```dotenv
CHANNELS__WECOM__ENABLED=true
CHANNELS__WECOM__CORP_ID=your_corp_id
CHANNELS__WECOM__AGENT_ID=your_numeric_agent_id
CHANNELS__WECOM__APP_SECRET=replace_with_application_secret
CHANNELS__WECOM__CALLBACK_TOKEN=replace_with_callback_token
CHANNELS__WECOM__ENCODING_AES_KEY=replace_with_43_character_encoding_aes_key
```

`AGENT_ID` 必须是控制台分配的正整数；模板的 `0` 仅表示未配置。Callback Token 和 EncodingAESKey 来自应用的消息接收配置，不是应用 Secret。设置回调地址：

```text
https://你的域名/api/channels/wecom/webhook
```

保存时企业微信发送 GET 验证：Runtime 校验 `msg_signature`、时间戳和 nonce，使用 EncodingAESKey 解密 `echostr` 并核对 CorpID，返回不带 JSON 引号和换行的明文。POST 消息使用同一签名/AES 协议，另核对正文 CorpID 和 AgentID；持久接收后立即返回纯文本 `success`，不等待模型。

成员从应用会话发送文本并绑定，回复使用应用 `message/send`；按企业微信控制台要求设置应用可见范围、可信 IP 等条件。一次只向当前成员回复，禁止 `@all` 和多个收件人拼接。当前不支持客户联系、外部联系人、群机器人、智能机器人或群回调；不要拿其他产品的配置填入本应用渠道。

每段最多 500 字符，最多 4 段，避免 emoji 等 UTF-8 文本超出平台字节限制。过长回复不静默截断，保留在 Promethea 会话中。

官方参考：[接收消息](https://developer.work.weixin.qq.com/document/path/90237)、[发送应用消息](https://developer.work.weixin.qq.com/document/path/90239)、[腾讯加解密示例](https://github.com/sbzhu/weworkapi_python/blob/master/callback/WXBizMsgCrypt.py)。

## 升级与排错

原 `gateway_config.json` 中的 `webhook_url`、`webhook_secret`、`corpid`、`corpsecret`、`agentid` 等旧字段不再构成渠道配置；改用上面的根 `.env` 键。没有自动复制旧密钥，也不保留另一套单向发送路径。此前若只配置了群 Webhook，需要创建具备双向能力的应用/企业机器人。

| 现象 | 先检查 |
| --- | --- |
| 设置页无平台 | `ENABLED`、必需凭证、插件加载日志；修改配置后是否重启 |
| 已启动但无回复 | 平台发布/可见范围、接收事件订阅、私聊绑定、后端到官方 API 的网络 |
| 回调 403 | 时钟、签名、加密 key、AppID/CorpID/AgentID 与机器人是否匹配 |
| 回调 400 | 是否混用了群 Webhook、不同回调产品、消息类型或加密格式 |
| 回调 503 | Runtime 是否就绪、渠道是否启用、持久队列是否已满 |
| 企业微信 URL 验证失败 | GET、查询串和 `echostr` 是否完整，EncodingAESKey 是否 43 字符 |
| `delivery_failed` | 记录中的平台错误码、发送权限、可信 IP、成员可见范围或限流 |
| `uncertain` | 检查会话和平台侧记录；不能直接重跑未知副作用 |

本地测试使用合成回调、真实加解密和模拟平台 HTTP 响应，不代表已完成平台控制台和真实账号联调。投入实际业务前，需用运营方的应用完成共用部署步骤和收发验收。
