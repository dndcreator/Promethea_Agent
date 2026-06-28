# Community Extensions

Put community MCP-style extensions here. Each extension should live in its own folder and include an `agent-manifest.json` file.

Example layout:

```text
extensions/community/my_tool/
  agent-manifest.json
  service.py
```

After adding or editing an extension, use the Web UI Settings -> Advanced Capabilities & Visibility -> Extensions & Tools -> Hot Reload, or call `POST /api/extensions/reload`.

Do not place API keys or user data in this directory. Sensitive values belong in `.env` or `config/users/<user_id>/secrets.env`.
