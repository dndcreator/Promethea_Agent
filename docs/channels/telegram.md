# Telegram Bot

支持 Bot API Webhook 私聊文本收发，不需要额外桥接进程。当前没有 polling、群消息、编辑消息、频道贴文、附件下载或语音输入；不要从旧 adapter 元数据推断这些能力。

## 配置

通过 Telegram BotFather 创建 Bot，项目根 `.env`：

```dotenv
CHANNELS__TELEGRAM__ENABLED=true
CHANNELS__TELEGRAM__BOT_TOKEN=你的BotToken
CHANNELS__TELEGRAM__WEBHOOK_SECRET=独立随机WebhookSecret
```

Webhook Secret 不是 Bot Token。按官方 [setWebhook](https://core.telegram.org/bots/api#setwebhook) 的字符规则使用字母、数字、下划线、连字符，推荐至少 32 字符。重启后端，通过受信 HTTPS 反向代理公开：

```text
https://你的域名/api/channels/telegram/webhook
```

代理须保留 `X-Telegram-Bot-Api-Secret-Token` 和原始 body，不要公开整个后台或禁用用户认证。

后端还必须能访问 `api.telegram.org:443`。当前传输使用直连，不自动读取
`HTTP_PROXY`、`HTTPS_PROXY` 或系统 PAC；网络受限时需使用可达网络或受信的
网络级路由。本轮没有实现应用内代理配置。

## 注册回调

由部署者一次性设置，不擅自替换既有 Bot 的 polling/webhook。将 shell 环境变量设为 `.env` 对应值和公网 URL；不要提交凭证或将它们贴到日志：

```bash
curl --fail-with-body --request POST \
  "https://api.telegram.org/bot${CHANNELS__TELEGRAM__BOT_TOKEN}/setWebhook" \
  --data-urlencode "url=${PROMETHEA_TELEGRAM_CALLBACK_URL}" \
  --data-urlencode "secret_token=${CHANNELS__TELEGRAM__WEBHOOK_SECRET}" \
  --data-urlencode 'allowed_updates=["message"]' \
  --data 'drop_pending_updates=false'
```

根 `.env` 不会自动变成 shell 环境变量。PowerShell 可用 `$env:...` 和 `Invoke-RestMethod` 提交同样参数。不要执行来源不明的凭证加载脚本。诊断可调用官方 `getWebhookInfo` 查看待处理数量和最后错误；不要公开含 Bot Token 的 URL。

Webhook 与 `getUpdates` polling 不能同时消费同一个 Bot。不要让别的程序争抢消息；迁移回 polling 前由部署者显式调用 `deleteWebhook`。

## 绑定与验收

1. Promethea **设置 → 消息平台 → Telegram** 生成绑定码。
2. Telegram 私聊自己的 Bot，点 Start，再发送 `/bind ...`。
3. 收到 `[Runtime]` 绑定确认，返回设置刷新。
4. 发普通文本，确认模型回复和 Web 会话历史。
5. 同一 `update_id` 重投不应重复运行模型；错误 Secret Token 应被拒绝。

回复使用纯文本，不启用 HTML/Markdown parse_mode。长回复分段有上限；平台拒绝和结果不明分别记录，未知发送结果不自动重试。当前不宣称跨平台 exactly-once。

隔离、审批、解绑、队列和恢复见 [接入总览](README.md)。Bot Token 只在部署端使用，不是模型 API Key。
