"""Bounded, synchronized sensor payload contracts used by recording and curation."""
import math
import struct
import zlib


def validate_frame(name, frame, payload, timestamp):
    expected = {"media_type", "shape", "dtype", "units", "coordinate_frame", "timestamp", "sensor_version"}
    if set(frame) != expected or not isinstance(payload, bytes):
        raise ValueError("invalid modality frame contract")
    shape = frame["shape"]
    rank = 3 if name == "rgb" else 2
    if name not in ("rgb", "depth") or not isinstance(shape, list) or len(shape) != rank or any(type(x) is not int or not 0 < x <= 4096 for x in shape):
        raise ValueError("invalid modality shape")
    if type(frame["timestamp"]) not in (int, float) or frame["timestamp"] != timestamp:
        raise ValueError("unsynchronized modality timestamp")
    if not all(isinstance(frame[k], str) and frame[k] for k in ("coordinate_frame", "sensor_version")):
        raise ValueError("modality sensor/frame provenance required")
    if name == "depth":
        if (frame["media_type"], frame["dtype"], frame["units"]) != ("application/x-depth-f32", "float32-le", "m") or len(payload) != math.prod(shape)*4:
            raise ValueError("invalid depth encoding or units")
        if any(not math.isfinite(x[0]) or x[0] < 0 for x in struct.iter_unpack("<f", payload)):
            raise ValueError("invalid depth values")
    else:
        if (frame["media_type"], frame["dtype"], frame["units"]) != ("image/png", "uint8", "intensity") or shape[2] != 3 or payload[:8] != b"\x89PNG\r\n\x1a\n":
            raise ValueError("invalid RGB encoding")
        index, compressed, header, ended = 8, bytearray(), None, False
        while index < len(payload):
            if index+12 > len(payload): raise ValueError("truncated PNG")
            length = struct.unpack(">I", payload[index:index+4])[0]
            end = index+12+length
            if end > len(payload): raise ValueError("truncated PNG chunk")
            kind, content = payload[index+4:index+8], payload[index+8:end-4]
            if zlib.crc32(kind+content) != struct.unpack(">I", payload[end-4:end])[0]: raise ValueError("PNG checksum mismatch")
            if kind == b"IHDR": header = content
            elif kind == b"IDAT": compressed.extend(content)
            elif kind == b"IEND": ended = True
            index = end
        if not ended or header != struct.pack(">IIBBBBB", shape[1], shape[0], 8, 2, 0, 0, 0): raise ValueError("PNG shape/encoding mismatch")
        expected_size = shape[0]*(shape[1]*3+1)
        decoder = zlib.decompressobj()
        pixels = decoder.decompress(bytes(compressed), expected_size+1)
        if len(pixels) != expected_size or not decoder.eof: raise ValueError("PNG frame size mismatch")
