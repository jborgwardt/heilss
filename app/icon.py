"""Icon helpers: every app gets a 256x256 square SVG (no rounded corners)."""
import base64, hashlib, re
from xml.sax.saxutils import escape

PALETTES = [("#7c5cff", "#3b2bb5"), ("#2dd4bf", "#0f766e"), ("#f97316", "#9a3412"), ("#38bdf8", "#1d4ed8"),
            ("#f472b6", "#9d174d"), ("#a3e635", "#3f6212"), ("#facc15", "#a16207"), ("#fb7185", "#9f1239")]


def generate(name):
    h = int(hashlib.sha256(name.encode()).hexdigest(), 16)
    a, b = PALETTES[h % len(PALETTES)]
    letters = "".join(w[0] for w in re.findall(r"[A-Za-z0-9]+", name)[:2]).upper() or "?"
    deco = (h >> 8) % 3
    shapes = ["", '<circle cx="210" cy="46" r="90" fill="#fff" opacity=".08"/>',
              '<path d="M0 256 L256 120 V256 Z" fill="#fff" opacity=".08"/>',
              '<rect x="150" y="-40" width="140" height="140" fill="#fff" opacity=".07" transform="rotate(30 220 30)"/>'][deco + 1]
    return f'''<svg xmlns="http://www.w3.org/2000/svg" width="256" height="256" viewBox="0 0 256 256">
<defs><linearGradient id="g" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="{a}"/><stop offset="1" stop-color="{b}"/></linearGradient></defs>
<rect width="256" height="256" fill="url(#g)"/>{shapes}
<text x="128" y="128" text-anchor="middle" dominant-baseline="central" font-family="Helvetica,Arial,sans-serif" font-weight="700" font-size="{120 if len(letters) == 1 else 96}" fill="#fff">{escape(letters)}</text>
</svg>
'''


def _sniff(data):
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return "image/png"
    if data[:3] == b"\xff\xd8\xff":
        return "image/jpeg"
    if data[:6] in (b"GIF87a", b"GIF89a"):
        return "image/gif"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    return None


def normalize(data):
    """Turn uploaded bytes (svg or raster) into a safe 256x256 SVG string."""
    head = data[:2000].lstrip()
    if b"<svg" in data[:4000].lower():
        s = data.decode("utf-8", "replace")
        s = re.sub(r"<\?xml[^>]*\?>", "", s)
        s = re.sub(r"<!DOCTYPE[^>]*>", "", s)
        s = re.sub(r"<script\b.*?</script>", "", s, flags=re.S | re.I)
        s = re.sub(r"\son\w+\s*=\s*(\"[^\"]*\"|'[^']*')", "", s, flags=re.I)
        m = re.search(r"<svg\b([^>]*)>", s, flags=re.I)
        attrs = m.group(1)
        if not re.search(r"viewBox", attrs, re.I):
            w = re.search(r'\swidth="([\d.]+)', attrs)
            hh = re.search(r'\sheight="([\d.]+)', attrs)
            vb = f' viewBox="0 0 {w.group(1) if w else 256} {hh.group(1) if hh else 256}"'
        else:
            vb = ""
        attrs = re.sub(r'\s(width|height)="[^"]*"', "", attrs)
        if "xmlns=" not in attrs:
            attrs += ' xmlns="http://www.w3.org/2000/svg"'
        new = f'<svg{attrs}{vb} width="256" height="256">'
        s = s[:m.start()] + new + s[m.end():]
        s = re.sub(r"\srx=\"[^\"]*\"", lambda x: x.group(0), s)
        return s.strip() + "\n"
    mime = _sniff(data)
    if not mime:
        raise ValueError("icon must be an SVG, PNG, JPEG, GIF or WebP")
    b64 = base64.b64encode(data).decode()
    return (f'<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink" width="256" height="256" viewBox="0 0 256 256">'
            f'<image width="256" height="256" preserveAspectRatio="xMidYMid slice" href="data:{mime};base64,{b64}" xlink:href="data:{mime};base64,{b64}"/></svg>\n')
