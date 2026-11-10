"""Build a bounded visual block for the canonical tool observation path."""
import base64
from io import BytesIO


def workspace_image_content(image):
    if image.width * image.height > 16_000_000:
        raise ValueError("Image exceeds 16 megapixels.")
    image.thumbnail((896, 896))
    data = BytesIO()
    image.convert("RGB").save(data, "JPEG", quality=82)
    url = "data:image/jpeg;base64," + base64.b64encode(data.getvalue()).decode("ascii")
    return [{"type": "image_url", "image_url": {"url": url}, "_workspace_media": True}]
