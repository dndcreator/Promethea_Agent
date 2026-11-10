export function voiceError(error: unknown, t: (zh: string, en: string) => string): string {
  const code = typeof error === 'string' ? error : error && typeof error === 'object' && 'code' in error ? String(error.code) : error instanceof Error ? error.message : ''
  const messages: Record<string, string> = {
    VOICE_DISABLED: t('语音服务未启用', 'Speech service disabled'),
    VOICE_STATUS_UNAVAILABLE: t('无法获取语音配置', 'Could not load speech settings'),
    VOICE_MODEL_REQUIRED: t('请配置语音模型', 'Configure a speech model'),
    VOICE_ENDPOINT_REQUIRED: t('请配置语音接口', 'Configure a speech endpoint'),
    VOICE_VOICE_REQUIRED: t('请选择音色', 'Choose a voice'),
    VOICE_PROVIDER_AUTH_FAILED: t('语音接口认证失败，请检查 API Key', 'Speech authentication failed; check the API key'),
    VOICE_PROVIDER_ERROR: t('语音接口拒绝请求，请检查模型、音色和接口地址', 'Speech request rejected; check model, voice and endpoint'),
    VOICE_PROVIDER_UNAVAILABLE: t('无法连接语音接口', 'Could not connect to speech provider'),
    VOICE_PROVIDER_TIMEOUT: t('语音接口超时', 'Speech provider timed out'),
    VOICE_PROVIDER_RATE_LIMITED: t('语音接口请求过多', 'Speech provider rate limited'),
    VOICE_INVALID_ENDPOINT: t('语音接口地址无效', 'Invalid speech endpoint'),
    VOICE_INVALID_AUDIO: t('接口未返回有效音频', 'Provider did not return valid audio'),
    VOICE_INVALID_FORMAT: t('当前提供方不支持此音频格式', 'Audio format unsupported by this provider'),
    VOICE_AUDIO_TOO_LARGE: t('音频文件不能超过 24 MiB', 'Audio file cannot exceed 24 MiB'),
    VOICE_RESPONSE_TOO_LARGE: t('语音接口返回内容过大', 'Speech provider response too large'),
    VOICE_UNSUPPORTED_PROVIDER: t('不支持此语音提供方', 'Unsupported speech provider'),
    VOICE_INVALID_RESPONSE: t('语音接口响应无效', 'Invalid speech response'),
    VOICE_EMPTY_AUDIO: t('没有录到声音', 'No audio recorded'),
    VOICE_EMPTY_TRANSCRIPT: t('未识别到文字', 'No speech recognized'),
    VOICE_TEXT_TOO_LONG: t('合成文本不能超过 4096 字符', 'Speech text cannot exceed 4096 characters'),
    VOICE_MICROPHONE_DENIED: t('麦克风权限被拒绝', 'Microphone permission denied'),
    VOICE_RECORDING_UNAVAILABLE: t('当前浏览器无法录音，请检查麦克风和安全连接', 'Recording unavailable; check microphone and secure connection'),
    VOICE_RECORDING_FAILED: t('录音失败', 'Recording failed'),
  }
  return messages[code] || t('语音操作失败，请检查配置后重试', 'Speech operation failed; check configuration and retry')
}
