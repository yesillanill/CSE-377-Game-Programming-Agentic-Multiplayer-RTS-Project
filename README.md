# CSE-377-Game-Programming-Agentic-Multiplayer-RTS-Project

Unity 6 + Photon PUN 2 real-time strategy game with an in-game **AI Strategic Commander**
(custom MCP server + local LLM via Ollama + RAG + JSON-Schema action plans + player approval), player-to-player chat
and a single-player **Play vs AI** mode whose opponent bot uses the **Laya** decision model.

| Folder | Content |
|---|---|
| `UnityRTS/` | Unity project |
| `ai/` | AI gateway, custom MCP server, agent, RAG knowledge base, Laya decision layer (`ai/decision`), tests |
| `evaluation/` | evaluation prompts, snapshots, runner, results, security tests, `laya_benchmark.py` |
| `docs/` | `architecture.md`, `setup.md` |

## Python environment (ai/.venv)

1. Create the venv: `py -3 -m venv ai\.venv`
2. **Install the CUDA build of PyTorch first** from https://pytorch.org/get-started/locally/, e.g.
   `ai\.venv\Scripts\python.exe -m pip install torch --index-url https://download.pytorch.org/whl/cu130`
   (a plain `pip install -r requirements.txt` on an empty venv would pull the CPU-only torch as a dependency of laya).
3. Then: `ai\.venv\Scripts\python.exe -m pip install -r ai\requirements.txt` (tests: `-r ai\requirements-dev.txt`).
4. `ollama pull llama3.1:8b`

The first gateway start downloads the Laya `multilingual` checkpoint (~1.3 GB, Hugging Face cache in
`%USERPROFILE%\.cache\huggingface`, outside the repo). Secrets go to `ai/.env` (read by the gateway, never by Unity; ignored by git).

## Running

The game starts everything automatically: `AiServiceLauncher` (MainMenu) reads
`UnityRTS/Assets/StreamingAssets/ai_services.json`, checks `GET http://127.0.0.1:8765/health` and `http://127.0.0.1:11434/api/tags`,
starts what is missing (hidden, logs in `%USERPROFILE%\AppData\LocalLow\<company>\<product>\Logs`) and stops it on exit only if it started it.

Manual start (if needed), one line from the repo root:

    cd ai && .venv\Scripts\python.exe -m gateway

Tests: `cd ai && .venv\Scripts\python.exe -m pytest tests -q` · Laya benchmark: `cd ai && .venv\Scripts\python.exe ..\evaluation\laya_benchmark.py`

## VsAI bot decisions (Laya + heuristic)

`POST /bot/decide`: hard constraints (options the validator would reject are never offered) → optional RAG knowledge
(same index as `search_game_knowledge`, injection-screened) → Laya → `final = w × Laya + (1 − w) × heuristic`.
Settings (`ai/.env` or environment): `RTS_RAG_ENRICHMENT` (true), `RTS_RAG_MAX_RECORDS` (2), `RTS_RAG_MAX_CHARS` (200),
`RTS_BLEND_WEIGHT` (0.4), `RTS_ATTACK_RATIO` (1.3), `RTS_MIN_ARMY` (4), `RTS_MAX_TOWERS` (3), `RTS_MAX_DEFENSE_SHARE` (0.25),
`RTS_LAYA_BOT_MODEL` (auto = `ai/models/laya-bot` if present, else typed-decisions). The Unity side has the same knobs on
`VsAI_Systems > BotController > Config`.

Evaluation: `..\evaluation\bot_decision_eval.py` (35 hand-written scenarios), `..\evaluation\laya_rag_compare.py`.

Synthetic fine-tune (teacher = the heuristic; output in `ai/models/laya-bot`, not committed):

    cd ai
    .venv\Scripts\python.exe -m laya_finetune.generate_dataset --rows 4000
    .venv\Scripts\python.exe -m laya_finetune.train --epochs 2

See [docs/setup.md](docs/setup.md).
