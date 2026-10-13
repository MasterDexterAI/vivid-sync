# 03. Setup: venv, requirements, model, keys

Ten minutes if nothing breaks. Run every command from the `vivid-sync` folder.

## 1. Create and activate the virtual environment

**macOS / Linux**

```bash
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
```

**Windows PowerShell**

```powershell
py -3.12 -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
```

If PowerShell refuses to run the activate script, run this once and try again:

```powershell
Set-ExecutionPolicy -Scope CurrentUser RemoteSigned
```

Your prompt now starts with `(.venv)`. Every command below assumes that.

In VS Code: `Ctrl+Shift+P`, "Python: Select Interpreter", pick the one inside `.venv`. New terminals will activate it on their own.

## 2. Write the requirements files

`requirements.txt` (local dev, server plus client):

```text
fastapi>=0.115
uvicorn[standard]>=0.30
websockets>=14
python-dotenv>=1.0
numpy>=1.26
scipy>=1.13
onnxruntime>=1.18
opencv-python>=4.10
mss>=9.0
sounddevice>=0.5
PySide6>=6.7
pyobjc-framework-Cocoa>=10.3; sys_platform == "darwin"
```

`requirements-server.txt` (what the deployed server needs):

```text
fastapi>=0.115
uvicorn[standard]>=0.30
websockets>=14
python-dotenv>=1.0
numpy>=1.26
scipy>=1.13
onnxruntime>=1.18
```

Why each one is there:

- `fastapi`, `uvicorn[standard]`: the gateway. The `[standard]` extra pulls in a fast WebSocket implementation.
- `websockets`: the client side of both sockets. The server uses it to reach OpenAI, the desktop app uses it to reach the server. Version 14 or newer, because the code uses the `additional_headers` argument.
- `numpy`, `scipy`: audio as arrays, and `resample_poly` to turn 24 kHz audio into the 16 kHz Silero expects.
- `onnxruntime`: runs Silero VAD in under a millisecond without installing PyTorch.
- `opencv-python`: blur, diff, threshold, JPEG encode.
- `mss`: fast cross-platform screenshots.
- `sounddevice`: microphone and loopback capture through PortAudio.
- `PySide6`: the HUD window.
- `pyobjc-framework-Cocoa`: macOS only, for hiding the HUD from screen share. The marker skips it on other OSes.

## 3. Install

```bash
pip install -r requirements.txt
pip install silero-vad --no-deps
```

That second line is deliberate. The `silero-vad` package depends on PyTorch, which is a download of several hundred MB you do not need. We only want the ONNX file inside it. `--no-deps` grabs the package without torch.

## 4. Pull out the VAD model

`scripts/fetch_vad_model.py`:

```python
import importlib.util
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TARGET = ROOT / "models" / "silero_vad.onnx"


def main():
    spec = importlib.util.find_spec("silero_vad")
    if spec is None or not spec.submodule_search_locations:
        sys.exit("silero-vad is not installed. Run: pip install silero-vad --no-deps")
    source = Path(list(spec.submodule_search_locations)[0]) / "data" / "silero_vad.onnx"
    if not source.exists():
        sys.exit(f"Model not found at {source}")
    TARGET.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy(source, TARGET)
    print(f"Copied {source.name} ({source.stat().st_size // 1024} KB) to {TARGET}")


if __name__ == "__main__":
    main()
```

```bash
python scripts/fetch_vad_model.py
```

You should see `Copied silero_vad.onnx (2272 KB)`. It finds the package without importing it, which is why torch never gets loaded.

## 5. Configure `.env`

`.env.example`:

```bash
OPENAI_API_KEY=sk-your-key-here
REALTIME_MODEL=gpt-realtime-2.1
TRANSCRIBE_MODEL=gpt-4o-transcribe
VAD_START=0.5
VAD_END=0.35
VAD_SILENCE_MS=350
MIN_TURN_MS=600
BARGE_IN=true

SERVER_URL=ws://127.0.0.1:8000/ws
AUDIO_DEVICE=
MONITOR=1
SCREEN_HZ=2
DELTA_THRESHOLD=0.015
MIN_FRAME_INTERVAL=1.0
JPEG_QUALITY=75
HIDE_FROM_CAPTURE=true
```

```bash
cp .env.example .env
```

On Windows: `copy .env.example .env`.

Open `.env` and set `OPENAI_API_KEY`. Leave everything else alone for now.

What the knobs do, once you start tuning:

- `VAD_SILENCE_MS`: how long someone must be quiet before the turn ends. Lower is faster and cuts people off more. 250 to 350 is the useful range.
- `MIN_TURN_MS`: turns shorter than this (a "yeah", an "mm-hm") are added to context but do not trigger a response. Saves money and noise.
- `BARGE_IN`: if true, a new speaker cancels the answer in progress.
- `AUDIO_DEVICE`: empty means default mic. Set it to the index of your aggregate or VoiceMeeter device later.
- `DELTA_THRESHOLD`: fraction of the screen that must change before a frame is sent. 0.015 is 1.5%.

## 6. The other config files

`.gitignore`:

```text
.venv/
__pycache__/
.env
models/*.onnx
*.wav
```

`.vscode/extensions.json`:

```json
{
  "recommendations": [
    "ms-python.python",
    "ms-python.vscode-pylance",
    "ms-python.debugpy",
    "charliermarsh.ruff",
    "pomdtr.excalidraw-editor",
    "mikestead.dotenv"
  ]
}
```

`.vscode/settings.json`:

```json
{
  "python.terminal.activateEnvironment": true,
  "editor.formatOnSave": true,
  "[python]": { "editor.defaultFormatter": "charliermarsh.ruff" },
  "files.exclude": { "**/__pycache__": true }
}
```

`.vscode/launch.json`. This gives you a "Server + Client" option in the Run and Debug panel that starts both with one click:

```json
{
  "version": "0.2.0",
  "configurations": [
    {
      "name": "Server",
      "type": "debugpy",
      "request": "launch",
      "module": "uvicorn",
      "args": ["server.main:app", "--port", "8000"],
      "envFile": "${workspaceFolder}/.env",
      "justMyCode": true
    },
    {
      "name": "Client HUD",
      "type": "debugpy",
      "request": "launch",
      "module": "client.main",
      "envFile": "${workspaceFolder}/.env"
    }
  ],
  "compounds": [
    { "name": "Server + Client", "configurations": ["Server", "Client HUD"] }
  ]
}
```

## 7. Sanity check

```bash
python -c "import fastapi, onnxruntime, cv2, mss, sounddevice, PySide6; print('all good')"
python scripts/list_devices.py
```

The second command prints your input devices with their index numbers. Write down the one you will use.

Next: [04. The server](04-server.md).
