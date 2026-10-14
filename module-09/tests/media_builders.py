"""Builders for Story 9.3 test media. Every input is generated in-process; nothing is downloaded.

PDFs are written with the standard library so their structure is fully known. Images are encoded
with Pillow from explicit pixel patterns.
"""

import io
import struct
import zlib

from PIL import Image

QUADRANTS = ((255, 0, 0), (0, 255, 0), (0, 0, 255), (255, 255, 255))


def quadrant_image(size: int = 16) -> Image.Image:
    """Return an RGB image split into red, green / blue, white quadrants."""
    image = Image.new("RGB", (size, size))
    half = size // 2
    for y in range(size):
        for x in range(size):
            image.putpixel((x, y), QUADRANTS[(y >= half) * 2 + (x >= half)])
    return image


def encode(image: Image.Image, fmt: str, **options: object) -> bytes:
    """Encode an image with Pillow."""
    buffer = io.BytesIO()
    image.save(buffer, format=fmt, **options)
    return buffer.getvalue()


def png_header_only(width: int, height: int) -> bytes:
    """Return a PNG whose header declares the given size but whose pixel data is tiny."""

    def chunk(kind: bytes, data: bytes) -> bytes:
        crc = zlib.crc32(kind + data) & 0xFFFFFFFF
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", crc)

    header = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", header)
        + chunk(b"IDAT", zlib.compress(b"\x00" * 16))
        + chunk(b"IEND", b"")
    )


def _escape(text: str) -> str:
    return text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


def build_pdf(pages: list[list[str]], *, title: str | None = None) -> bytes:
    """Build a minimal, valid PDF with one Helvetica text line per string on each page.

    Args:
        pages: Text lines for each page. An empty list produces a page with no text layer.
        title: Optional document-information title.

    Returns:
        The PDF bytes.
    """
    objects: list[bytes] = []
    page_ids = [4 + 2 * index for index in range(len(pages))]
    kids = " ".join(f"{pid} 0 R" for pid in page_ids)
    objects.append(b"<< /Type /Catalog /Pages 2 0 R >>")
    objects.append(f"<< /Type /Pages /Kids [{kids}] /Count {len(pages)} >>".encode())
    objects.append(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")
    for page_id, lines in zip(page_ids, pages, strict=True):
        objects.append(
            (
                "<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
                f"/Resources << /Font << /F1 3 0 R >> >> /Contents {page_id + 1} 0 R >>"
            ).encode()
        )
        if lines:
            shown = " T* ".join(f"({_escape(line)}) Tj" for line in lines)
            stream = f"BT /F1 12 Tf 14 TL 72 720 Td {shown} ET".encode("latin-1")
        else:
            stream = b"0 0 1 rg 72 72 100 100 re f"
        objects.append(
            b"<< /Length " + str(len(stream)).encode() + b" >>\nstream\n" + stream + b"\nendstream"
        )
    info_ref = ""
    if title is not None:
        objects.append(f"<< /Title ({_escape(title)}) >>".encode("latin-1"))
        info_ref = f" /Info {len(objects)} 0 R"
    out = io.BytesIO()
    out.write(b"%PDF-1.4\n")
    offsets = []
    for number, body in enumerate(objects, start=1):
        offsets.append(out.tell())
        out.write(f"{number} 0 obj\n".encode() + body + b"\nendobj\n")
    xref = out.tell()
    out.write(f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n".encode())
    for offset in offsets:
        out.write(f"{offset:010d} 00000 n \n".encode())
    out.write(
        f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R{info_ref} >>\n"
        f"startxref\n{xref}\n%%EOF\n".encode()
    )
    return out.getvalue()
