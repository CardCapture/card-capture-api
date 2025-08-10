from io import BytesIO
import base64
import importlib

try:
    import qrcode  # type: ignore
except Exception:  # pragma: no cover - runtime import guard
    qrcode = None  # Will be resolved lazily at call time


def qr_png_data_uri(payload: str, box_size: int = 10, border: int = 2) -> str:
    """Generate a PNG QR code as a data URI for the given payload.

    Args:
        payload: The string to encode in the QR image. Prefer opaque tokens.
        box_size: Pixel size of each QR box.
        border: Border width around the QR code.

    Returns:
        A data URI string suitable for embedding in HTML <img src="...">.
    """
    global qrcode
    if qrcode is None:
        try:
            qrcode = importlib.import_module("qrcode")  # type: ignore
        except Exception as _:
            raise RuntimeError(
                "qrcode library is not installed. Add `qrcode` to requirements.txt."
            )

    image = qrcode.make(payload, box_size=box_size, border=border)
    buffer = BytesIO()
    image.save(buffer, format="PNG")
    return "data:image/png;base64," + base64.b64encode(buffer.getvalue()).decode()


