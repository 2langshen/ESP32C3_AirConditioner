import sys
import time
import paho.mqtt.client as mqtt

host = sys.argv[1] if len(sys.argv) > 1 else "127.0.0.1"
port = int(sys.argv[2]) if len(sys.argv) > 2 else 1883
topic = sys.argv[3] if len(sys.argv) > 3 else "ac/cmd"
payload = sys.argv[4] if len(sys.argv) > 4 else "hello"

got = []

def on_connect(cl, u, flags, rc):
    print("connected rc=", rc)
    cl.subscribe("ac/#", qos=1)

def on_subscribe(cl, u, mid, granted):
    print("subscribed", granted)
    cl.publish(topic, payload, qos=1)

def on_message(cl, u, m):
    got.append((m.topic, bytes(m.payload).decode("utf-8", "replace")))

c = mqtt.Client(mqtt.CallbackAPIVersion.VERSION1, "pc-test")
c.on_connect = on_connect
c.on_subscribe = on_subscribe
c.on_message = on_message
c.connect(host, port, 30)
c.loop_start()
time.sleep(2.0)
c.loop_stop()
c.disconnect()
print("published:", topic, "=", payload)
print("received:", got)
