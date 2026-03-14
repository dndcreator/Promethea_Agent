# Backlog 013 - Channel Adapter Framework

## 1. 背景

Promethea 的长期目标包含多入口能力，但系统当前最重要的不是“入口数量”，而是“入口扩展时不破坏核心 runtime”。如果没有统一 Channel Adapter Framework，后续引入：

- Web UI
- HTTP API
- Desktop / Tauri
- Telegram
- Slack / 飞书
- Voice / Live 模式

时，很容易出现每个入口都各自拼装 session、上下文、权限和 response 的问题，导致 runtime 逻辑分裂。

本任务负责建立统一 Channel Adapter Framework。

---

## 2. 目标

本任务要完成：

1. 定义统一 channel adapter 接口
2. 让不同入口都通过 adapter 转换成统一 GatewayRequest / GatewayResponse
3. 确保 session / identity / permission 逻辑不在各入口重复发明
4. 为 future desktop、IM、voice 模式建立统一接入层

---

## 3. 非目标

本任务不负责：

- 一次性实现所有渠道
- 一次性做完最终 UI 体验
- 一次性实现复杂多端同步

本任务重点是建立 **统一接入契约**。

---

## 4. 当前代码位置

优先检查：

- Web UI 对应入口
- HTTP API 入口
- `gateway/server.py`
- 任何 desktop / Tauri 接口代码
- `channels/` 目录（如已存在）
- session / identity / response mapping 相关模块

---

## 5. 目标设计

## 5.1 ChannelAdapter 接口

建议统一接口至少包括：

- `ingest_message(raw_input) -> GatewayRequest`
- `normalize_identity(raw_input) -> IdentityContext`
- `build_session_key(raw_input) -> str`
- `emit_response(gateway_response) -> ChannelOutput`
- `emit_stream_chunk(chunk) -> ChannelChunk`
- `permission_check(identity_context) -> PermissionDecision`

---

## 5.2 Channel 元数据

每个 channel 建议有明确元信息：

- `channel_id`
- `channel_type`
- `supports_streaming`
- `supports_attachments`
- `supports_rich_artifacts`
- `supports_reactions`
- `supports_voice`
- `session_model`

---

## 5.3 第一批支持范围

第一版优先整理为：

- Web UI adapter
- HTTP API adapter
- Desktop / Tauri adapter
- Telegram adapter
- Slack 或飞书 adapter（二选一）

注意：第一版目标不是“功能全”，而是“接口统一”。

---

## 6. 推荐实现路径

## 6.1 第一步：定义 base adapter interface

建议新增：

- `channels/base.py`

定义统一抽象基类或协议接口。

---

## 6.2 第二步：重构现有 Web / HTTP 入口

目标：

- 先把已有入口都改成 adapter 模式
- 避免后续在新渠道中重复写一遍相同逻辑

---

## 6.3 第三步：统一身份与 session 映射

要求：

- 不同 channel 都明确映射到 `user_id`
- session key 构建逻辑统一抽象
- 不允许各渠道自己发明不同的 session 规则

---

## 6.4 第四步：统一 response 输出映射

要求：

- Gateway 只返回 `GatewayResponse`
- 每个 channel adapter 再把它映射成具体界面/消息格式

---

## 6.5 第五步：增加一个新渠道作为验证

建议第一批新增：

- Telegram
- 或 Slack / 飞书（二选一）

目标是验证框架，而不是追求入口数量。

---

## 7. 预期效果

完成后应达到：

- 新增一个 channel 不需要修改核心 runtime 语义
- 多入口系统结构更清晰
- 工程师与 Codex 更容易定位“入口问题”和“runtime 问题”的边界
- 为桌面常驻模式、IM 渠道、未来 voice 模式奠定接入基础

---

## 8. 测试要求

至少需要补以下测试：

1. base adapter 接口测试
2. Web adapter -> GatewayRequest 转换测试
3. HTTP adapter -> GatewayRequest 转换测试
4. GatewayResponse -> channel 输出映射测试
5. 不同 channel 的 session key 规则测试
6. identity normalization 测试

---

## 9. 验收标准

本任务完成后，必须满足：

- 已存在统一 channel adapter interface
- Web 与 HTTP 至少一条主路径已改造为 adapter 方式
- 已统一 `GatewayRequest / GatewayResponse` 的接入与输出映射
- 至少一个新渠道通过 adapter 模式接入
- channel 不再直接侵入 conversation/runtime 逻辑

---

## 10. 风险与注意事项

### 风险 1：过早追求渠道数量
本任务重点是框架统一，不是数量扩张。

### 风险 2：adapter 只是名字统一，逻辑仍然散落
必须确保 session、identity、response mapping 真正通过 adapter 抽象承载。

### 风险 3：渠道特性强行塞回核心 runtime
渠道差异应该由 adapter 处理，核心 runtime 只处理统一协议对象。

---

## 11. 回滚方案

如影响过大，可以：

- 保留 base adapter interface
- 先只改 Web / HTTP
- 新渠道暂缓
- 通过 adapter 兼容旧入口实现

不允许回滚到所有入口各写一套接入逻辑的状态。

---

## 12. 完成后应追加的文档更新

- `docs/architecture/channel-framework.md`（建议新增）
- `docs/architecture/runtime-overview.md`
- `docs/adr/ADR-013-channel-adapter-framework.md`（建议新增）

---

## 13. 建议提交信息

- `feat(channels): introduce unified channel adapter framework`
- `refactor(interface): normalize web http and im entrypoints through adapters`
