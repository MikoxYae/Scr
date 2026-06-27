import math
import tempfile
import requests
from io import BytesIO
from PIL import Image

THUMB_W, THUMB_H = 320, 240


def make_collage(thumb_urls: list, max_thumbs: int = 9) -> str | None:
    images = []
    for url in thumb_urls[:max_thumbs]:
        try:
            r = requests.get(url, timeout=10)
            img = Image.open(BytesIO(r.content)).convert("RGB")
            img = img.resize((THUMB_W, THUMB_H), Image.LANCZOS)
            images.append(img)
        except Exception:
            pass

    if not images:
        return None

    cols = min(3, len(images))
    rows = math.ceil(len(images) / cols)
    canvas = Image.new("RGB", (THUMB_W * cols, THUMB_H * rows), (15, 15, 15))

    for i, img in enumerate(images):
        canvas.paste(img, ((i % cols) * THUMB_W, (i // cols) * THUMB_H))

    tmp = tempfile.NamedTemporaryFile(suffix=".jpg", delete=False, dir="data")
    canvas.save(tmp.name, "JPEG", quality=85)
    tmp.close()
    return tmp.name


def download_thumb(url: str) -> str | None:
    try:
        r = requests.get(url, timeout=10)
        tmp = tempfile.NamedTemporaryFile(suffix=".jpg", delete=False, dir="data")
        tmp.write(r.content)
        tmp.close()
        return tmp.name
    except Exception:
        return None
