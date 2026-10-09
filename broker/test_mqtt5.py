import time
import paho.mqtt.client as mqtt

got = []


def on_connect(c, u, flags, rc, props=None):
    print("connect rc=", rc)
    c.subscribe("ac/#", qos=1)


def on_message(c, u, m):
    got.append((m.topic, bytes(m.payload).decode("utf-8", "replace")))


c = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, "pc5", protocol=mqtt.MQTTv5)
c.on_connect = on_connect
c.on_message = on_message
c.connect("127.0.0.1", 1883, 30)
c.loop_start()
time.sleep(1.0)
c.publish("ac/cmd", '{"power":1,"mode":0,"temp":26}', qos=1)
time.sleep(2.0)
c.loop_stop()
c.disconnect()
print("received:", got)
