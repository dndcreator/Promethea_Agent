# QQ 官方机器人

使用官方 Webhook 和 OpenAPI v2，不是个人 QQ 登录，不依赖 OneBot/NapCat。支持单聊文本和显式授权的群 @ 文本；暂不包含附件、语音、频道、频道私信或富媒体交互。

## 1. 凭证

在 [QQ 开放平台](https://q.qq.com/) 创建机器人，完成平台要求的认证、审核或测试成员配置，开通对应收发权限。Promethea 不能绕过这些约束。

项目根 `.env`：

```dotenv
CHANNELS__QQ__ENABLED=true
CHANNELS__QQ__APP_ID=你的AppID
CHANNELS__QQ__CLIENT_SECRET=获取access_token使用的ClientSecret
CHANNELS__QQ__BOT_SECRET=回调验签使用的BotSecret
```

控制台若将两者显示为同一 Secret，可填成相同值；不要填 access_token。分别参见官方 [安全和授权](https://bot.q.qq.com/wiki/develop/api-v2/dev-prepare/interface-framework/sign.html)、[获取访问凭证](https://bot.q.qq.com/wiki/develop/api-v2/dev-prepare/access-token.html)。程序缓存 access_token 并在临近到期时刷新，不把凭证返回前端。

重启后端，确认 `http://127.0.0.1:8000/health` 就绪；改过 HTTP 端口时使用实际地址。Gateway WebSocket 端口不是回调端口。

## 2. HTTPS 回调

通过受信的反向代理公开现有 HTTP 服务。正式使用稳定域名和有效 TLS；临时测试隧道不要公开整个后台。例如 Nginx 仅代理回调：

```nginx
location = /api/channels/qq/webhook {
    client_max_body_size 1m;
    proxy_pass http://127.0.0.1:8000;
    proxy_http_version 1.1;
    proxy_read_timeout 10s;
    proxy_set_header Host $host;
}
```

放进已经正确配置 TLS 的 server 中，这不是完整 Nginx 配置。保留 `X-Bot-Appid`、`X-Signature-Timestamp`、`X-Signature-Ed25519` 和原始 body；不能做网页登录跳转、验证码或 body 重写。

在 QQ 开放平台选择 HTTP 回调，填写：

```text
https://你的域名/api/channels/qq/webhook
```

官方要求 HTTPS，允许端口 80、443、8080、8443，推荐 443。保存时平台发 `op=13` 挑战，程序返回签名；正常事件验签后确认 `{"op":12,"d":0}`。GET 页面能打开不等于回调成功。

订阅 `C2C_MESSAGE_CREATE`，需要群聊时再订阅 `GROUP_AT_MESSAGE_CREATE`，不申请无权限的 Intent。参见 [事件订阅与通知](https://bot.q.qq.com/wiki/develop/api-v2/dev-prepare/interface-framework/event-emit.html)。

## 3. 绑定与测试

1. 登录 Promethea，打开 **设置 → 消息平台 → QQ → 生成绑定码**。
2. 复制 `/bind ...`，在 QQ **私聊**自己的机器人发送。
3. 收到 `[Runtime]` 绑定确认，返回设置刷新状态。
4. 发送普通问题，应收到模型回复，Web 历史也应出现 QQ 会话。
5. 测试需要工具的任务，验证 Workbench 执行记录和敏感操作审批。

OpenID 不是 QQ 号，无须手填。平台标识按 AppID 隔离，换机器人需要重新绑定。旧 `/user/channels/bind` 不再接受 QQ/Telegram 的无证明身份声明。

## 4. 可选群聊

默认无群授权。创建**专用 Promethea 群账号**，不要绑定个人平台身份、导入个人记忆或授予私人目录/凭证；通过 `/api/user/profile` 获取其本地 `user_id`。

从平台事件/调试信息确认群和成员的 OpenID，不能用 QQ 号代替。未授权来源 ID 只在本地日志用于定位，不自动创建账号。根 `.env`：

```dotenv
CHANNELS__QQ__GROUPS={"群OpenID":{"user_id":"专用账号本地user_id","allowed_senders":["成员OpenID"]}}
```

重启后，仅所列成员 @ 机器人时进入专用账号。拥有个人渠道绑定的账号不能用作群身份。群属于共享上下文，成员可能访问该身份的记忆和工具；群内 `/approve` 不生效，审批回到 Web UI。

## 5. 排错

| 现象 | 检查 |
| --- | --- |
| 设置看不到 QQ | `.env` 启用、插件加载、是否重启 |
| 平台验证失败 | AppID、BotSecret、HTTPS、端口、路径、代理是否改写 |
| 403 | 签名/时间戳错误或绑定码失效；确认主机时钟同步 |
| 503 | 未就绪、未启动、Worker 未运行或队列满 |
| 200 但无回复 | 是否绑定，事件/文本是否支持，群是否授权；查 deliveries 和会话 |
| `100016` | ClientSecret/AppID 错误或失效 |
| `HTTP_429` | 平台限流，不要重复运行 Agent 来解决发送失败 |
| 被动窗口错误 | 在 Web 会话看结果，不转为未经授权的主动消息 |
| `uncertain` | 可能已经发送/执行，检查记录，不盲目重试 |

官方权限、频率和回复窗口可能调整，本地限制不保证平台永远接受。详见 [消息收发概述](https://bot.q.qq.com/wiki/develop/api-v2/server-inter/message/overview.html)、[单聊发送 API](https://bot.q.qq.com/wiki/develop/api-v2/autogen/api/v2_users_user_openid_messages.post.html)。状态、恢复和生产边界见 [接入总览](README.md)。
