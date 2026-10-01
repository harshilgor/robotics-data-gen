"""Orthographic diagnostic sensor for the Cartesian surrogate, not photorealism."""
import struct
import zlib


def capture(environment, requested, timestamp):
    width = height = 32
    colors = bytearray([35, 35, 35] * width * height)
    depth = [1.] * (width * height)
    for role, color in (("target", (70, 210, 90)), ("object", (210, 100, 60)), ("eef", (80, 150, 240))):
        x, y, z = environment[role]
        column = round(x / .4 * (width-1))
        row = round((y + .2) / .4 * (height-1))
        for r in range(max(0, row-1), min(height, row+2)):
            for c in range(max(0, column-1), min(width, column+2)):
                index = r*width+c
                colors[index*3:index*3+3] = bytes(color)
                depth[index] = max(0., 1.-z)
    def chunk(name, content):
        return struct.pack(">I", len(content)) + name + content + struct.pack(">I", zlib.crc32(name+content))
    results = {}
    for modality in requested:
        if modality == "rgb":
            rows = b"".join(b"\0" + colors[r*width*3:(r+1)*width*3] for r in range(height))
            payload = (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
                       + chunk(b"IDAT", zlib.compress(rows)) + chunk(b"IEND", b""))
            shape, dtype, units, media = [height, width, 3], "uint8", "intensity", "image/png"
        elif modality == "depth":
            payload = struct.pack("<" + "f"*len(depth), *depth)
            shape, dtype, units, media = [height, width], "float32-le", "m", "application/x-depth-f32"
        else:
            raise ValueError("unsupported synthetic modality")
        results[modality] = {"payload": payload, "media_type": media, "shape": shape, "dtype": dtype,
            "units": units, "coordinate_frame": "synthetic_camera", "timestamp": timestamp,
            "sensor_version": "orthographic-diagnostic-1.0"}
    return results
