# 08. Ship it: deploy, demo, debug

"Live, deployed, demonstrable." Here is each one.

## Deploy the server

The client stays on your laptop. Only the gateway goes to the cloud. Pick a host that supports long-lived WebSockets and lets you choose a region near you and near OpenAI. Render, Railway, Fly.io and any small VM all work.

`Dockerfile`:

```dockerfile
FROM python:3.12-slim
WORKDIR /app
COPY requirements-server.txt .
RUN pip install --no-cache-dir -r requirements-server.txt && pip install --no-cache-dir silero-vad --no-deps
COPY server ./server
COPY scripts ./scripts
COPY knowledge ./knowledge
RUN python scripts/fetch_vad_model.py
EXPOSE 8000
CMD ["sh", "-c", "uvicorn server.main:app --host 0.0.0.0 --port ${PORT:-8000} --ws-ping-interval 20"]
```

Build and run it locally first:

```bash
docker build -t vivid-sync .
docker run --rm -p 8000:8000 --env-file .env vivid-sync
curl http://127.0.0.1:8000/health
```

Then deploy the same image. The steps are similar on every platform:

1. Push the repo to GitHub.
2. Create a new web service from the repo. Pick "Docker" as the runtime.
3. Add `OPENAI_API_KEY` (and any other server settings) as environment variables in the dashboard. Never bake the key into the image.
4. Deploy. You get a URL like `https://vivid-sync-xyz.onrender.com`.
5. On your laptop, set `SERVER_URL=wss://vivid-sync-xyz.onrender.com/ws` in `.env`. Note `wss`, not `ws`.

Before you share that URL with anyone: there is no auth on `/ws` yet. Anyone who finds it spends your OpenAI credit. The fastest fix is a shared token. Have the client send it as a query parameter, check it in `copilot_socket` before `accept()`, and close the socket if it is wrong.

## The 3-minute demo

Rehearse this exact script. It hits every feature once.

1. Show the diagram for 20 seconds. Point at the red budget line.
2. Start a meeting with a second device or a friend. Share your screen with a slide that has a revenue number on it.
3. Say: "As you can see, Q3 came in at 5.1 million." The HUD flags it red with the right number.
4. Your friend says: "Can you send me the pricing deck by Friday?" A task appears with owner and date.
5. Ask the friend to stop sharing and look at their screen. The HUD is not there.
6. Talk over an answer while it streams. It clears. That is barge-in.
7. Read the latency off the status line.

> Do not demo features. Demo the moment the co-pilot catches a mistake before anyone else in the room does.

## When it breaks

**HUD says "error: could not reach OpenAI"**
Wrong key, no billing, or a model name your account cannot use. Check `/health` for `key_loaded`, then check the model name on the OpenAI Models page.

**Turns never end**
Background noise keeps the VAD probability above `VAD_END`. Use headphones, or raise `VAD_END` to 0.4. Run `scripts/test_vad.py` to see the probabilities yourself.

**The co-pilot answers every "yeah" and "okay"**
Raise `MIN_TURN_MS` to 900.

**It comments on everything**
The model is ignoring the `PASS` rule. Make rule 4 in `prompts.py` stricter, or add an example of a turn where the right reply is `PASS`.

**No transcript on the HUD**
The transcription model name in `.env` is not available to you. Transcription is optional. The co-pilot still works without it.

**`PortAudio library not found`**
Linux: `sudo apt install libportaudio2`.

**`Invalid number of channels` or no audio**
Wrong `AUDIO_DEVICE`. Run `scripts/list_devices.py` and pick an index with `in=` greater than 0.

**Screen frames are black on macOS**
Screen Recording permission is missing, or granted but the app was not restarted.

**HUD shows up in the screen share**
Read [05. The client](05-client.md) again, then run Test 5 in [06](06-run-and-measure.md). On Linux there is no equivalent API.

**Session dies after an hour**
Realtime sessions have a maximum length of 60 minutes. The client reconnects on its own, but the model loses context. The upgrade: at 50 minutes, ask the model for a summary out of band, open a fresh session, and seed it with that summary.

## What to build next

In order of payoff:

1. Auth on `/ws`. Ten lines. Do it before you deploy publicly.
2. Push tasks to Linear, Notion or Slack. One new tool each.
3. `lookup_facts` backed by a vector store, once `facts.md` outgrows 20 KB.
4. Session rotation for meetings longer than an hour.
5. Speaker labels: one channel for your mic, one for system audio, so it knows who promised what.

> The best meeting tool is the one that makes you look prepared, not the one that makes a nice summary nobody reads.
