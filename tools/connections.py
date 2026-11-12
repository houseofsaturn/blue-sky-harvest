#!/usr/bin/env python3
"""
connections: who and what an artist is connected to, from offline Wikipedia.

The prototype for gleaner's music conversations in #listenings (no AI). Give it a
name; it reads that article in the Wikipedia .zim, follows every link, ranks
them, and prints the strongest connections grouped by kind (musicians and groups,
records, labels, scenes and styles), each with the Wikipedia sentence that makes
the connection.

    python3 connections.py "Milford Graves"
    python3 connections.py "Milford Graves" --top 15      # more per group
    python3 connections.py "Milford Graves" --all         # also people, places, other
    python3 connections.py "Milford Graves" --why         # show how each score was made
    python3 connections.py "Milford Graves" --zim /path/to/wikipedia.zim

Finds the archive itself: the biggest wikipedia*.zim in ~/zim (or the folder in
WIKISTACK_ZIM_DIR), unless --zim is given.

How a link is ranked (all from the two articles, nothing guessed):
  mentioned   how many sentences of the artist's article mention it (up to 3)
  lead        it's mentioned in the opening section
  infobox     it's listed in the infobox (e.g. "Associated acts", "Labels")
  links back  its own article links back to the artist
  shared      how much the two articles link to the same things
Links only in "See also", references, navigation boxes and so on are ignored.
The link-back and shared-link ideas come from WIKISTACK's LinkJudge; the skip
lists and link handling from its article parser.

Needs: python3, libzim, lxml (exlo: sudo apt install python3-libzim python3-lxml;
elsewhere: pip install libzim lxml). Text from Wikipedia, CC BY-SA 4.0.
"""
from __future__ import annotations

import argparse
import math
import os
import posixpath
import re
import sys
import time
from urllib.parse import unquote

try:
    from libzim.reader import Archive
    from libzim.suggestion import SuggestionSearcher
except ImportError:
    sys.exit("connections: needs libzim.  exlo: sudo apt install python3-libzim   other: pip install libzim")
try:
    import lxml.html
except ImportError:
    sys.exit("connections: needs lxml.  exlo: sudo apt install python3-lxml   other: pip install lxml")

VERSION = "0.1"

# ---------------------------------------------------------------- what to skip (from WIKISTACK's parser)
SKIP_CLASS = {"mw-editsection", "navbox", "navbox-styles", "metadata", "noprint", "sidebar", "ambox", "hatnote",
              "shortdescription", "mw-empty-elt", "mbox-small", "portalbox", "portal", "sistersitebox",
              "sister-box", "side-box", "vertical-navbox", "toc", "mw-cite-backlink", "printfooter", "catlinks",
              "navbar", "mw-jump-link", "magnify", "mbox", "ombox", "tmbox", "cmbox", "fmbox", "dmbox", "asbox",
              "stub", "authority-control", "navigation-not-searchable", "mw-authority-control", "dablink",
              "rellink", "reference", "mw-ref", "references", "reflist", "mw-references-wrap", "IPA",
              "rt-commentedText", "geo-nondefault", "geo-multi-punct", "mw-kartographer-container"}
SKIP_TAGS = {"style", "script", "sup", "math", "svg", "figure", "audio", "video"}
# sections whose links are not connections
SKIP_SECTIONS = {"references", "notes", "citations", "footnotes", "sources", "works cited", "explanatory notes",
                 "notes and references", "references and notes", "general references", "cited sources",
                 "endnotes", "bibliography", "see also", "external links", "further reading", "further listening",
                 "sources and further reading", "links"}
NOT_ARTICLE = re.compile(r"^(?:Category|User|User_talk|Talk|Wikipedia|Template|Portal|Help|File|Draft|Module|"
                         r"MediaWiki|Special|TimedText|Book|Index|Media|Image|WP)[:_]", re.I)
DATEISH = re.compile(r"^(?:\d{1,4}(?:s|_BC|_AD)?|(?:January|February|March|April|May|June|July|August|September|"
                     r"October|November|December)(?:_\d{1,2})?|\d{1,2}(?:st|nd|rd|th)_century)$", re.I)
REFMARK = re.compile(r"\[(?:\d+|[a-z]|note \d+|citation needed)\]")
HREF = re.compile(rb'<a\s[^>]*?href="([^"#?]+)', re.I)
WS = re.compile(r"\s+")
# a sentence ends at . ! ? followed by space and a capital/quote/digit; not after common abbreviations
SENT_END = re.compile(r'(?<=[.!?])\s+(?=["“(\[A-Z0-9])')
ABBREV = re.compile(r"(?:\b(?:Jr|Sr|Dr|Mr|Ms|Mrs|St|No|Vol|vs|ca|c|Mt|Ft|Bros|Co|Inc|Ltd|feat)|\b[A-Z])\.$")


def split_sentences(text: str) -> list:
    out = []
    for piece in SENT_END.split(text):
        piece = piece.strip()
        if not piece:
            continue
        if out and ABBREV.search(out[-1]):
            out[-1] += " " + piece
        else:
            out.append(piece)
    return out

# ---------------------------------------------------------------- kinds, from a target's infobox and first sentence
MUSIC_WORDS = re.compile(
    r"\b(musician|drummer|percussionist|saxophonist|pianist|bassist|double[- ]bassist|trumpeter|trombonist|"
    r"guitarist|singer|vocalist|composer|bandleader|clarinetist|clarinettist|flautist|flutist|violinist|cellist|"
    r"organist|keyboardist|multi-instrumentalist|rapper|DJ|record producer|songwriter|improviser|band|ensemble|"
    r"quartet|quintet|trio|sextet|septet|octet|orchestra|duo|group|collective)\b", re.I)
RECORD_WORDS = re.compile(r"\b(album|EP|single|song|recording|live album|compilation|soundtrack|composition)\b", re.I)
LABEL_WORDS = re.compile(r"\brecord label\b|\b(label|record company|imprint)\b", re.I)
SCENE_WORDS = re.compile(r"\b(genre|style of (?:music|jazz)|music(?:al)? (?:movement|scene|style)|subgenre|"
                         r"movement|scene|tradition|school of)\b", re.I)
# a place: "X is a city in …", "X was a jazz club on …"
PLACE_WORDS = re.compile(r"\b(?:a|an|the)\s+(?:[\w-]+\s+){0,3}(city|town|borough|neighbou?rhood|village|county|"
                         r"province|capital|district|island|suburb|venue|club|nightclub|concert hall|ballroom|"
                         r"theatre|theater|studio)\s+(?:in|on|of|at|located)\b", re.I)
MUSIC_CONTEXT = re.compile(r"\b(music|musical|jazz|rock|punk|folk|blues|soul|funk|gospel|hip[- ]hop|rap|reggae|"
                           r"dub|electronic|techno|house|ambient|classical|avant-garde|improvis\w*|experimental|"
                           r"noise|drone|psychedelic|disco|metal|pop|song|band)\b", re.I)

KIND_ORDER = [("musician", "Musicians and groups"), ("record", "Records"), ("label", "Labels"),
              ("scene", "Scenes and styles"), ("person", "Other people"), ("place", "Places"), ("other", "Other")]
MAIN_KINDS = {"musician", "record", "label", "scene"}


def norm(s: str) -> str:
    return WS.sub(" ", s or "").strip()


def classes(el) -> set:
    return set((el.get("class") or "").split())


def find_zim(arg: str | None) -> str:
    if arg:
        if not os.path.exists(arg):
            sys.exit(f"connections: no such file: {arg}")
        return arg
    d = os.environ.get("WIKISTACK_ZIM_DIR", os.path.join(os.path.expanduser("~"), "zim"))
    try:
        zims = [os.path.join(d, f) for f in os.listdir(d) if f.lower().endswith(".zim")]
    except FileNotFoundError:
        zims = []
    wiki = [z for z in zims if "wikipedia" in os.path.basename(z).lower()] or zims
    if not wiki:
        sys.exit(f"connections: no .zim found in {d}. Use --zim /path/to/wikipedia.zim")
    return max(wiki, key=os.path.getsize)


# ================================================================ the archive
class Wiki:
    def __init__(self, path: str):
        self.zim = Archive(path)
        self.path = path

    def entry(self, path: str):
        """entry for a path (redirects followed), or None"""
        e = None
        for p in (path, path.replace(" ", "_")):
            try:
                e = self.zim.get_entry_by_path(p)
                break
            except Exception:
                pass
        if e is None:
            try:
                e = self.zim.get_entry_by_title(path.replace("_", " "))
            except Exception:
                return None
        for _ in range(8):
            if not e.is_redirect:
                try:
                    return e if e.get_item().mimetype.startswith("text/html") else None
                except Exception:
                    return None
            e = e.get_redirect_entry()
        return None

    def find(self, name: str):
        """the article for a name: exact path/title first, then the top title suggestion"""
        e = self.entry(name.strip())
        if e is None:
            for p in suggest(self.zim, name, 5):
                e = self.entry(p)
                if e is not None:
                    break
        return e

    def suggestions(self, name: str, n: int = 8) -> list:
        return [p.replace("_", " ") for p in suggest(self.zim, name, n)]

    @staticmethod
    def html(e) -> bytes:
        return bytes(e.get_item().content)


def suggest(zim, q: str, n: int) -> list:
    """title suggestions; libzim renamed getResults to get_results, so try both"""
    try:
        s = SuggestionSearcher(zim).suggest(q)
        get = getattr(s, "get_results", None) or getattr(s, "getResults")
        return list(get(0, n))
    except Exception:
        return []


def resolve(base_dir: str, href: str) -> str | None:
    """a relative article link -> archive path (as WIKISTACK's Parser.resolve)"""
    h = unquote((href or "").strip())
    if not h or h.startswith(("#", "//", "javascript:", "data:")) or re.match(r"^[a-z]+:", h, re.I) and not h.startswith("./"):
        return None
    p = h.split("#")[0].split("?")[0]
    if not p:
        return None
    p = posixpath.normpath(posixpath.join(base_dir, p))
    while p.startswith("./"):
        p = p[2:]
    if p in (".", "") or p.startswith("../"):
        return None
    return p


def raw_links(raw: bytes, base_dir: str) -> set:
    """every article path an article links to (fast; regex over the raw HTML, as LinkJudge does)"""
    out = set()
    for m in HREF.finditer(raw):
        p = resolve(base_dir, m.group(1).decode("utf-8", "replace"))
        if p:
            out.add(p)
    return out


# ================================================================ reading one article
class Article:
    """the parts of an article that matter for connections"""

    def __init__(self, wiki: Wiki, entry, full: bool = True):
        """full=False (linked articles): only the links, infobox and first sentence, which is much faster"""
        self.path = entry.path
        self.title = entry.title or entry.path.replace("_", " ")
        self.base = posixpath.dirname(entry.path)
        raw = Wiki.html(entry)
        self.all_links = raw_links(raw, self.base)
        root = lxml.html.fromstring(raw)
        try:
            content = root.get_element_by_id("mw-content-text")
        except Exception:
            content = root.find("body") if root.find("body") is not None else root
        self.infobox_rows = []          # (label, text, [link paths])
        self.infobox_classes = set()
        for tbl in list(content.iter("table")):
            if "infobox" in classes(tbl):
                self.infobox_classes |= classes(tbl)
                self._infobox(tbl)
                tbl.drop_tree()
                break
        self.first_sentence = ""
        self.mentions = {}              # path -> [(section, sentence, in_lead)]
        self.sentences = 0
        if not full:
            for p in content.iter("p"):
                t = REFMARK.sub("", norm(p.text_content()))
                if len(t) > 40:
                    self.first_sentence = (split_sentences(t) or [t])[0]
                    break
            return
        for el in list(content.iter()):
            if not isinstance(el.tag, str):
                continue
            if el.tag in SKIP_TAGS or classes(el) & SKIP_CLASS or el.get("role") == "navigation" \
                    or "display:none" in (el.get("style") or "").replace(" ", ""):
                if el.getparent() is not None:
                    el.drop_tree()
        self._body(content)

    def _infobox(self, tbl):
        for tr in tbl.iter("tr"):
            cells = [c for c in tr if isinstance(c.tag, str) and c.tag in ("th", "td")]
            if len(cells) < 2:
                continue
            label = norm(cells[0].text_content())
            val = cells[1]
            for br in val.iter("br"):
                br.tail = " · " + (br.tail or "")
            links = [p for a in val.iter("a") if (p := resolve(self.base, a.get("href")))]
            text = norm(val.text_content())
            if label:
                self.infobox_rows.append((label, text, links))

    def _body(self, content):
        section, lead = "", True
        for el in content.iter():
            if not isinstance(el.tag, str):
                continue
            if el.tag in ("h2", "h3", "h4"):
                t = norm(el.text_content()).lower()
                if el.tag == "h2":
                    section = t
                    lead = False
                elif section not in SKIP_SECTIONS:
                    section = section or t
                continue
            if el.tag not in ("p", "li", "dd", "td") or section in SKIP_SECTIONS:
                continue
            # only the innermost text blocks: skip a block that contains another block
            if any(isinstance(c.tag, str) and c.tag in ("p", "li", "dd", "td", "table", "ul", "ol") for c in el.iterdescendants()):
                # still take a list item's own sentence before its nested list
                if el.tag != "li":
                    continue
            text = norm(el.text_content())
            if len(text) < 3:
                continue
            sents = split_sentences(text)
            if not self.first_sentence and el.tag == "p" and len(text) > 40:
                self.first_sentence = sents[0] if sents else text
            self.sentences += len(sents)
            for a in el.iter("a"):
                p = resolve(self.base, a.get("href"))
                if not p:
                    continue
                anchor = norm(a.text_content())
                sent = next((s for s in sents if anchor and anchor in s), sents[0] if sents else text)
                lst = self.mentions.setdefault(p, [])
                if all(sent != x[1] for x in lst):
                    lst.append((section or "(opening)", sent, lead))

    def kind(self) -> str:
        """musician / record / label / scene / person / place / other, from the infobox and first sentence"""
        labels = {l.lower().rstrip(" :") for l, _, _ in self.infobox_rows}
        ic = " ".join(self.infobox_classes).lower()
        first = self.first_sentence[:300]
        # what it "is", from the first sentence: "X is/was an American jazz drummer ..."
        m = re.search(r"\b(?:is|was|are|were)\b(.{0,160})", first)
        what = m.group(1) if m else first
        if labels & {"released", "recorded", "studio", "length", "producer", "venue"} or ("album" in ic):
            return "record"
        if labels & {"instruments", "instrument(s)", "instrument", "associated acts", "past members",
                     "spinoff of", "spinoffs"} or "musical-artist" in ic \
                or ({"genres", "genre"} & labels and {"labels", "label"} & labels):
            return "musician"
        if labels & {"distributor(s)", "distributor"} or LABEL_WORDS.search(what) and "label" in what.lower():
            return "label"
        if labels & {"stylistic origins", "cultural origins", "typical instruments", "derivative forms",
                     "subgenres", "fusion genres"}:
            return "scene"
        if MUSIC_WORDS.search(what):
            return "musician"
        if RECORD_WORDS.search(what) and re.search(r"\bby\b", what):
            return "record"
        if SCENE_WORDS.search(what) and MUSIC_CONTEXT.search(what):
            return "scene"
        if labels & {"born", "died", "occupation", "occupation(s)", "nationality"}:
            return "person"
        if PLACE_WORDS.search(first) or labels & {"population", "coordinates", "elevation", "area", "postcode",
                                                  "zip code", "zip codes", "time zone", "borough", "capacity"}:
            return "place"
        return "other"


# ================================================================ ranking
def connections(wiki: Wiki, seed: Article, progress=True):
    infobox_links = {}
    for label, _, links in seed.infobox_rows:
        for p in links:
            infobox_links.setdefault(p, label)
    candidates = set(seed.mentions) | set(infobox_links)
    seed_links = seed.all_links
    out = {}
    t0 = time.time()
    for i, path in enumerate(sorted(candidates)):
        if progress and i % 25 == 0:
            print(f"\r   reading linked articles… {i}/{len(candidates)}", end="", file=sys.stderr, flush=True)
        name = posixpath.basename(path)
        if NOT_ARTICLE.match(name) or DATEISH.match(name):
            continue
        e = wiki.entry(path)
        if e is None or e.path == seed.path:
            continue
        if e.path in out:                       # two links (e.g. a redirect) to the same article: merge
            r = out[e.path]
            r["mentions"] += [m for m in seed.mentions.get(path, []) if m not in r["mentions"]]
            r["infobox"] = r["infobox"] or infobox_links.get(path)
            continue
        try:
            target = Article(wiki, e, full=False)
        except Exception:
            continue
        out[e.path] = {"path": e.path, "title": target.title, "kind": target.kind(),
                       "first": target.first_sentence, "mentions": list(seed.mentions.get(path, [])),
                       "infobox": infobox_links.get(path),
                       "back": seed.path in target.all_links or any(
                           posixpath.basename(l) == posixpath.basename(seed.path) for l in target.all_links),
                       "shared": cosine(seed_links, target.all_links)}
    if progress:
        print(f"\r   read {len(candidates)} linked articles in {time.time() - t0:.1f}s" + " " * 10, file=sys.stderr)
    for r in out.values():
        n = len(r["mentions"])
        parts = {
            "mentioned": 0.30 * min(n, 3) / 3,
            "lead": 0.15 * (1 if any(m[2] for m in r["mentions"]) else 0),
            "infobox": 0.10 * (1 if r["infobox"] else 0),
            "links back": 0.25 * (1 if r["back"] else 0),
            "shared": 0.20 * min(1.0, r["shared"] / 0.25),      # cosine 0.25+ counts as fully shared
        }
        r["parts"] = parts
        r["score"] = round(sum(parts.values()), 3)
    return sorted(out.values(), key=lambda r: -r["score"])


def cosine(a: set, b: set) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / math.sqrt(len(a) * len(b))


def reason(r: dict, width: int = 220) -> str:
    if r["mentions"]:
        # prefer a body sentence over a list item, and the longest-but-not-huge one
        sec, sent, _ = sorted(r["mentions"], key=lambda m: (not m[2], m[0] in ("discography", "selected discography"),
                                                              -min(len(m[1]), 300)))[0]
        s = sent if len(sent) <= width else sent[:width].rsplit(" ", 1)[0] + "…"
        return f"“{s}”" + (f"  [{sec}]" if sec and sec != "(opening)" else "")
    if r["infobox"]:
        return f"listed in the infobox under “{r['infobox']}”"
    return ""


# ================================================================ output
def main():
    ap = argparse.ArgumentParser(description="Connections from offline Wikipedia (gleaner prototype).")
    ap.add_argument("name", help='an artist, record, label or scene, e.g. "Milford Graves"')
    ap.add_argument("--zim", help="the Wikipedia .zim (default: biggest wikipedia*.zim in ~/zim)")
    ap.add_argument("--top", type=int, default=8, help="how many per group (default 8)")
    ap.add_argument("--all", action="store_true", help="also show other people, places and other links")
    ap.add_argument("--why", action="store_true", help="show how each score was made")
    a = ap.parse_args()

    wiki = Wiki(find_zim(a.zim))
    print(f"connections {VERSION} · {os.path.basename(wiki.path)}", file=sys.stderr)
    e = wiki.find(a.name)
    if e is None:
        alts = wiki.suggestions(a.name)
        sys.exit(f"No article for “{a.name}”." + (" Did you mean: " + "; ".join(alts) if alts else ""))
    seed = Article(wiki, e)
    if re.search(r"\b(?:may|might|can|could) (?:also )?(?:refer|be used to refer) to\b", seed.first_sentence):
        opts = [posixpath.basename(p).replace("_", " ") for p in list(seed.mentions)[:12]]
        sys.exit(f"“{seed.title}” is a disambiguation page. Try one of: " + "; ".join(opts))

    print(f"\n{seed.title}  ({seed.kind()})")
    if seed.first_sentence:
        print("  " + (seed.first_sentence[:300] + ("…" if len(seed.first_sentence) > 300 else "")))
    wanted = ("genre", "genres", "instrument", "instruments", "instrument(s)", "labels", "label", "years active",
              "associated acts", "members", "past members", "origin", "born", "released", "recorded")
    facts = [(l, t) for l, t, _ in seed.infobox_rows if l.lower().rstrip(":") in wanted and t]
    if facts:
        print()
        for l, t in facts:
            print(f"  {l}: {t[:200]}")
    print()

    ranked = connections(wiki, seed)
    shown = 0
    for kind, heading in KIND_ORDER:
        if kind not in MAIN_KINDS and not a.all:
            continue
        rows = [r for r in ranked if r["kind"] == kind
                and (r["score"] > 0.12 or (kind in MAIN_KINDS and r["mentions"]))][:a.top]
        if not rows:
            continue
        print(f"\n{heading}")
        print("-" * len(heading))
        for r in rows:
            shown += 1
            print(f"{r['score']:.2f}  {r['title']}")
            why = reason(r)
            if why:
                print(f"      {why}")
            if a.why:
                p = r["parts"]
                print("      " + " · ".join(f"{k} {v:.2f}" for k, v in p.items() if v)
                      + f"   (mentions {len(r['mentions'])}, shared {r['shared']:.2f}, back {'yes' if r['back'] else 'no'})")
    if not shown:
        print("No strong connections found." + ("" if a.all else " Try --all."))
    hidden = sum(1 for r in ranked if r["kind"] not in MAIN_KINDS)
    if not a.all and hidden:
        print(f"\n({hidden} other links to people, places and other things: add --all to see them)")


if __name__ == "__main__":
    main()
