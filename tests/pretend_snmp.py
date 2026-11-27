"""The toner test's pretend SNMP copier (small responders on 127.0.0.1), as a module for the 19_06 / 19_07 tests."""
import socket, threading
import toners


# ------------------------------------------------------------ a pretend copier (written apart from toners.py)


def tlv(tag, body):
    n = len(body)
    ln = bytes([n]) if n < 128 else bytes([0x80 | ((n.bit_length() + 7) // 8)]) + n.to_bytes((n.bit_length() + 7) // 8, "big")
    return bytes([tag]) + ln + body


def enc_int(n, tag=0x02):
    return tlv(tag, n.to_bytes(max(1, (n.bit_length() + 8) // 8), "big", signed=True))


def enc_oid(text):
    p = [int(x) for x in text.split(".")]
    body = bytes([40 * p[0] + p[1]])
    for v in p[2:]:
        chunk = [v & 0x7F]; v >>= 7
        while v:
            chunk.insert(0, 0x80 | (v & 0x7F)); v >>= 7
        body += bytes(chunk)
    return tlv(0x06, body)


def take(data, i):
    tag, n = data[i], data[i + 1]; i += 2
    if n & 0x80:
        k = n & 0x7F; n = int.from_bytes(data[i:i + k], "big"); i += k
    return tag, data[i:i + n], i + n


def dec_oid(b):
    out, n = [b[0] // 40, b[0] % 40], 0
    for x in b[1:]:
        n = (n << 7) | (x & 0x7F)
        if not x & 0x80:
            out.append(n); n = 0
    return ".".join(map(str, out))


def key(oid):
    return tuple(int(x) for x in oid.split("."))


class PretendCopier:
    def __init__(self, port):
        self.values = {}  # oid -> ("int"/"str"/"counter", value)
        self.on = True
        self.s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.s.bind(("127.0.0.1", port))
        threading.Thread(target=self.serve, daemon=True).start()

    def encode(self, kind, v):
        return {"int": lambda: enc_int(v), "counter": lambda: enc_int(v, 0x41), "str": lambda: tlv(0x04, v.encode())}[kind]()

    def serve(self):
        while True:
            data, addr = self.s.recvfrom(65535)
            if not self.on:
                continue
            _, msg, _ = take(data, 0)
            _, ver, i = take(msg, 0); _, comm, i = take(msg, i); ptype, pdu, _ = take(msg, i)
            _, rid, j = take(pdu, 0); _, _, j = take(pdu, j); _, _, j = take(pdu, j); _, binds, _ = take(pdu, j)
            out, k = b"", 0
            while k < len(binds):
                _, bind, k = take(binds, k); _, oidb, _ = take(bind, 0)
                oid = dec_oid(oidb)
                if ptype == 0xA0:
                    val = self.values.get(oid)
                    out_oid, vb = oid, (self.encode(*val) if val else b"\x80\x00")
                else:
                    nxt = sorted((o for o in self.values if key(o) > key(oid)), key=key)
                    out_oid, vb = (nxt[0], self.encode(*self.values[nxt[0]])) if nxt else (oid, b"\x82\x00")
                out += tlv(0x30, enc_oid(out_oid) + vb)
            body = tlv(0x30, out)
            resp = tlv(0xA2, tlv(0x02, rid) + enc_int(0) + enc_int(0) + body)
            self.s.sendto(tlv(0x30, tlv(0x02, ver) + tlv(0x04, comm) + resp), addr)

    def set(self, total=None, bw=None, colour=None, levels=None, ricoh_names=True, ok_only=False):
        v = self.values
        v["1.3.6.1.2.1.1.1.0"] = ("str", "RICOH pretend copier")
        v["1.3.6.1.2.1.25.3.2.1.3.1"] = ("str", "RICOH IM Pretend")
        if total is not None:
            v["1.3.6.1.2.1.43.10.2.1.4.1.1"] = ("counter", total)
        base = "1.3.6.1.4.1.367.3.2.1.2.19.5.1"
        if bw is not None:
            v[f"{base}.5.1"] = ("str", "Total: Black & White"); v[f"{base}.9.1"] = ("int", bw)
        if colour is not None:
            v[f"{base}.5.2"] = ("str", "Total: Full Color"); v[f"{base}.9.2"] = ("int", colour)
        sup = "1.3.6.1.2.1.43.11.1.1"
        for i, c in enumerate(toners.COLOURS, start=1):
            v[f"{sup}.5.1.{i}"] = ("int", 3)
            v[f"{sup}.6.1.{i}"] = ("str", f"{c.title()} Toner")
            v[f"{sup}.8.1.{i}"] = ("int", -2 if ok_only else 100)
            v[f"{sup}.9.1.{i}"] = ("int", -3 if ok_only else levels[c])
        v[f"{sup}.5.1.5"] = ("int", 4); v[f"{sup}.6.1.5"] = ("str", "Waste Toner")
        v[f"{sup}.8.1.5"] = ("int", 100); v[f"{sup}.9.1.5"] = ("int", 60)

