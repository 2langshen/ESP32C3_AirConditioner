import paho.mqtt.client as mqtt


def on_connect(c, u, f, rc):
    print("connected; watching ac/# ... (Ctrl+C to quit)")
    c.subscribe("ac/#", 1)


def on_message(c, u, m):
    print("<-", m.topic, bytes(m.payload).decode("utf-8", "replace"), flush=True)


c = mqtt.Client(mqtt.CallbackAPIVersion.VERSION1, "pc-watch")
c.on_connect = on_connect
c.on_message = on_message
c.connect("127.0.0.1", 1883, 30)
c.loop_forever()
