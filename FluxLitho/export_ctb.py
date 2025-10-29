import struct
import zlib
from PIL import Image

# Druckerparameter (Elegoo Mars 2)
PANEL_PX_W = 2560
PANEL_PX_H = 1620
PX_SIZE_MM = 0.05
LAYER_HEIGHT_MM = 0.05
EXPOSURE_TIME = 2.0


def png_to_bitmap(png_path):
    """Lädt PNG und wandelt in 1-Bit Bitmap (schwarz/weiß) um"""
    img = Image.open(png_path).convert("1")  # 1-bit
    if img.size != (PANEL_PX_W, PANEL_PX_H):
        raise ValueError(f"PNG hat falsche Größe {img.size}, erwartet {(PANEL_PX_W, PANEL_PX_H)}")
    # Pixel in Bytes packen (8 Pixel pro Byte)
    data = bytearray()
    pixels = img.load()
    for y in range(PANEL_PX_H):
        byte = 0
        bit_count = 0
        for x in range(PANEL_PX_W):
            if pixels[x, y] == 0:  # schwarz = belichtet
                byte |= (1 << (7 - bit_count))
            bit_count += 1
            if bit_count == 8:
                data.append(byte)
                byte = 0
                bit_count = 0
        if bit_count > 0:
            data.append(byte)
    return bytes(data)


def write_ctb(front_png, back_png, out_path="test.ctb"):
    # --- Layers vorbereiten ---
    layer_bitmaps = [png_to_bitmap(front_png), png_to_bitmap(back_png)]
    compressed = [zlib.compress(bm) for bm in layer_bitmaps]

    # --- Header bauen ---
    header = b"CTB\x00"              # Magic
    version = struct.pack("<I", 4)   # Version
    header_size = struct.pack("<I", 0x200)  # Header size
    res_x = struct.pack("<I", PANEL_PX_W)
    res_y = struct.pack("<I", PANEL_PX_H)
    px_size = struct.pack("<f", PX_SIZE_MM)
    layer_height = struct.pack("<f", LAYER_HEIGHT_MM)
    exp_time = struct.pack("<f", EXPOSURE_TIME)
    layer_count = struct.pack("<I", len(layer_bitmaps))

    # Platzhalter für LayerTable-Offset
    offset_layer_table = struct.pack("<I", 0x200)

    hdr = (
        header + version + header_size +
        res_x + res_y + px_size + layer_height +
        exp_time + layer_count + offset_layer_table
    )
    hdr = hdr.ljust(0x200, b"\x00")  # auffüllen auf 512 Byte

    # --- LayerTable + Layerdaten ---
    layer_entries = []
    layer_data = b""
    current_offset = len(hdr) + (len(layer_bitmaps) * 16)

    for bm, comp in zip(layer_bitmaps, compressed):
        entry = struct.pack("<IIIf", current_offset, len(comp), len(bm), EXPOSURE_TIME)
        layer_entries.append(entry)
        layer_data += comp
        current_offset += len(comp)

    layer_table = b"".join(layer_entries)

    # --- Dummy Vorschau ---
    # Einfach ein kleines 128x128 Graubild
    preview = Image.new("L", (128, 128), 180)
    preview_bytes = preview.tobytes()
    preview_offset = current_offset
    preview_size = len(preview_bytes)

    # Vorschau Header
    preview_header = struct.pack("<II", preview_offset, preview_size)

    # --- Datei schreiben ---
    with open(out_path, "wb") as f:
        f.write(hdr)
        f.write(layer_table)
        f.write(layer_data)
        f.write(preview_header)
        f.write(preview_bytes)

    print(f"✅ CTB geschrieben: {out_path} ({len(layer_bitmaps)} Layer + Vorschau)")


if __name__ == "__main__":
    write_ctb("front.png", "back.png", "test.ctb")