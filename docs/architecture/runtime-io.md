# Runtime I/O

## Purpose

`ConversationService` is the LLM I/O hub. It does not own memory, tools,
reasoning, workflow, or file storage. It receives standard runtime input blocks
from those modules, compiles them for the active model, calls the LLM path, and
returns structured output to the caller.

## RuntimeBlock

`RuntimeBlock` (`gateway/runtime_io.py`) is the internal contract for material
that can enter the cognitive loop:

- `source`: `user`, `attachment`, `tool`, `action`, `memory`, `reasoning`,
  `workflow`, or `system`
- `role`: `request`, `context`, `observation`, `constraint`, or `result`
- `modality`: `text`, `image`, `file`, or `structured`
- `content`: text, JSON-like data, file metadata, or image payload
- `metadata`: labels, file ids, provenance, extraction status, and safety notes

The goal is to make user input, uploaded files, tool observations, screenshots,
memory recall, reasoning summaries, and workflow results look like the same
kind of cognitive material before they reach the model.

## ContextCompiler

`ContextCompiler` converts `RuntimeBlock` values into provider-compatible chat
message content:

- text blocks become labeled text context
- image blocks become `image_url` content parts when the active model is
  vision-capable
- image blocks fall back to extracted text/OCR when available
- unavailable visual content is represented as an explicit notice so the model
  is told not to invent visual details

This keeps multimodal support inside the LLM input layer instead of scattering
image/OCR logic across routes, tools, memory, and reasoning.

## Service Boundaries

- `ConversationService`: owns LLM input/output compilation.
- `Attachment/file store`: stores files and exposes text/blob data.
- `ToolService`: executes tools and returns observations.
- `ActionService`: owns action-run lifecycle and delegates execution to the
  existing tool-call loop.
- `MemoryService`: owns recall and memory writes.
- `ReasoningService`: owns reasoning trees and summaries.

Modules may produce or consume runtime blocks, but they should not directly
assemble provider-specific LLM messages.

## Current Scope

The first integrated path covers chat requests and uploaded attachments:

- HTTP routes pass raw `message` plus `attachments` instead of merging file text
  into the user message.
- `gateway.runtime_input_builder` creates runtime blocks for the user request
  and attachments; `ConversationService.prepare_chat_turn` consumes the
  compiled result.
- Text/document attachments compile into labeled text context.
- Image attachments compile into native image blocks for vision-capable models
  and clear fallback text for text-only models.

Tool observations already use OpenAI-style content blocks inside the existing
tool-call loop. They remain under `ToolService` / tool runtime control and can
be lifted into RuntimeBlock producers without changing the public tool contract.
