import sounddevice as sd

for index, device in enumerate(sd.query_devices()):
    if device["max_input_channels"] > 0:
        print(f"{index:>3}  in={device['max_input_channels']}  {int(device['default_samplerate'])} Hz  {device['name']}")
print(f"\nDefault input: {sd.default.device[0]}")
