"""Interactive AC controller over local MQTT.

Run:  python acctl.py
Then type commands at the prompt, e.g.:
  a                 -> sweep all 5 Konka codes (power on, 3s apart)
  1 .. 5            -> lock the working code
  p                 -> toggle power       on / off
  m                 -> cycle mode         + / -  -> temp up/down
  f                 -> cycle fan speed    w      -> toggle swing
  {"power":1,"mode":0,"temp":26}   -> set several at once
  i                 -> query status       o      -> publish state
  q                 -> quit
"""
import time
import paho.mqtt.client as mqtt


def on_connect(c, u, f, rc):
    c.subscribe("ac/#", 1)
    print("[connected] watching ac/#. type 'h' for help.")


def on_message(c, u, m):
    print(time.strftime("%H:%M:%S"), "<-", m.topic, bytes(m.payload).decode("utf-8", "replace"), flush=True)


c = mqtt.Client(mqtt.CallbackAPIVersion.VERSION1, "acctl")
c.on_connect = on_connect
c.on_message = on_message
c.connect("127.0.0.1", 1883, 30)
c.loop_start()
time.sleep(0.8)

print(__doc__)
try:
    while True:
        line = input("cmd> ").strip()
        if line in ("q", "quit", "exit"):
            break
        if line == "h":
            print(__doc__)
            continue
        c.publish("ac/cmd", line if line else "i", qos=1)
except (EOFError, KeyboardInterrupt):
    pass

c.loop_stop()
c.disconnect()
print("bye")
