# 01. Tools and how to install them

You need seven things. Two of them trip people up: the Python version and the audio loopback. Do those carefully.

| Tool | Why | Required? |
|---|---|---|
| Python 3.12 | Runs everything | Yes |
| VS Code | Editor, debugger, runs server and client side by side | Yes |
| Git | Version control | Yes |
| OpenAI API key | Realtime model access | Yes |
| Excalidraw | Architecture diagram | Yes for the demo |
| Audio loopback | Lets the co-pilot hear the other people on the call | Yes for real calls |
| Docker | Deploying the server | Only for step 08 |

## Python 3.12

Use 3.12. Not 3.13, not 3.10. PySide6, onnxruntime and OpenCV all ship wheels for 3.12 on every OS, and 3.12 is what the Dockerfile uses. Same version locally and in prod means fewer surprises.

**Windows**

```powershell
winget install -e --id Python.Python.3.12
```

Or download from python.org and tick "Add python.exe to PATH" on the first screen. Then check:

```powershell
py -3.12 --version
```

**macOS**

```bash
brew install python@3.12
python3.12 --version
```

No Homebrew? Install it from brew.sh first.

**Ubuntu / Debian**

```bash
sudo apt update
sudo apt install -y python3.12 python3.12-venv libportaudio2
python3.12 --version
```

`libportaudio2` matters on Linux. Without it, `sounddevice` fails with "PortAudio library not found". On Windows and macOS the wheel bundles PortAudio, so you skip this.

## VS Code

Download from code.visualstudio.com. Or:

```powershell
winget install -e --id Microsoft.VisualStudioCode
```

```bash
brew install --cask visual-studio-code
```

The project ships `.vscode/extensions.json`, so VS Code will prompt you to install these when you open the folder:

- Python and Pylance (`ms-python.python`, `ms-python.vscode-pylance`)
- Python Debugger (`ms-python.debugpy`)
- Ruff (`charliermarsh.ruff`), formatter and linter
- Excalidraw (`pomdtr.excalidraw-editor`), opens `.excalidraw` files inside VS Code
- DotENV (`mikestead.dotenv`), syntax colors for `.env`

## Git

```powershell
winget install -e --id Git.Git
```

```bash
brew install git
sudo apt install -y git
```

## OpenAI API key

1. Go to platform.openai.com, then API keys, then create a new secret key.
2. Add billing credit. Realtime models do not run on a free tier.
3. Open the Models page and confirm the Realtime model name you will use. This guide defaults to `gpt-realtime-2.1`. Names change. If yours differs, you only change one line in `.env`.

Treat the key like a password. It lives in `.env`, and `.env` is in `.gitignore`.

## Excalidraw

Two ways, same file format:

- Browser: excalidraw.com. Nothing to install.
- Inside VS Code: the Excalidraw extension above. Open `docs/architecture.excalidraw` and it renders as a canvas.

## Audio loopback (the part everyone skips)

Your microphone hears you. It does not hear the person on the other end of the Zoom call, especially with headphones on. To fact-check them, the co-pilot needs the system audio too.

The trick: create one virtual input device that contains your mic plus the call audio, and point the client at it.

**macOS: BlackHole**

```bash
brew install blackhole-2ch
```

Then in Audio MIDI Setup:

1. Click `+`, Create Multi-Output Device. Tick your headphones and BlackHole 2ch. Set it as your system output. Now you hear the call and BlackHole gets a copy.
2. Click `+`, Create Aggregate Device. Tick your microphone and BlackHole 2ch. This is the device the co-pilot listens to.

**Windows: VB-Audio Virtual Cable or VoiceMeeter**

Install VB-CABLE from vb-audio.com. The simplest setup is VoiceMeeter (same site): route your mic and the system output into one virtual output, then pick "VoiceMeeter Output" as the client's input device. Some laptops also have "Stereo Mix" under Sound settings, Recording, Show disabled devices. If you have it, that works too.

**Linux (PulseAudio / PipeWire)**

Use the "Monitor of" source for your output device. It shows up in `scripts/list_devices.py`.

Do this later if you want. For the first runs, your mic alone is enough.

One honest note. You are recording other people. Tell them an assistant is listening, and check your local consent laws before using this on real calls.

## Docker (optional)

Only for deploying in step 08. Install Docker Desktop from docker.com, or `sudo apt install docker.io` on Linux.

## Checklist

```bash
python3.12 --version
git --version
code --version
```

All three print a version? Move on to [02. Folder structure](02-folder-structure.md).
