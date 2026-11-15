# Setup — AI Commander and chat

## Requirements

* Windows, Unity 6 (6000.6.3f1), Photon PUN 2 (already in the project)
* Python 3.10+ (`py -3 --version`)
* [Ollama](https://ollama.com) with the model used by the project:

```
ollama pull llama3.1:8b
```

No API key is needed; the model runs locally. Nothing secret is stored in the repository.

## Run

Just start the game (Editor Play or a Windows build). When the Game scene starts, `AiGatewayLauncher` (on `AI_Systems`)
brings everything up automatically, hidden in the background:

1. If Ollama is not answering on `127.0.0.1:11434`, it runs `ollama serve`.
2. If the gateway is not answering on `127.0.0.1:8765`, it runs `ai/start_gateway.bat`. The first run creates
   `ai/.venv`, installs `ai/requirements.txt` and builds the RAG index (a few minutes, needs internet once).
   Console output goes to `ai/logs/gateway_console.log`.
3. The robot tab gets a status dot: amber = starting, green = ready, red = failed (the reason is written in the AI tab).

The gateway watches the Unity process id (`RTS_PARENT_PID`) and exits by itself when the game or the Editor
closes. In the Editor it stays up between Play sessions, so the next Play is instant. Components that are already
running are reused. The model itself is never downloaded automatically (4.9 GB); if it is missing the AI tab says
`ollama pull llama3.1:8b`.

Running `ai/start_gateway.bat` by hand still works (useful to watch the console).

For a build, copy the `ai` folder next to the game's `.exe` (or one folder above it), or set `RTS_AI_DIR`.

Every player who wants to use the AI Commander runs their own gateway + Ollama on their own computer.
The **Player** tab (chat with the opponent) works without the gateway.

Optional environment variables: `RTS_AI_MODEL` (default `llama3.1:8b`), `RTS_OLLAMA_URL`
(default `http://127.0.0.1:11434`), `RTS_GATEWAY_PORT` (default `8765`; also change `AiGatewayClient.gatewayUrl`).

## Unity scene setup

The chat panel, its prefabs and the `AI_Systems` object are saved in `Game.unity` by
**Tools ▸ RTS ▸ Setup Chat Panel (Player + AI Commander)**. Run it again after pulling UI changes; it is idempotent.

## Tests

```
cd ai
.venv\Scripts\python -m unittest discover -s tests -t .      # 42 tests, no Ollama needed
.venv\Scripts\python -m rag.build_index --query "counter cavalry"
```

Unity: **Window ▸ General ▸ Test Runner ▸ EditMode** (`AiChatTests` and the existing suites).

MCP Inspector (optional, needs Node.js):

```
cd ai
npx @modelcontextprotocol/inspector .venv\Scripts\python -m mcp_server.server --snapshot mcp_server/demo_snapshot.json
```

## Evaluation

With the gateway running:

```
ai\.venv\Scripts\python evaluation\run_eval.py
```

Writes `evaluation/results.csv`, `results_raw.jsonl` and `summary.md`.

## Demo helpers (AI tab)

* `/test-invalid` — injects a schema-valid but illegal plan (20 Cavalry without a Stable). Approve it to see
  `GameActionValidator` reject it with no state change.
* `/test-schema` — injects a plan with an unknown action type and a negative count; Unity rejects it before showing it.

## Logs

`ai/logs/agent_YYYYMMDD.jsonl` (tool calls per question), `security_*.jsonl` (cheat / injection / invalid snapshot),
`plan_decisions_*.jsonl` (approve / reject). They are git-ignored.
