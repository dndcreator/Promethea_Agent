# Using a Local Model with Promethea

Promethea works with any model server that implements the OpenAI Chat Completions API (`/v1/chat/completions`).  
This includes vLLM, Ollama (via its OpenAI proxy), LM Studio, llama.cpp server, and similar tools.

---

## How it works

Promethea's `APIConfig` maps directly to an OpenAI-style client:

```python
# Internally:
client = OpenAI(api_key=cfg.api.api_key, base_url=cfg.api.base_url)
response = client.chat.completions.create(model=cfg.api.model, ...)
```

If your local server provides a compatible endpoint, it just works.

---

## Configuration

Set all three fields together in `.env`:

```bash
API__API_KEY=dummy-local-key     # required field; most local servers ignore the value
API__BASE_URL=http://127.0.0.1:8001/v1
API__MODEL=your-model-id         # must exactly match the model ID your server uses
```

> ⚠️ The model ID must match what your server reports. If your vLLM instance serves `meta-llama/Llama-3-8B-Instruct`, set `API__MODEL=meta-llama/Llama-3-8B-Instruct`.

---

## vLLM

Start vLLM with the OpenAI-compatible server:

```bash
python -m vllm.entrypoints.openai.api_server \
  --model meta-llama/Llama-3-8B-Instruct \
  --port 8001
```

`.env`:
```bash
API__API_KEY=dummy
API__BASE_URL=http://127.0.0.1:8001/v1
API__MODEL=meta-llama/Llama-3-8B-Instruct
```

---

## Ollama

Ollama exposes an OpenAI-compatible API at port 11434 by default.

Pull and run a model:
```bash
ollama pull llama3
ollama serve
```

`.env`:
```bash
API__API_KEY=dummy
API__BASE_URL=http://127.0.0.1:11434/v1
API__MODEL=llama3
```

---

## LM Studio

Enable the local server in LM Studio (Settings → Local Server → Start).  
Default port is 1234.

`.env`:
```bash
API__API_KEY=lm-studio
API__BASE_URL=http://127.0.0.1:1234/v1
API__MODEL=your-loaded-model-name
```

The model name must match what LM Studio shows as the loaded model identifier.

---

## llama.cpp server

```bash
./server -m your-model.gguf --port 8001 --api-key dummy
```

`.env`:
```bash
API__API_KEY=dummy
API__BASE_URL=http://127.0.0.1:8001/v1
API__MODEL=your-model.gguf
```

---

## Using a separate model for memory extraction

If you want a fast/cheap model for memory operations but a larger model for conversation:

```bash
# Main conversation model
API__API_KEY=dummy
API__BASE_URL=http://127.0.0.1:8001/v1
API__MODEL=llama3-70b

# Separate memory extraction model (optional)
MEMORY__API__USE_MAIN_API=false
MEMORY__API__API_KEY=dummy
MEMORY__API__BASE_URL=http://127.0.0.1:8002/v1
MEMORY__API__MODEL=llama3-8b
```

---

## Troubleshooting

**`Connection refused` on startup**  
Your local server is not running or is on a different port. Start the server before running Promethea.

**`Model not found` error**  
`API__MODEL` must exactly match the model ID exposed by your server.  
For vLLM, check the model ID with: `curl http://127.0.0.1:8001/v1/models`

**Authentication error**  
Some servers require a non-empty `API__API_KEY` even if they don't validate it. Use any non-empty string.

**Streaming not working**  
Set `SYSTEM__STREAM_MODE=false` in `.env` as a workaround for servers that do not support SSE streaming.

**Slow responses or timeouts**  
Increase the timeout:
```bash
API__TIMEOUT=120
API__RETRY_COUNT=1
```
