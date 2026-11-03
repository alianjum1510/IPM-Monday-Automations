"""Build the Comment Builder page into ../static/ (served by router.py).

Usage (from the repository root):  python3 -I app/features/comment_builder/page/build.py

The page is the original v2 bundle (base/, from monday - never edit it) with two of its functions swapped for
this folder's code:

  comment-logic.js  replaces the bundle's data layer (Tn/En/Dn/On: load deal, preview, save, history)
  updates-feed.js   the deal's monday Updates (write, mention, emoji, like, reply, edit, delete, attach files)
  ui.js             replaces the bundle's main screen (Pn): header → Updates → comment form → comment history
  updates.css       extra styles for that screen (the original stylesheet is copied unchanged)

Moved from the old Comment Builder project (v4/ + comment-builder-server-app/build_client.py), with
v4-fixes.diff applied. Edit the sources here, then run this; never edit static/ by hand.
"""
import hashlib
import pathlib
import shutil

HERE = pathlib.Path(__file__).resolve().parent
BASE = HERE / "base"
STATIC = HERE.parent / "static"
V2_JS = "index-DrcEGg81.js"

src = (BASE / "assets" / V2_JS).read_text(encoding="utf-8")
logic = (HERE / "comment-logic.js").read_text(encoding="utf-8")
feed = (HERE / "updates-feed.js").read_text(encoding="utf-8")
ui = (HERE / "ui.js").read_text(encoding="utf-8")
css = (HERE / "updates.css").read_text(encoding="utf-8")


def swap(text, start_marker, end_marker, new):
    """Replace text[start_marker : end_marker) with new; both markers must be unique."""
    for marker in (start_marker, end_marker):
        if text.count(marker) != 1:
            raise SystemExit(f"Marker {marker[:40]!r} not unique; is this the v2 bundle?")
    start, end = text.index(start_marker), text.index(end_marker)
    return text[:start] + "\n" + new + "\n" + text[end:]


src = swap(src, "async function Tn(e){", "var kn=0", logic)
src = swap(src, "function Pn(){", "Ut(document.getElementById(`root`))", feed + "\n" + ui)


# Content-hashed names: monday never serves a cached file after a change.
def hashed(stem, ext, content):
    return f"{stem}-{hashlib.sha256(content.encode('utf-8')).hexdigest()[:8]}.{ext}"


out_js = hashed("index", "js", src)
out_css = hashed("updates", "css", css)

if STATIC.exists():
    shutil.rmtree(STATIC)
(STATIC / "assets").mkdir(parents=True)
(STATIC / "assets" / out_js).write_text(src, encoding="utf-8")
(STATIC / "assets" / out_css).write_text(css, encoding="utf-8")
for orig_css in (BASE / "assets").glob("*.css"):
    shutil.copy2(orig_css, STATIC / "assets" / orig_css.name)

html = (BASE / "index.html").read_text(encoding="utf-8")
if html.count(f"./assets/{V2_JS}") != 1 or html.count("</head>") != 1:
    raise SystemExit("Unexpected index.html; is this the v2 build?")
html = html.replace(f"./assets/{V2_JS}", f"./assets/{out_js}")
html = html.replace("<title>Deal Comment Logger</title>", "<title>Comment Builder</title>")
html = html.replace("</head>", f'  <link rel="stylesheet" href="./assets/{out_css}">\n  </head>')
html = html.replace('"./assets/', '"/assets/')  # absolute: works whatever path monday opens the page on
(STATIC / "index.html").write_text(html, encoding="utf-8")
print("Built page into", STATIC, "->", out_js, out_css)
