"""LAN HTTP -> MQTT bridge for Siri Shortcuts.

Listens on http://<PC-IP>:8080 and publishes to the local MQTT broker (ac/cmd).
Siri: Shortcuts app -> "Get Contents of URL" -> one of the URLs below.

Endpoints (all return "OK ..."):
  /                     help
  /p  /toggle /on /off  toggle power (the working frame is a toggle)
  /mode/cool|heat|auto|fan|dry
  /temp/16 .. /temp/30
  /fan/0 .. /fan/3
  /wind/0 .. /wind/6
  /raw?p=<payload>      publish raw payload to ac/cmd
  /state                last ac/state JSON received
"""
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

import paho.mqtt.client as mqtt

MQTT_HOST = "127.0.0.1"
MQTT_PORT = 1883
CMD_TOPIC = "ac/cmd"
STATE_TOPIC = "ac/state"
HTTP_PORT = 8080

_last_state = {"value": None}
_lock = threading.Lock()

client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION1, "siri-bridge")


def on_connect(c, u, f, rc):
    c.subscribe(STATE_TOPIC, 1)
    print("[mqtt] connected, subscribed", STATE_TOPIC, flush=True)


def on_message(c, u, m):
    if m.topic == STATE_TOPIC:
        with _lock:
            _last_state["value"] = bytes(m.payload).decode("utf-8", "replace")


client.on_connect = on_connect
client.on_message = on_message
client.connect(MQTT_HOST, MQTT_PORT, 30)
client.loop_start()


def publish(payload):
    client.publish(CMD_TOPIC, payload, qos=1)
    print("[pub]", payload, flush=True)


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _reply(self, text):
        body = (text + "\n").encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        u = urlparse(self.path)
        parts = [p for p in u.path.split("/") if p]
        q = parse_qs(u.query)
        try:
            if not parts:
                return self._reply(HELP)
            head = parts[0].lower()
            arg = parts[1] if len(parts) > 1 else (q.get("v", [""])[0] or q.get("p", [""])[0])

            if head == "on":
                publish("on")
                return self._reply("OK on")
            if head == "off":
                publish("off")
                return self._reply("OK off")
            if head in ("p", "toggle", "power"):
                publish("p")
                return self._reply("OK toggle")
            if head == "mode":
                m = arg or q.get("m", [""])[0]
                mm = {"cool": 0, "heat": 1, "auto": 2, "fan": 3, "dry": 4}
                if m in mm:
                    publish(json.dumps({"mode": mm[m]}))
                    return self._reply("OK mode " + m)
                return self._reply("ERR mode")
            if head == "temp":
                t = arg or q.get("t", [""])[0]
                if t.isdigit() and 16 <= int(t) <= 30:
                    publish(json.dumps({"temp": int(t)}))
                    return self._reply("OK temp " + t)
                return self._reply("ERR temp (16..30)")
            if head == "fan":
                f = arg or q.get("f", [""])[0]
                if f.isdigit() and 0 <= int(f) <= 3:
                    publish(json.dumps({"fan": int(f)}))
                    return self._reply("OK fan " + f)
                return self._reply("ERR fan (0..3)")
            if head == "wind":
                w = arg or q.get("w", [""])[0]
                if w.isdigit() and 0 <= int(w) <= 6:
                    publish(json.dumps({"wind": int(w)}))
                    return self._reply("OK wind " + w)
                return self._reply("ERR wind (0..6)")
            if head == "sleep":
                v = arg or q.get("v", [""])[0]
                if v in ("0", "off", "false", "1", "on", "true"):
                    val = 0 if v in ("0", "off", "false") else 1
                else:
                    with _lock:
                        st = _last_state["value"]
                    cur = 0
                    if st:
                        try:
                            cur = json.loads(st).get("sleep", 0)
                        except Exception:
                            pass
                    val = 0 if cur else 1
                publish(json.dumps({"sleep": val}))
                return self._reply("OK sleep %d" % val)
            if head == "turbo":
                v = arg or q.get("v", [""])[0]
                if v in ("0", "off", "false", "1", "on", "true"):
                    val = 0 if v in ("0", "off", "false") else 1
                else:
                    with _lock:
                        st = _last_state["value"]
                    cur = 0
                    if st:
                        try:
                            cur = json.loads(st).get("turbo", 0)
                        except Exception:
                            pass
                    val = 0 if cur else 1
                publish(json.dumps({"turbo": val}))
                return self._reply("OK turbo %d" % val)
            if head == "raw":
                p = q.get("p", [""])[0] or arg
                if p:
                    publish(p)
                    return self._reply("OK raw" + p)
                return self._reply("ERR raw")
            if head == "state":
                with _lock:
                    return self._reply(json.dumps(_last_state["value"]))
            if head == "sweep":
                publish("Z")
                return self._reply("OK sweep states")
            if head == "xiaomi":
                publish("z")
                return self._reply("OK sweep xiaomi")
            return self._reply("ERR unknown: " + head)
        except Exception as e:
            return self._reply("ERR " + str(e))


HELP = """LAN AC bridge. Examples:
  /p                      toggle
  /mode/heat              set mode heat
  /temp/26                set 26C
  /fan/1                  fan low
  /wind/3                 wind 3
  /state                  last ac/state
  /raw?p=@mode_heat       raw mqtt payload
"""


def main():
    srv = ThreadingHTTPServer(("0.0.0.0", HTTP_PORT), Handler)
    print("siri-bridge listening on http://0.0.0.0:%d" % HTTP_PORT, flush=True)
    srv.serve_forever()


if __name__ == "__main__":
    main()
