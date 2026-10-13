# Vivid Sync: build a meeting co-pilot that answers before the meeting moves on

Every meeting AI you have used is a historian. It tells you what went wrong an hour after it went wrong.

That is the whole problem. The CFO says "Q3 was $5.1M" on a call, the real number is $4.2M, and Otter will politely write the wrong number into a beautiful summary. By then the moment is gone.

Vivid Sync is the opposite bet. It listens to the call, looks at the shared screen, and puts a correction, a task, or an answer on a small overlay while the sentence is still in the air. Under 500 ms from the end of a sentence to the first word on screen.

You will build all of it in Python. One FastAPI server. One desktop client. About 600 lines of code.

> Post-call notes are a receipt. A live co-pilot is a second brain sitting next to you.

## What actually makes it fast

Most people think latency lives in the model. It does not.

I ran the whole pipeline end to end against a mock Realtime server while writing this guide. Silero VAD took 0.71 ms per 32 ms audio frame. The gateway added about 5 ms. The model mock was set to 200 ms and the HUD saw 202 to 207 ms.

So where does the time go in a real call? Into waiting to be sure the speaker stopped. That silence window is 350 ms by default. It is the biggest number in your budget and it is a config value.

> Your latency budget is not eaten by GPT. It is eaten by politeness: waiting to be sure someone finished talking.

## Three decisions that shape the build

**The model writes, it does not talk.** The co-pilot whispers to one person through text. No synthesized voice. That kills audio output cost and makes interruption handling simple: cancel the response, done.

**Your VAD decides turns, not OpenAI's.** Server VAD is off. Silero runs inside the gateway, so you control exactly when a turn ends, when the model gets interrupted, and which audio gets billed. Silence never leaves your server.

**The screen is sent once per turn, not once per second.** The client only ships a frame when more than 1.5% of the screen changed. The server only forwards the newest one, right before the turn is committed. In my test, 30 captures of a 4K screen produced 2 frames worth sending. A blinking cursor produced zero.

## Read in this order

1. [Tools and installs](docs/01-tools.md). Python, VS Code, Git, Excalidraw, audio loopback, your API key.
2. [Folder structure](docs/02-folder-structure.md). Every file and the one job it has.
3. [Setup](docs/03-setup.md). venv, requirements, the VAD model, `.env`.
4. [The server](docs/04-server.md). FastAPI gateway, Silero VAD, the Realtime session, tools.
5. [The client](docs/05-client.md). Audio capture, screen sampling, the HUD, hiding it from screen share.
6. [Run it and measure it](docs/06-run-and-measure.md). Prove the 500 ms claim with your own numbers.
7. [Draw it in Excalidraw](docs/07-excalidraw.md). The architecture diagram you will show in the demo.
8. [Ship it](docs/08-ship-it.md). Deploy the server, run the demo, fix what breaks.

## Do this today

Build it in this order and stop after each step until it works:

1. VAD on a recorded clip. If turns are wrong, nothing above it will be right.
2. Server plus `fake_client.py` with a WAV file. No microphone, no screen, no UI.
3. Real microphone.
4. Screen frames.
5. HUD.

People who start with the overlay spend a week debugging three things at once.

Next up: making it remember across meetings, so it can say "that contradicts what you said last Tuesday." Subscribe if you want that one when it drops.
