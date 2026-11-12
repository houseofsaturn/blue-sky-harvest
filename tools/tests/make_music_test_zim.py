#!/usr/bin/env python3
"""
Build a small test .zim for tools/connections.py, laid out like a Kiwix "maxi"
English Wikipedia (sections in <details>, an infobox, See also, references, a
navbox). Every musician, record and label here is MADE UP: placeholder text for
testing the ranking, not facts.

    python3 make_music_test_zim.py /tmp/music_test.zim
    python3 ../connections.py "Orrin Vale" --zim /tmp/music_test.zim --why

What a correct ranking shows (checked by test_connections.py):
  - Lena Marsh (mentioned often, links back, shares links) is the top musician
  - The Hollow Quartet comes from the infobox and the body
  - Night Choir is a record, Kestrel Disk a label, Free jazz a scene
  - Drum kit (See also only), Rook Abernathy (navbox only), 1964 (a year) never appear
"""
import sys
from libzim.writer import Creator, Item, StringProvider, Hint


def page(title, infobox, sections, extra=""):
    ib = ""
    if infobox:
        rows = "".join(f'<tr><th scope="row" class="infobox-label">{k}</th><td class="infobox-data">{v}</td></tr>'
                       for k, v in infobox)
        ib = (f'<table class="infobox vcard plainlist"><tbody><tr><th colspan="2" class="infobox-above">'
              f'{title}</th></tr>{rows}</tbody></table>')
    lead, *rest = sections
    body = f'<section data-mw-section-id="0">{ib}{lead}</section>'
    for name, html in rest:
        body += (f'<details data-level="2" open=""><summary class="section-heading"><h2 id="{name}">{name}</h2>'
                 f'</summary><div>{html}</div></details>')
    return (f'<!DOCTYPE html><html><head><meta charset="UTF-8"><title>{title}</title></head><body>'
            f'<div id="mw-content-text"><h1 class="section-heading"><span class="mw-headline">{title}</span></h1>'
            f'{body}{extra}</div></body></html>')


NAVBOX = ('<div role="navigation" class="navbox"><table><tr><td><a href="Rook_Abernathy">Rook Abernathy</a> · '
          '<a href="Lena_Marsh">Lena Marsh</a> · <a href="Orrin_Vale">Orrin Vale</a></td></tr></table></div>')
REFS = ('<details data-level="2" open=""><summary class="section-heading"><h2 id="References">References</h2>'
        '</summary><div><div class="mw-references-wrap"><ol class="references"><li>Interview in '
        '<a href="Jazz_Weekly">Jazz Weekly</a>, <a href="1971">1971</a>.</li></ol></div></div></details>')

ARTICLES = {
    "Orrin_Vale": page("Orrin Vale", [
        ("Born", 'Orrin Vale<br>3 May 1938<br><a href="Harrow_Bend">Harrow Bend</a>'),
        ("Genres", '<a href="Free_jazz">Free jazz</a>'),
        ("Instruments", "Drums, percussion"),
        ("Labels", '<a href="Kestrel_Disk">Kestrel Disk</a>'),
        ("Associated acts", '<a href="The_Hollow_Quartet">The Hollow Quartet</a>, <a href="Lena_Marsh">Lena Marsh</a>'),
    ], [
        '<p><b>Orrin Vale</b> (3 May 1938 – 9 June 2019) was an invented <a href="Free_jazz">free jazz</a> drummer '
        'and percussionist from <a href="Harrow_Bend">Harrow Bend</a>.<sup class="reference"><a href="#cite1">[1]</a></sup> '
        'He is best known for his long partnership with the saxophonist <a href="Lena_Marsh">Lena Marsh</a>.</p>',
        ("Career", '<p>In <a href="1964">1964</a> Vale co-founded <a href="The_Hollow_Quartet">The Hollow Quartet</a> '
                   'with <a href="Lena_Marsh">Marsh</a> and the pianist <a href="Tom_Ide">Tom Ide</a>. '
                   'The group recorded for <a href="Kestrel_Disk">Kestrel Disk</a>.</p>'
                   '<p>Vale and Marsh made <i><a href="Night_Choir">Night Choir</a></i> together in 1967. '
                   'Critics later called <a href="Lena_Marsh">Marsh</a> his closest musical ally.</p>'),
        ("Discography", '<ul><li><i><a href="Night_Choir">Night Choir</a></i> (1967, with Lena Marsh)</li>'
                        '<li><i>Stone Hours</i> (1970)</li></ul>'),
        ("See also", '<ul><li><a href="Drum_kit">Drum kit</a></li></ul>'),
    ], extra=REFS + NAVBOX),
    "Lena_Marsh": page("Lena Marsh", [("Instruments", "Alto saxophone"),
                                      ("Associated acts", '<a href="Orrin_Vale">Orrin Vale</a>')], [
        '<p><b>Lena Marsh</b> was an invented <a href="Free_jazz">free jazz</a> saxophonist who played with '
        '<a href="Orrin_Vale">Orrin Vale</a> in <a href="The_Hollow_Quartet">The Hollow Quartet</a>, recording for '
        '<a href="Kestrel_Disk">Kestrel Disk</a>. She grew up in <a href="Harrow_Bend">Harrow Bend</a>.</p>']),
    "Tom_Ide": page("Tom Ide", [("Instruments", "Piano")], [
        '<p><b>Tom Ide</b> was an invented pianist who later taught in <a href="Mill_Town">Mill Town</a>.</p>']),
    "The_Hollow_Quartet": page("The Hollow Quartet", [
        ("Years active", "1964–1972"),
        ("Past members", '<a href="Orrin_Vale">Orrin Vale</a>, <a href="Lena_Marsh">Lena Marsh</a>, <a href="Tom_Ide">Tom Ide</a>'),
    ], ['<p><b>The Hollow Quartet</b> was an invented free jazz group formed by <a href="Orrin_Vale">Orrin Vale</a>.</p>']),
    "Night_Choir": page("Night Choir", [("Released", "1967"), ("Label", '<a href="Kestrel_Disk">Kestrel Disk</a>')], [
        '<p><i><b>Night Choir</b></i> is an invented album by <a href="Lena_Marsh">Lena Marsh</a> and '
        '<a href="Orrin_Vale">Orrin Vale</a>.</p>']),
    "Kestrel_Disk": page("Kestrel Disk", [("Founded", "1963"), ("Distributor(s)", "Self")], [
        '<p><b>Kestrel Disk</b> is an invented record label that issued <a href="Free_jazz">free jazz</a> records '
        'by <a href="The_Hollow_Quartet">The Hollow Quartet</a>.</p>']),
    "Free_jazz": page("Free jazz", [("Stylistic origins", "Jazz"), ("Cultural origins", "1950s–1960s")], [
        '<p><b>Free jazz</b> is a style of jazz. Here it is test text for <a href="Orrin_Vale">Orrin Vale</a>.</p>']),
    "Harrow_Bend": page("Harrow Bend", [("Country", "Nowhere")], [
        '<p><b>Harrow Bend</b> is an invented town on a river.</p>']),
    "Mill_Town": page("Mill Town", [], ['<p><b>Mill Town</b> is an invented town.</p>']),
    "Drum_kit": page("Drum kit", [], ['<p>A <b>drum kit</b> is a collection of drums.</p>']),
    "Rook_Abernathy": page("Rook Abernathy", [("Instruments", "Drums")], [
        '<p><b>Rook Abernathy</b> was an invented drummer.</p>']),
    "Jazz_Weekly": page("Jazz Weekly", [], ['<p><b>Jazz Weekly</b> is an invented magazine.</p>']),
    "1964": page("1964", [], ['<p><b>1964</b> was a year.</p>']),
}
REDIRECTS = {"Orrin_Vale_(drummer)": "Orrin_Vale"}


class Page(Item):
    def __init__(self, path, html):
        super().__init__()
        self.p, self.h = path, html

    def get_path(self): return self.p
    def get_title(self): return self.p.replace("_", " ")
    def get_mimetype(self): return "text/html"
    def get_contentprovider(self): return StringProvider(self.h)
    def get_hints(self): return {Hint.FRONT_ARTICLE: True}


def main(out):
    with Creator(out).config_indexing(True, "eng") as c:
        c.set_mainpath("Orrin_Vale")
        for k, v in {"Title": "Music test (made up)", "Language": "eng", "Creator": "Blue Sky Harvest",
                     "Publisher": "test", "Name": "music_test", "Description": "Invented test articles",
                     "Date": "2026-11-12"}.items():
            c.add_metadata(k, v)
        for p, h in ARTICLES.items():
            c.add_item(Page(p, h))
        for src, dst in REDIRECTS.items():
            c.add_redirection(src, src.replace("_", " "), dst, {Hint.FRONT_ARTICLE: False})
    print("wrote", out)


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "/tmp/music_test.zim")
