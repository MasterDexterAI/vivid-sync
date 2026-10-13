# 02. Folder structure

Two programs, one repo. The server talks to OpenAI. The client lives on your laptop. They only share a WebSocket and a `.env` file.

```
vivid-sync/
├── .env.example
├── .env
├── .gitignore
├── .vscode/
│   ├── extensions.json
│   ├── launch.json
│   └── settings.json
├── Dockerfile
├── requirements.txt
├── requirements-server.txt
├── README.md
├── docs/
│   └── architecture.excalidraw
├── knowledge/
│   └── facts.md
├── models/
│   └── silero_vad.onnx
├── server/
│   ├── __init__.py
│   ├── config.py
│   ├── main.py
│   ├── prompts.py
│   ├── session.py
│   ├── tools.py
│   └── vad.py
├── client/
│   ├── __init__.py
│   ├── audio.py
│   ├── config.py
│   ├── hud.py
│   ├── main.py
│   ├── screen.py
│   └── stealth.py
└── scripts/
    ├── __init__.py
    ├── fake_client.py
    ├── fetch_vad_model.py
    ├── list_devices.py
    ├── test_screen_delta.py
    └── test_vad.py
```

## What each file does

### Root

| File | Job |
|---|---|
| `.env.example` | Every setting with a sane default. Copy it to `.env`. |
| `.env` | Your real API key and device choices. Never committed. |
| `.gitignore` | Keeps `.venv`, `.env`, the ONNX model and test WAVs out of Git. |
| `requirements.txt` | Everything for local dev: server and client. |
| `requirements-server.txt` | Server only. No Qt, no OpenCV. Used by Docker. |
| `Dockerfile` | Builds the server image for deployment. |
| `.vscode/launch.json` | One click runs server, client, or both together. |

### `server/`: the brain

| File | Job |
|---|---|
| `config.py` | Reads `.env` into one frozen settings object. |
| `vad.py` | Silero VAD on ONNX Runtime, plus the turn detector state machine. |
| `prompts.py` | The system prompt. Loads `knowledge/facts.md` into it. |
| `tools.py` | Two functions the model can call: `add_task` and `flag_claim`. |
| `session.py` | One `CopilotSession` per connected client. Audio in, VAD, frames, OpenAI socket, events out. This is the heart. |
| `main.py` | FastAPI app. `/health` and `/ws`. Ten lines. |

### `client/`: the eyes, ears and face

| File | Job |
|---|---|
| `config.py` | Server URL, audio device, monitor, screen rate. |
| `audio.py` | Captures 24 kHz mono PCM16 in 32 ms blocks. |
| `screen.py` | Captures the screen at 2 Hz and runs the OpenCV delta filter. |
| `stealth.py` | Hides the HUD window from screen sharing on Windows and macOS. |
| `hud.py` | The overlay: status, suggestion, transcript, fact checks, tasks. |
| `main.py` | Starts Qt in the main thread and the network loop in a background thread. |

### `knowledge/`

`facts.md` is what the co-pilot checks claims against. Put your real numbers here. The sample has a fake company with revenue, churn, pricing and a launch date so you can test fact-checking on day one.

### `models/`

Holds `silero_vad.onnx` (2.2 MB). Copied in by `scripts/fetch_vad_model.py`. Not committed.

### `scripts/`

| File | Job |
|---|---|
| `fetch_vad_model.py` | Copies the ONNX model out of the `silero-vad` package. |
| `list_devices.py` | Prints every input device with its index. |
| `test_vad.py` | Runs turn detection on a WAV or a live recording and prints timings. |
| `test_screen_delta.py` | Shows how many frames the delta filter keeps versus drops. |
| `fake_client.py` | Streams a WAV to the server like a real client. Your latency benchmark. |

## Create it

```bash
mkdir vivid-sync && cd vivid-sync
mkdir -p .vscode docs knowledge models server client scripts
touch server/__init__.py client/__init__.py scripts/__init__.py
code .
```

On Windows PowerShell, replace the `mkdir -p` and `touch` lines with:

```powershell
mkdir .vscode, docs, knowledge, models, server, client, scripts
ni server/__init__.py, client/__init__.py, scripts/__init__.py
```

The empty `__init__.py` files matter. They let you run `python -m client.main` and `python -m scripts.fake_client` from the project root.

Next: [03. Setup](03-setup.md).
