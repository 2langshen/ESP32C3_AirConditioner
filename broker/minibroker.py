"""Minimal MQTT broker (3.1.1 + 5.0) for local testing: pub/sub, QoS 0/1, wildcards."""
import asyncio
import sys

LOG = True


def log(*a):
    if LOG:
        print(*a, flush=True)


def enc_len(n):
    out = bytearray()
    while True:
        b = n % 128
        n //= 128
        if n > 0:
            b |= 0x80
        out.append(b)
        if n == 0:
            return bytes(out)


def read_varint(buf, i):
    mult, value = 1, 0
    start = i
    while True:
        b = buf[i]
        i += 1
        value += (b & 0x7F) * mult
        if not (b & 0x80):
            return value, i - start
        mult *= 128


def topic_matches(filt, topic):
    f = filt.split("/")
    t = topic.split("/")
    for i, seg in enumerate(f):
        if seg == "#":
            return True
        if i >= len(t):
            return False
        if seg != "+" and seg != t[i]:
            return False
    return len(f) == len(t)


class Client:
    def __init__(self, reader, writer):
        self.reader = reader
        self.writer = writer
        self.subs = {}
        self.lock = asyncio.Lock()
        self.pid = 0
        self.mqtt5 = False
        self.last = (0, b"")

    async def send(self, data):
        async with self.lock:
            self.writer.write(data)
            await self.writer.drain()

    async def read_packet(self):
        b1 = (await self.reader.readexactly(1))[0]
        mult, value = 1, 0
        while True:
            b = (await self.reader.readexactly(1))[0]
            value += (b & 0x7F) * mult
            if not (b & 0x80):
                break
            mult *= 128
        body = await self.reader.readexactly(value) if value else b""
        self.last = (b1, body)
        return b1, body

    def next_pid(self):
        self.pid = (self.pid % 65535) + 1
        return self.pid

    def props_len(self):
        return b"\x00" if self.mqtt5 else b""

    async def deliver(self, topic, payload, qos, retain):
        t = topic.encode()
        var = len(t).to_bytes(2, "big") + t
        if qos > 0:
            var += self.next_pid().to_bytes(2, "big")
        var += self.props_len()
        flags = 0x30 | ((qos & 3) << 1) | (1 if retain else 0)
        pkt = bytes([flags]) + enc_len(len(var) + len(payload)) + var + payload
        await self.send(pkt)

    async def run(self, broker):
        while True:
            b1, body = await self.read_packet()
            typ = b1 >> 4
            if typ == 1:  # CONNECT
                nl = int.from_bytes(body[0:2], "big")
                level = body[2 + nl]
                self.mqtt5 = (level == 5)
                await self.send(bytes([0x20, 0x03, 0x00, 0x00, 0x00]) if self.mqtt5
                                else bytes([0x20, 0x02, 0x00, 0x00]))
                log("CONNECT (MQTT%s) -> CONNACK" % ("5" if self.mqtt5 else "3.1.1"))
            elif typ == 3:  # PUBLISH
                qos = (b1 >> 1) & 3
                tlen = int.from_bytes(body[0:2], "big")
                topic = body[2:2 + tlen].decode("utf-8", "replace")
                i = 2 + tlen
                if qos > 0:
                    pid = body[i:i + 2]
                    i += 2
                if self.mqtt5:
                    plen, n = read_varint(body, i)
                    i += n + plen
                payload = body[i:]
                if qos == 1:
                    await self.send((bytes([0x40, 0x04]) + pid + b"\x00\x00") if self.mqtt5
                                    else (bytes([0x40, 0x02]) + pid))
                elif qos == 2:
                    await self.send((bytes([0x50, 0x04]) + pid + b"\x00\x00") if self.mqtt5
                                    else (bytes([0x50, 0x02]) + pid))
                log("PUBLISH q%d %s = %s" % (qos, topic, payload.decode("utf-8", "replace")))
                await broker.fanout(topic, payload, qos, b1 & 1)
            elif typ == 8:  # SUBSCRIBE
                pid = body[0:2]
                i = 2
                if self.mqtt5:
                    plen, n = read_varint(body, i)
                    i += n + plen
                codes = bytearray()
                while i < len(body):
                    tlen = int.from_bytes(body[i:i + 2], "big")
                    i += 2
                    filt = body[i:i + tlen].decode("utf-8", "replace")
                    i += tlen
                    rq = body[i]
                    i += 1
                    self.subs[filt] = 1 if rq >= 1 else 0
                    codes.append(1 if rq >= 1 else 0)
                    log("SUBSCRIBE", filt)
                pkt = bytes([0x90]) + enc_len(2 + len(self.props_len()) + len(codes)) + pid + self.props_len() + bytes(codes)
                await self.send(pkt)
            elif typ == 10:  # UNSUBSCRIBE
                pid = body[0:2]
                i = 2
                if self.mqtt5:
                    plen, n = read_varint(body, i)
                    i += n + plen
                while i < len(body):
                    tlen = int.from_bytes(body[i:i + 2], "big")
                    i += 2
                    filt = body[i:i + tlen].decode("utf-8", "replace")
                    i += tlen
                    self.subs.pop(filt, None)
                await self.send((bytes([0xB0, 0x03]) + pid + b"\x00") if self.mqtt5
                                else (bytes([0xB0, 0x02]) + pid))
            elif typ == 6:  # PUBREL
                pid = body[0:2]
                await self.send((bytes([0x70, 0x04]) + pid + b"\x00\x00") if self.mqtt5
                                else (bytes([0x70, 0x02]) + pid))
            elif typ == 12:  # PINGREQ
                await self.send(bytes([0xD0, 0x00]))
            elif typ == 14:  # DISCONNECT
                log("DISCONNECT")
                return
            else:
                log("unhandled type", typ)


class Broker:
    def __init__(self):
        self.clients = set()

    async def fanout(self, topic, payload, qos, retain):
        for c in list(self.clients):
            for filt, sq in c.subs.items():
                if topic_matches(filt, topic):
                    try:
                        await c.deliver(topic, payload, min(qos, sq), retain)
                    except Exception as e:
                        log("deliver err", e)

    async def handle(self, reader, writer):
        c = Client(reader, writer)
        self.clients.add(c)
        try:
            await c.run(self)
        except Exception as e:
            log("client closed: %s: %s | last b1=0x%02x body=%s"
                % (type(e).__name__, e, c.last[0], c.last[1][:32].hex()))
        finally:
            self.clients.discard(c)
            writer.close()


async def main():
    host = sys.argv[1] if len(sys.argv) > 1 else "0.0.0.0"
    port = int(sys.argv[2]) if len(sys.argv) > 2 else 1883
    broker = Broker()
    server = await asyncio.start_server(broker.handle, host, port)
    log("minibroker listening on %s:%d" % (host, port))
    async with server:
        await server.serve_forever()


if __name__ == "__main__":
    asyncio.run(main())
