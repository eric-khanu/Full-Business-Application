# inventory/barcode.py
"""
Barcode rendering helpers.

Requires: `pip install python-barcode pillow`
"""
import base64
import io

try:
    from barcode import EAN13, Code128
    from barcode.writer import ImageWriter
    HAS_BARCODE = True
except ImportError:
    HAS_BARCODE = False


def barcode_data_uri(value: str) -> str:
    """
    Return a data: URI for the barcode PNG, or empty string on failure.

    Uses EAN-13 when the value has exactly 13 digits, otherwise Code128.
    """
    if not value or not HAS_BARCODE:
        return ""

    value = str(value).strip()
    buffer = io.BytesIO()

    try:
        if len(value) == 13 and value.isdigit():
            # python-barcode generates the check digit — pass first 12
            EAN13(value[:12], writer=ImageWriter()).write(buffer)
        else:
            Code128(value, writer=ImageWriter()).write(buffer)
    except Exception:
        return ""

    b64 = base64.b64encode(buffer.getvalue()).decode("ascii")
    return f"data:image/png;base64,{b64}"