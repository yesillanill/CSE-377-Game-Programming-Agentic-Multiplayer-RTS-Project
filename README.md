# CSE-377-Game-Programming-Agentic-Multiplayer-RTS-Project

Unity 6 + Photon PUN 2 real-time strategy game with an in-game **AI Strategic Commander**
(custom MCP server + local LLM via Ollama + RAG + JSON-Schema action plans + player approval) and player-to-player chat.

| Folder | Content |
|---|---|
| `UnityRTS/` | Unity project |
| `ai/` | AI gateway, custom MCP server, agent, RAG knowledge base, tests |
| `evaluation/` | evaluation prompts, snapshots, runner, results, security tests |
| `docs/` | `architecture.md`, `setup.md` |

Quick start: `ollama pull llama3.1:8b`, run `ai/start_gateway.bat`, start the game, open the **AI Commander** tab.
See [docs/setup.md](docs/setup.md).
