"""A real FIT file, built byte by byte, so the decoder is tested rather than trusted.

There is no sample recording in this repository and none in `fitdecode`, so the
alternative was a mock that returns whatever the parser expects — which tests that the
parser agrees with itself. This writes an actual FIT file: the 14-byte header with its
own CRC, definition messages declaring each field's number, size and base type, data
messages in that layout, and the file CRC over everything.

It is more code than a fixture usually deserves, and it earns it: the scaling and
offsets below (altitude stored as `(metres + 500) x 5`, position in semicircles, speed
in millimetres per second) are exactly the conventions a decoder gets wrong, and a
hand-written blob is the only way to assert that the numbers coming out are the
numbers that went in.
"""

import io
import struct

CRC_TABLE = [
    0x0000,
    0xCC01,
    0xD801,
    0x1400,
    0xF001,
    0x3C00,
    0x2800,
    0xE401,
    0xA001,
    0x6C00,
    0x7800,
    0xB401,
    0x5000,
    0x9C01,
    0x8801,
    0x4400,
]


def crc16(data, crc=0):
    for byte in data:
        for _ in range(2):
            tmp = CRC_TABLE[crc & 0xF]
            crc = (crc >> 4) & 0x0FFF
            crc = crc ^ tmp ^ CRC_TABLE[byte & 0xF]
            byte >>= 4
    return crc


SEMI = 2**31 / 180.0
EPOCH = 631065600  # 1989-12-31 UTC in unix seconds


def build(points, *, start_unix=1700000000):
    body = io.BytesIO()
    # --- file_id definition, local type 0
    body.write(bytes([0x40, 0x00, 0x00]))
    body.write(struct.pack("<H", 0))  # global msg 0 = file_id
    body.write(bytes([2]))  # 2 fields
    body.write(bytes([0, 1, 0x00]))  # type, 1 byte, enum
    body.write(bytes([4, 4, 0x86]))  # time_created, uint32
    body.write(bytes([0x00, 4]))  # data: type=4 (activity)
    body.write(struct.pack("<I", start_unix - EPOCH))

    # --- record definition, local type 1
    fields = [
        (253, 4, 0x86),
        (0, 4, 0x85),
        (1, 4, 0x85),
        (2, 2, 0x84),
        (3, 1, 0x02),
        (4, 1, 0x02),
        (5, 4, 0x86),
        (6, 2, 0x84),
        (7, 2, 0x84),
    ]
    body.write(bytes([0x41, 0x00, 0x00]))
    body.write(struct.pack("<H", 20))
    body.write(bytes([len(fields)]))
    for num, size, base in fields:
        body.write(bytes([num, size, base]))

    for i, p in enumerate(points):
        body.write(bytes([0x01]))
        body.write(struct.pack("<I", start_unix + i - EPOCH))
        body.write(struct.pack("<i", int(p["lat"] * SEMI)))
        body.write(struct.pack("<i", int(p["lon"] * SEMI)))
        body.write(struct.pack("<H", int((p["alt"] + 500) * 5)))
        body.write(bytes([p["hr"]]))
        body.write(bytes([p["cad"]]))
        body.write(struct.pack("<I", int(p["dist"] * 100)))
        body.write(struct.pack("<H", int(p["speed"] * 1000)))
        body.write(struct.pack("<H", p["power"]))

    data = body.getvalue()
    header = struct.pack("<BBHI4s", 14, 0x20, 2100, len(data), b".FIT")
    header += struct.pack("<H", crc16(header))
    out = header + data
    return out + struct.pack("<H", crc16(out))
