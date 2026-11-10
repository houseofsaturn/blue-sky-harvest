#!/usr/bin/env python3
"""
mobi2epub: turn an old Kindle MOBI (MOBI7) into a clean EPUB for KOReader,
with a working, nested table of contents.

    python3 mobi2epub.py book.mobi out.epub [--parts parts.json]

The chapter list comes from the MOBI's own (unreadable-by-KOReader) NCX, or
failing that from its contents page. --parts groups chapters under part
headings: {"Fictions": ["First story", ...], ...}.
Needs: pip install mobi ebooklib lxml
"""
import json
import re
import sys
from pathlib import Path

import mobi
from ebooklib import epub
from lxml import etree
from lxml import html as LH

CSS = """
body { margin: 0 2%; }
p { margin: 0; text-indent: 1.2em; text-align: justify; }
p.c, p.r { text-indent: 0; }
p.c { text-align: center; }
p.r { text-align: right; }
p.gap { margin-top: 0.8em; }
h1, h2, h3 { text-align: center; text-indent: 0; font-weight: bold; margin: 1.5em 0 1em; }
h1 { font-size: 1.6em; }
h2 { font-size: 1.35em; }
h3 { font-size: 1.15em; }
blockquote { margin: 0.6em 1.5em; }
sup { font-size: 0.7em; line-height: 0; }
a { text-decoration: none; }
"""


def clean(el):
    """MOBI7 markup -> tidy XHTML, in place"""
    for pb in el.iter("mbp:pagebreak"):
        pb.tag = "REMOVE"
    for p in el.iter("p"):
        size = None
        fonts = [f for f in p.iter("font") if f.get("size")]
        text = "".join(p.itertext()).strip()
        if fonts and text and all(f.get("size") in ("6", "7") for f in fonts) \
                and len("".join("".join(f.itertext()) for f in fonts).strip()) >= len(text) - 1:
            size = max(f.get("size") for f in fonts)
        align = (p.get("align") or "").lower()
        gap = p.get("height") not in (None, "0pt")
        for a in ("height", "width", "align"):
            p.attrib.pop(a, None)
        if size and len(text) < 120:
            p.tag = "h2" if size == "7" else "h3"
            etree.strip_tags(p, "b")
        else:
            cls = {"center": "c", "right": "r"}.get(align, "")
            if gap:
                cls = (cls + " gap").strip()
            if cls:
                p.set("class", cls)
    for img in el.iter("img"):
        for a in ("align", "height", "width"):
            img.attrib.pop(a, None)
        img.set("style", "height:1em;width:auto")
        img.set("alt", img.get("alt", ""))
    for a in el.iter("a"):
        etree.strip_tags(a, "u")
    for x in el.iter():
        if x.tag not in ("img",) and isinstance(x.tag, str):
            for at in ("height", "width", "align", "color", "size"):
                x.attrib.pop(at, None)
    etree.strip_tags(el, "font", "REMOVE")


def main():
    src, out = Path(sys.argv[1]), Path(sys.argv[2])
    parts = {}
    if "--parts" in sys.argv:
        parts = json.loads(Path(sys.argv[sys.argv.index("--parts") + 1]).read_text())
    tmp, path = mobi.extract(str(src))
    base = Path(path).parent
    raw = Path(path).read_text(encoding="utf-8", errors="replace")
    opf = (base / "content.opf").read_text(encoding="utf-8", errors="replace")
    ncx = (base / "toc.ncx").read_text(encoding="utf-8", errors="replace") if (base / "toc.ncx").exists() else ""

    meta = lambda tag: (re.search(rf"<dc:{tag}[^>]*>(.*?)</dc:{tag}>", opf, re.S) or [None, ""])[1].strip()
    title, author, lang = meta("title") or src.stem, meta("creator"), meta("language") or "en"

    # chapter starts: NCX targets, labelled by the contents page where it has nicer names
    targets = re.findall(r"<text>(.*?)</text>\s*</navLabel>\s*<content src=\"[^#\"]*#(filepos\d+)\"", ncx, re.S)
    contents = {}
    for pos, lab in re.findall(r'<a href="#(filepos\d+)">(.*?)</a>', raw):
        lab = re.sub(r"<[^>]+>", "", lab).strip()
        contents.setdefault(pos, lab)
    doc = LH.document_fromstring(raw)
    body = doc.body
    top_ids = [c.get("id") for c in body if c.tag == "a" and c.get("id")]
    starts = [(t, contents.get(t, lab).strip()) for lab, t in targets if t in top_ids]
    if not starts:
        sys.exit("no chapter list found in this MOBI")
    # a contents-page link often points just past the NCX anchor (at the title); use the
    # nicer contents-page label for the nearest following link
    names = dict(starts)
    for t, lab in starts:
        n = int(t[7:])
        near = [p for p in contents if 0 < int(p[7:]) - n < 200]
        if near:
            names[t] = contents[min(near, key=lambda p: int(p[7:]))]

    clean(body)
    chapters = [("front", "Title page", [])]
    start_ids = dict(starts)
    for child in list(body):
        if child.tag == "a" and child.get("id") in start_ids:
            chapters.append((child.get("id"), names[child.get("id")], []))
        chapters[-1][2].append(child)

    book = epub.EpubBook()
    book.set_identifier("mobi2epub-" + re.sub(r"\W+", "-", title.lower()))
    book.set_title(title)
    book.set_language(lang)
    if author:
        book.add_author(author)
    css = epub.EpubItem(uid="css", file_name="style.css", media_type="text/css", content=CSS)
    book.add_item(css)

    # images
    for img in (base / "Images").glob("*") if (base / "Images").exists() else []:
        mt = {"jpeg": "image/jpeg", "jpg": "image/jpeg", "gif": "image/gif", "png": "image/png"}.get(img.suffix[1:].lower())
        if not mt:
            continue
        if img.name.startswith("cover"):
            book.set_cover("Images/" + img.name, img.read_bytes())
        else:
            book.add_item(epub.EpubItem(file_name="Images/" + img.name, media_type=mt, content=img.read_bytes()))

    # where every id lives, for rewriting internal links
    home = {}
    for i, (_, _, els) in enumerate(chapters):
        for e in els:
            for x in e.iter():
                if x.get("id"):
                    home[x.get("id")] = f"c{i:02d}.xhtml"
    items = []
    for i, (cid, label, els) in enumerate(chapters):
        parts_html = []
        for e in els:
            for a in e.iter("a"):
                h = a.get("href") or ""
                if h.startswith("#") and h[1:] in home:
                    a.set("href", f"{home[h[1:]]}{h}")
            if e.tag == "a" and not len(e) and not (e.text or "").strip():
                parts_html.append(f'<div id="{e.get("id")}"></div>')
                continue
            if e.tag == "br":
                continue
            parts_html.append(etree.tostring(e, method="xml", encoding="unicode", with_tail=False))
        c = epub.EpubHtml(title=label, file_name=f"c{i:02d}.xhtml", lang=lang)
        c.content = "<html><head></head><body>" + "\n".join(parts_html) + "</body></html>"
        c.add_item(css)
        book.add_item(c)
        items.append((cid, label, c))

    # table of contents, grouped into parts if asked
    toc = []
    part_of = {name: p for p, names_ in parts.items() for name in names_}
    open_part = None
    for cid, lab, c in items[1:]:
        link = epub.Link(c.file_name, lab, cid)
        p = part_of.get(lab)
        if p:
            if open_part is None or open_part[0].title != p:
                open_part = (epub.Section(p, c.file_name), [])
                toc.append(open_part)
            open_part[1].append(link)
        else:
            open_part = None
            toc.append(link)
    book.toc = toc
    book.spine = [c for _, _, c in items]
    book.add_item(epub.EpubNcx())
    book.add_item(epub.EpubNav())
    epub.write_epub(str(out), book)
    print(f"{out.name}: {len(items) - 1} chapters, {len(parts)} parts")


if __name__ == "__main__":
    main()
