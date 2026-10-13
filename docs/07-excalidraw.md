# 07. Draw it in Excalidraw

Your demo has two halves. The live call, and one diagram that explains why it is fast. The diagram is the half people screenshot.

A starter file ships at `docs/architecture.excalidraw`. Open it at excalidraw.com (menu, Open) or double-click it in VS Code with the Excalidraw extension. Then make it yours.

## What is on it

Three dashed zones, left to right: your laptop, the FastAPI gateway, OpenAI.

**Laptop**

- Mic + system audio (sounddevice, 24 kHz PCM16)
- Screen capture (mss, 2 Hz)
- OpenCV delta filter (send only when more than 1.5% changes)
- HUD overlay (PySide6, hidden from screen share)

**Gateway**

- WebSocket `/ws` (binary audio plus JSON frames)
- Silero VAD (ONNX, under 1 ms): turn start, turn end, barge-in
- Latest screen frame cache: injected only at turn end
- Tool router: `add_task`, `flag_claim`

**OpenAI**

- `gpt-realtime-2.1`: text out, tools on, server VAD off
- `knowledge/facts.md`, loaded into instructions

**Arrows and labels**

- Audio box to WebSocket: "32 ms frames"
- Screen capture down to delta filter
- Delta filter to gateway: "JPEG, only on change"
- Gateway to model: "append / commit / response.cancel"
- Frame cache to model: "input_image"
- Model back to tool router: "function calls"
- Tool router back to HUD: "delta, task, claim, latency"

And one line in red along the bottom: the budget. 350 ms VAD hangover plus about 200 ms first token. That line is the insight. Make it big.

## Five rules that make it readable

1. One color per kind of data. Blue for audio, green for screen, purple for tools, yellow for the thing a human looks at. Keep it consistent and people read the diagram in seconds.
2. Label every arrow with what travels on it, never with a verb like "sends".
3. Put the numbers on the diagram: 32 ms, 2 Hz, 1.5%, under 1 ms. Numbers are what make a technical diagram believable.
4. Left to right is time. Data enters on the left, the answer comes back on the bottom.
5. Nothing smaller than 16 px. If it will not fit, it does not belong.

## Export

Menu, Export image. PNG at 2x scale, background on, "Embed scene" ticked. Embedding the scene means you can drag the PNG back into Excalidraw later and keep editing it. Save it as `docs/architecture.png` and link it from your README.

Next: [08. Ship it](08-ship-it.md).
