import sys
import time
import paho.mqtt.client as mqtt

# usage: python send.py "a"    or   python send.py '{"power":1,"temp":26}'
payload = sys.argv[1] if len(sys.argv) > 1 else "a"
got = []


def on_connect(c, u, f, rc):
    c.subscribe("ac/#", 1)


def on_subscribe(c, u, mid, g):
    c.publish("ac/cmd", payload, qos=1)


def on_message(c, u, m):
    got.append((m.topic, bytes(m.payload).decode("utf-8", "replace")))


c = mqtt.Client(mqtt.CallbackAPIVersion.VERSION1, "pc-send")
c.on_connect = on_connect
c.on_subscribe = on_subscribe
c.on_message = on_message
c.connect("127.0.0.1", 1883, 30)
c.loop_start()
time.sleep(4)
c.loop_stop()
c.disconnect()
print("sent ac/cmd =", payload)
for t, p in got:
    print("  <-", t, p)
