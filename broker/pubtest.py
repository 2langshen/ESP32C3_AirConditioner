import time
import paho.mqtt.client as mqtt

PAYLOADS = [
    '{"power":1,"mode":0,"temp":26}',   # on, cool, 26
    '{"temp":28}',                       # temp only
    '{"mode":1}',                        # heat
    '{"power":0}',                       # off
]
got = []


def on_connect(c, u, f, rc):
    c.subscribe("ac/#", 1)


def on_subscribe(c, u, mid, g):
    for p in PAYLOADS:
        c.publish("ac/cmd", p, qos=1)
        time.sleep(0.8)


def on_message(c, u, m):
    got.append((m.topic, bytes(m.payload).decode("utf-8", "replace")))


c = mqtt.Client(mqtt.CallbackAPIVersion.VERSION1, "pc-pub")
c.on_connect = on_connect
c.on_subscribe = on_subscribe
c.on_message = on_message
c.connect("127.0.0.1", 1883, 30)
c.loop_start()
time.sleep(6)
c.loop_stop()
c.disconnect()
print("sent:", PAYLOADS)
print("received:", got)
