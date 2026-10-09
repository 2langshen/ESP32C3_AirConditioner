import sys
import time
import paho.mqtt.client as mqtt

qos = int(sys.argv[1]) if len(sys.argv) > 1 else 0


def on_connect(c, u, f, rc):
    c.subscribe("ac/state", 0)
    c.subscribe("ac/cmd", 0)


c = mqtt.Client(mqtt.CallbackAPIVersion.VERSION1, "mimic")
c.on_connect = on_connect
c.connect("127.0.0.1", 1883, 30)
c.loop_start()
time.sleep(1.0)
print("connected before publish:", c.is_connected())
c.publish("ac/cmd", "a", qos=qos)
time.sleep(2.5)
print("connected after publish(qos%d):" % qos, c.is_connected())
c.loop_stop()
c.disconnect()
