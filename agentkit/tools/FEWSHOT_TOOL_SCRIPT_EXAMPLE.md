# Tool Few-Shot Example (LLM Prompt Ready)

Use this file as a copy-paste prompt to ask an LLM to generate a new AgentKit tool.

## Copy-Paste Prompt Template

```text
You are generating a new MCP tool service for my project.

Project conventions:
1) Create two files:
   - agentkit/tools/<tool_slug>/agent-manifest.json
   - agentkit/tools/<tool_slug>/<tool_slug>.py
2) Manifest format must follow:
   - name, label, version, description, serviceType="mcp"
   - entryPoint.module = "agentkit.tools.<tool_slug>.<tool_slug>"
   - entryPoint.class = "<ClassName>"
   - capabilities.invocation_commands[] with command/description/example
   - inputSchema.type = "object"
3) Python class:
   - class name must match manifest entryPoint.class
   - provide async methods for each invocation command
   - return string output
   - include basic parameter validation and exception handling
4) Keep implementation minimal and runnable.
5) Output only the two full file contents in markdown code blocks with file paths.

Now generate tool:
- tool_slug: {{tool_slug}}
- class_name: {{ClassName}}
- label: {{Tool Label}}
- description: {{What this tool does}}
- commands:
  - {{command_1}}: {{description_1}}
  - {{command_2}}: {{description_2}}
- input fields:
  - {{field_name}} ({{type}}): {{description}}
```

## Concrete Few-Shot Example

### File: `agentkit/tools/text_utils/agent-manifest.json`

```json
{
    "name": "text_utils",
    "label": "Text Utils",
    "version": "1.0.0",
    "description": "Simple text utility helpers for normalize and summarize.",
    "serviceType": "mcp",
    "entryPoint": {
        "module": "agentkit.tools.text_utils.text_utils",
        "class": "TextUtilsService"
    },
    "capabilities": {
        "invocation_commands": [
            {
                "command": "normalize_text",
                "description": "Normalize spaces and line breaks.",
                "example": "normalize_text(text='  hello\\nworld  ')"
            },
            {
                "command": "head_summary",
                "description": "Return the first N characters as a quick summary.",
                "example": "head_summary(text='long text...', max_chars=120)"
            }
        ]
    },
    "inputSchema": {
        "type": "object",
        "properties": {
            "text": { "type": "string", "description": "Input text" },
            "max_chars": { "type": "integer", "description": "Summary char limit" }
        }
    }
}
```

### File: `agentkit/tools/text_utils/text_utils.py`

```python
"""Minimal text utility tool service."""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


class TextUtilsService:
    """Simple MCP tool service for text normalization and quick summary."""

    def __init__(self):
        self.name = "text_utils"
        logger.info("TextUtilsService initialized")

    async def normalize_text(self, text: str) -> str:
        """Normalize spaces and line breaks."""
        try:
            if not text or not text.strip():
                return "Error: text cannot be empty"
            cleaned = " ".join(text.split())
            return cleaned
        except Exception as e:
            logger.error("normalize_text failed: %s", e)
            return f"Error: normalize_text failed: {e}"

    async def head_summary(self, text: str, max_chars: int = 120) -> str:
        """Return first N chars as a quick summary."""
        try:
            if not text or not text.strip():
                return "Error: text cannot be empty"
            if max_chars <= 0:
                return "Error: max_chars must be > 0"
            normalized = " ".join(text.split())
            if len(normalized) <= max_chars:
                return normalized
            return normalized[:max_chars].rstrip() + "..."
        except Exception as e:
            logger.error("head_summary failed: %s", e)
            return f"Error: head_summary failed: {e}"
```

## Usage

1) Copy the "Copy-Paste Prompt Template".
2) Fill placeholders.
3) Send to LLM.
4) Place generated files under `agentkit/tools/<tool_slug>/`.
5) Restart service and check `/api/doctor` + tool list panel.

