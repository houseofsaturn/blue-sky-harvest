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
    python3 connections.py "Milford Graves" --no-musicdb  # Wikipedia only
    python3 connections.py "RVNG Intl."                   # a label: its artists, each with their records on it

What you type decides what you get: the page's own infobox and first sentence say whether it is an
artist, a record, a label or a scene, and the answer is shaped to match (a label gets a roster of artists
with their records; an artist gets the people and records around them). A name that could be several things
("Nirvana") is not guessed: if one reading clearly dominates it is used and the others are named; otherwise
the options are listed and you pick one by its full title, e.g. "Nirvana (band)".

If music.db (tools/musicdb, built from MusicBrainz) is found, it adds the hard evidence: albums
and tracks played on together, bands, teachers. Musicians who played with the artist but aren't
linked from the article are added too, also those without a Wikipedia article ("not on Wikipedia").
music.db is looked for in MUSICDB, ~/musicdb/music.db, then next to this script (--musicdb PATH).

Finds the archive itself: the biggest wikipedia*.zim in ~/zim (or the folder in
WIKISTACK_ZIM_DIR), unless --zim is given.

How a link is ranked (all from the two articles, nothing guessed):
  mentioned   how many sentences of the artist's article mention it (up to 3)
  lead        it's mentioned in the opening section
  infobox     it's listed in the infobox (e.g. "Associated acts", "Labels")
  links back  its own article links back to the artist
  shared      how much the two articles link to the same things
  played      (music.db) albums together (up to 3), or tracks if no album; bands, teachers, collaborations
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
import sqlite3
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

VERSION = "0.5"

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
SENT_END = re.compile(r'(?:(?<=[.!?])|(?<=[.!?][)"”’\]]))\s+(?=["“(\[A-Z0-9])')
ABBREV = re.compile(r"(?:\b(?:Jr|Sr|Dr|Mr|Ms|Mrs|St|No|Vol|vs|ca|c|Mt|Ft|Bros|Co|Inc|Ltd|feat|rel|approx|ed|eds|trans|pp|p|vol|op|nos?)|\b[A-Z])\.$")


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
# "X is a(n) [American independent] record label …": the label word must be the thing X *is*,
# not a word later in the sentence (a photographer "known for his Sub Pop label work" is no label)
LABEL_HEAD = re.compile(r"^\s*(?:an?|the)\s+(?:(?!(?:known|for|of|who|that|which|with|by|in|at|from|on|as|and|or)\b)"
                        r"[\w'’.&-]+\s+){0,6}?(?:record label|label|record company|recording company|imprint|"
                        r"record imprint|sublabel)\b", re.I)
SCENE_WORDS = re.compile(r"\b(genre|style of (?:music|jazz)|music(?:al)? (?:movement|scene|style)|subgenre|"
                         r"movement|scene|tradition|school of)\b", re.I)
# a place: "X is a city in …", "X was a jazz club on …"
PLACE_WORDS = re.compile(r"\b(?:a|an|the)\s+(?:[\w-]+\s+){0,3}(city|town|borough|neighbou?rhood|village|county|"
                         r"province|capital|district|island|suburb|venue|club|nightclub|concert hall|ballroom|"
                         r"theatre|theater|studio)\s+(?:in|on|of|at|located)\b", re.I)
MUSIC_CONTEXT = re.compile(r"\b(music|musical|jazz|rock|punk|folk|blues|soul|funk|gospel|hip[- ]hop|rap|reggae|"
                           r"dub|electronic|techno|house|ambient|classical|avant-garde|improvis\w*|experimental|"
                           r"noise|drone|psychedelic|disco|metal|pop|song|band)\b", re.I)

# a composer: "composer" is the first thing the page says they are ("a Classical composer", "a German composer,
# virtuoso pianist"), not after another role ("a jazz pianist, composer" is a performer)
COMPOSER_HEAD = re.compile(
    r"^\s*(?:an?|the)\s+(?:(?!(?:drummer|percussionist|saxophonist|pianist|bassist|trumpeter|trombonist|guitarist|"
    r"singer|vocalist|bandleader|clarinetist|violinist|cellist|organist|keyboardist|rapper|DJ|producer|songwriter|"
    r"conductor|known|for|of|who|that|which|with|by|in|at|from|on|as|and|or)\b)[\w'’.&–-]+\s+){0,5}?composer\b", re.I)
# a piece of music: "X is an opera buffa …", "a piano concerto", "a string quartet"; ensembles with an infobox are
# musicians first, and the sentence must also sound like music (a "mass" can be physics)
WORK_HEAD = re.compile(
    r"^\s*(?:an?|the)\s+(?:(?!(?:known|for|of|who|that|which|with|by|in|at|from|on|as|and|or)\b)[\w'’.&–-]+\s+){0,6}?"
    r"(?:opera|singspiel|operetta|symphony|concerto|sonata|string quartet|piano quartet|string quintet|piano quintet|"
    r"piano trio|serenade|divertimento|oratorio|cantata|requiem|mass|motet|overture|ballet|suite|rondo|fantasia|"
    r"fugue|aria|prelude|nocturne|waltz|mazurka|polonaise|partita|song cycle|tone poem|symphonic poem|"
    r"musical composition|composition for|work for|oratorio)\b", re.I)
WORK_CONTEXT = re.compile(r"\b(composed|composer|libretto|K\.\s?\d|Op\.\s?\d|movements?|orchestra|piano|violin|cello|"
                          r"soprano|choir|choral|act|acts|opera|score|key of|in [A-G][ -](?:flat |sharp )?(?:major|minor))\b", re.I)


def composer_head(first: str) -> bool:
    m = re.search(r"\b(?:is|was|are|were)\b(.{0,160})", first or "")
    return bool(COMPOSER_HEAD.search(m.group(1))) if m else False


KIND_ORDER = [("musician", "Musicians and groups"), ("work", "Works"), ("recorder", "Most often recorded by"),
              ("record", "Records"), ("label", "Labels"),
              ("scene", "Scenes and styles"), ("person", "Other people"), ("place", "Places"), ("other", "Other")]
MAIN_KINDS = {"musician", "record", "label", "scene", "work", "recorder"}


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

    def exact(self, name: str):
        """the article with exactly this title: as typed, then with a capital first letter, then Title Case.
        (Archive paths are case-sensitive; "nirvana" must find "Nirvana", not a title-search guess.)"""
        n = norm(name)
        for v in dict.fromkeys((n, n[:1].upper() + n[1:], n.title())):
            e = self.entry(v)
            if e is not None:
                return e
        return None

    def find(self, name: str):
        """the article for a name: exact title first, then the top title suggestion"""
        e = self.exact(name)
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
        self.is_disambig_box = bool(re.search(rb"dmbox-disambig|id=.disambigbox", raw))
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
        self.first_para = ""            # the first paragraph however short: "Nirvana most commonly refers to:"
        self.mentions = {}              # path -> [(section, sentence, in_lead)]
        self.sentences = 0
        if not full:
            for p in content.iter("p"):
                t = REFMARK.sub("", norm(p.text_content()))
                if t and not self.first_para:
                    self.first_para = t[:200]
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
            for el in list(val.iter()):
                if isinstance(el.tag, str) and el.getparent() is not None and (
                        el.tag in SKIP_TAGS or classes(el) & (SKIP_CLASS | {"bday", "dtstart", "published"})
                        or "display:none" in (el.get("style") or "").replace(" ", "")):
                    el.drop_tree()
            for br in val.iter("br"):
                br.tail = " · " + (br.tail or "")
            for li in val.iter("li"):
                if li.getprevious() is not None:
                    li.text = ", " + (li.text or "")
            links = [p for a in val.iter("a") if (p := resolve(self.base, a.get("href")))]
            text = REFMARK.sub("", norm(val.text_content()))
            text = re.sub(r"\(\d{4}-\d{2}-\d{2}\)\s*", "", text).strip(" ·,")
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
            if not self.first_para and el.tag == "p":
                self.first_para = text[:200]
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
                    lst.append((section or "(opening)", sent, lead, anchor))

    def is_composer(self) -> bool:
        return composer_head(self.first_sentence)

    def is_disambig(self) -> bool:
        """a disambiguation page: "X may refer to:", "X most commonly refers to:", or Wikipedia's own box"""
        return self.is_disambig_box or bool(re.search(
            r"\b(?:may|might|can|could|most commonly|usually|often|also)\s+(?:also\s+)?(?:refer|be used to refer|refers) to\b"
            r"|\brefers? to\b.{0,40}:$", self.first_para or self.first_sentence))

    def kind(self) -> str:
        """musician / record / label / scene / person / place / other, from the infobox and first sentence"""
        labels = {l.lower().rstrip(" :") for l, _, _ in self.infobox_rows}
        ic = " ".join(self.infobox_classes).lower()
        first = self.first_sentence[:300]
        # what it "is", from the first sentence: "X is/was an American jazz drummer ..."
        m = re.search(r"\b(?:is|was|are|were)\b(.{0,160})", first)
        what = m.group(1) if m else first
        if re.match(r"List of |Lists of ", self.title) or re.search(r"\bdiscography$|\bfilmography$", self.title, re.I):
            return "other"                       # lists and discographies are not artists, records or labels
        # an album/song infobox has Released + Recorded (+ Length); "Length" or "Venue" alone is a cathedral or a sport
        if labels & {"released", "recorded", "studio"} or ("album" in ic):
            return "record"
        if labels & {"instruments", "instrument(s)", "instrument", "associated acts", "past members",
                     "spinoff of", "spinoffs"} or "musical-artist" in ic \
                or ({"genres", "genre"} & labels and {"labels", "label"} & labels):
            return "musician"
        if labels & {"distributor(s)", "distributor"} or LABEL_HEAD.search(what):
            return "label"
        if labels & {"stylistic origins", "cultural origins", "typical instruments", "derivative forms",
                     "subgenres", "fusion genres"}:
            return "scene"
        if WORK_HEAD.search(what) and WORK_CONTEXT.search(first):
            return "work"
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


# ================================================================ music.db (MusicBrainz)
MB_REL = {   # (seed -> other, other -> seed)
    "member of band": ("member of", "member"),
    "collaboration": ("collaborated in", "collaborator"),
    "supporting musician": ("supporting musician for", "supporting musician"),
    "instrumental supporting musician": ("played for", "played for them"),
    "vocal supporting musician": ("sang for", "sang for them"),
    "teacher": ("taught", "teacher"),
    "subgroup": ("subgroup of", "subgroup"),
    "founder": ("founded", "founder"),
    "conductor position": ("conducted", "conductor"),
    "artistic director": ("artistic director of", "artistic director"),
}
MB_SPLIT = 1.35         # Wikipedia parts add up to 1.00, music.db parts to 0.35: scores are divided by this
MB_SPLIT_LABEL = 1.30   # for a label the music.db part (albums on the label) is worth 0.30


def find_musicdb(arg):
    if arg:
        if not os.path.exists(arg):
            sys.exit(f"connections: no such file: {arg}")
        return arg
    for p in (os.environ.get("MUSICDB"), os.path.join(os.path.expanduser("~"), "musicdb", "music.db"),
              os.path.join(os.path.dirname(os.path.abspath(__file__)), "musicdb", "music.db")):
        if p and os.path.exists(p):
            return p
    return None


class MusicDB:
    BUDGET = 25.0          # seconds a lookup may take before it is abandoned (Wikipedia-only answer instead)

    def __init__(self, path, budget: float = BUDGET):
        self.path = path
        self.budget = budget
        self.deadline = None
        self.con = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
        self.con.set_progress_handler(self._expired, 200000)
        try:
            self.stamp = self.con.execute("SELECT value FROM meta WHERE key='musicbrainz_dump'").fetchone()[0][:10]
        except Exception:
            self.stamp = ""

    def _expired(self):
        return 1 if self.deadline is not None and time.time() > self.deadline else 0

    def start_clock(self):
        self.deadline = time.time() + self.budget

    def artist_for(self, seed: "Article"):
        """the MusicBrainz artist for a Wikipedia article: by title, else by name (most connected wins)"""
        title = posixpath.basename(seed.path)
        rows = self.con.execute("SELECT id FROM artist WHERE wiki=?", (title,)).fetchall()
        if not rows:
            name = re.sub(r"\s*\(.*?\)\s*$", "", seed.title)
            rows = self.con.execute("SELECT id FROM artist WHERE name=? COLLATE NOCASE", (name,)).fetchall()
        if not rows:
            return None
        if len(rows) == 1:
            return rows[0][0]
        return max((r[0] for r in rows), key=lambda i: self.con.execute(
            "SELECT (SELECT count(*) FROM played WHERE a=?) + (SELECT count(*) FROM played WHERE b=?)", (i, i)).fetchone()[0])

    def label_roster(self, seed: "Article", limit: int = 60):
        """for a label: (name as MusicBrainz has it, {artist id: partner-like dict}) from the label table,
        artists with the most albums on it first. ({}, "") if MusicBrainz doesn't know the label."""
        base = re.sub(r"\s*\((?:[^()]*\b(?:label|records?|company|imprint)\b[^()]*)\)\s*$", "", seed.title, flags=re.I).strip()
        for name in dict.fromkeys((base, base.rstrip("."), base + ".")):
            rows = self.con.execute("""SELECT a.id, a.name, a.wiki, a.type, l.n, l.name FROM label l
                                       JOIN artist a ON a.id = l.artist WHERE l.name = ? COLLATE NOCASE
                                       ORDER BY l.n DESC, a.name LIMIT ?""", (name, limit)).fetchall()
            if rows:
                return rows[0][5], {oid: {"id": oid, "name": nm, "wiki": wiki, "type": typ, "albums": n, "tracks": 0,
                                          "example": None, "year": None, "rels": [], "on_label": True}
                                    for oid, nm, wiki, typ, n, _ in rows}
        return "", {}

    def label_albums(self, label: str, artist: int, limit: int = 12) -> list:
        """[(album, year)] this artist put out on this label (needs music.db 0.5), earliest first"""
        try:
            return self.con.execute("""SELECT album, year FROM label_album WHERE label = ? COLLATE NOCASE AND artist = ?
                                       ORDER BY year IS NULL, year, album LIMIT ?""", (label, artist, limit)).fetchall()
        except sqlite3.Error:
            return []

    def weight_for_title(self, wiki_path: str) -> int:
        """how connected the MusicBrainz artist with this Wikipedia title is (0 if none): to pick the
        big "Nirvana (band)" over a small namesake"""
        title = posixpath.basename(wiki_path)
        n = 0
        for (i,) in self.con.execute("SELECT id FROM artist WHERE wiki=?", (title,)).fetchall():
            n += self.con.execute("SELECT (SELECT count(*) FROM played WHERE a=?) + (SELECT count(*) FROM played WHERE b=?)",
                                  (i, i)).fetchone()[0]
        return n

    def partners(self, aid: int, limit: int = 60) -> dict:
        """other artist id -> {name, wiki, type, albums, tracks, example, year, rels: [text]}"""
        out = {}
        for oid, name, wiki, typ, alb, trk, ex, yr in self.con.execute("""
                SELECT x.id, x.name, x.wiki, x.type, q.albums, q.tracks, q.example, q.year FROM (
                    SELECT * FROM (SELECT b o, albums, tracks, example, year FROM played WHERE a=?
                                   ORDER BY albums DESC, tracks DESC LIMIT ?)
                    UNION ALL
                    SELECT * FROM (SELECT a o, albums, tracks, example, year FROM played WHERE b=?
                                   ORDER BY albums DESC, tracks DESC LIMIT ?)
                    ORDER BY albums DESC, tracks DESC LIMIT ?) q
                JOIN artist x ON x.id = q.o ORDER BY q.albums DESC, q.tracks DESC""", (aid, limit, aid, limit, limit)):
            out[oid] = {"id": oid, "name": name, "wiki": wiki, "type": typ, "albums": alb or 0, "tracks": trk or 0,
                        "example": ex, "year": yr, "rels": []}
        for oid, name, wiki, typ, kind, rev, b, e in self.con.execute("""
                SELECT x.id, x.name, x.wiki, x.type, r.kind, 0, r.begin, r.end FROM rel r JOIN artist x ON x.id=r.b WHERE r.a=?
                UNION ALL
                SELECT x.id, x.name, x.wiki, x.type, r.kind, 1, r.begin, r.end FROM rel r JOIN artist x ON x.id=r.a WHERE r.b=?""",
                (aid, aid)):
            if kind not in MB_REL:
                continue
            d = out.setdefault(oid, {"id": oid, "name": name, "wiki": wiki, "type": typ, "albums": 0, "tracks": 0,
                                     "example": None, "year": None, "rels": []})
            yrs = f"{b or ''}–{e or ''}" if (b or e) else ""
            d["rels"].append(MB_REL[kind][rev] + (f" ({yrs})" if yrs else ""))
        return out


def mb_text(m: dict) -> str:
    bits = []
    if m["rels"]:
        bits.append("; ".join(dict.fromkeys(m["rels"])))
    if m["albums"]:
        s = f"{m['albums']} album{'s' * (m['albums'] != 1)} together"
        if m["example"]:
            s += f", first {m['example']}" + (f" ({m['year']})" if m["year"] else "")
        bits.append(s)
    elif m["tracks"]:
        bits.append(f"{m['tracks']} track{'s' * (m['tracks'] != 1)} together")
    return "MusicBrainz: " + "; ".join(bits) if bits else ""


# ================================================================ ranking
class Ranked(list):
    """the ranked connections, plus what the seed was read as (label_mode) and its MusicBrainz name"""
    label_mode = False
    composer_mode = False
    label_name = ""


def connections(wiki: Wiki, seed: Article, progress=True, mb: "MusicDB | None" = None):
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
        r["mb"] = None
    seed_kind = seed.kind()
    label_mode = seed_kind == "label"
    composer_mode = seed_kind == "musician" and seed.is_composer()
    label_name = ""
    ranked_mb = mb
    if mb:
        partners = {}
        if progress:
            print("   looking in music.db…", end="", file=sys.stderr, flush=True)
        mb.start_clock()
        t1 = time.time()
        try:
            if label_mode:                                   # a label: its roster (artists, albums on it)
                label_name, partners = mb.label_roster(seed)
            elif seed_kind not in ("record", "scene"):       # an artist: who they played with
                aid = mb.artist_for(seed)
                partners = mb.partners(aid) if aid is not None else {}
            if progress:
                print(f" {time.time() - t1:.1f}s", file=sys.stderr)
        except sqlite3.OperationalError:                     # too slow: give the Wikipedia-only answer, say so
            partners, ranked_mb = {}, None
            if progress:
                print(f" gave up after {mb.budget:.0f}s; Wikipedia only for this one", file=sys.stderr)
        mb.deadline = None
        if partners and composer_mode:
            add_recorders(wiki, seed, out, partners, seed_links)
            partners = {}
        if partners:
            added = 0
            for oid, m in partners.items():
                e = wiki.entry(m["wiki"]) if m["wiki"] else None
                if e is not None and e.path in out:
                    out[e.path]["mb"] = m
                    continue
                if not (m["albums"] or m["rels"]) or added >= 30:
                    continue
                added += 1
                if e is not None and e.path != seed.path:
                    try:
                        target = Article(wiki, e, full=False)
                    except Exception:
                        continue
                    out[e.path] = {"path": e.path, "title": target.title, "kind": target.kind(),
                                   "first": target.first_sentence, "mentions": [], "infobox": None,
                                   "back": seed.path in target.all_links or any(
                                       posixpath.basename(l) == posixpath.basename(seed.path) for l in target.all_links),
                                   "shared": cosine(seed_links, target.all_links), "mb": m}
                    if out[e.path]["kind"] not in MAIN_KINDS:
                        out[e.path]["kind"] = "musician"      # MusicBrainz says they played together
                elif e is None:
                    out[f"mb:{oid}"] = {"path": None, "title": m["name"], "kind": "musician", "first": "",
                                        "mentions": [], "infobox": None, "back": False, "shared": 0.0, "mb": m,
                                        "offwiki": True}
            if progress:
                print(f"   music.db: {added} more musicians from MusicBrainz", file=sys.stderr)
    split = MB_SPLIT_LABEL if label_mode else MB_SPLIT
    for r in out.values():
        n = len(r["mentions"])
        parts = {
            "mentioned": 0.30 * min(n, 3) / 3,
            "lead": 0.15 * (1 if any(m[2] for m in r["mentions"]) else 0),
            "infobox": 0.10 * (1 if r["infobox"] else 0),
            "links back": 0.25 * (1 if r["back"] else 0),
            "shared": 0.20 * min(1.0, r["shared"] / 0.5),       # cosine 0.5+ counts as fully shared
        }
        if ranked_mb and label_mode:
            m = r.get("mb")
            parts["on label"] = 0.30 * min(m["albums"], 4) / 4 if m else 0.0
            parts = {k: v / split for k, v in parts.items()}
        elif ranked_mb and not composer_mode:
            m = r.get("mb")
            parts["played"] = (0.25 * min(m["albums"], 3) / 3 if m and m["albums"] else
                               0.10 * min(m["tracks"], 10) / 10 if m and m["tracks"] else 0.0)
            parts["band/teacher"] = 0.10 if m and m["rels"] else 0.0
            parts = {k: v / split for k, v in parts.items()}
        r["parts"] = parts
        r["score"] = round(sum(parts.values()), 3)
    if composer_mode:
        for r in out.values():
            if r["kind"] == "person":
                r["kind"] = "musician"           # for a composer the people around them (family, patrons) matter
        recs = [r for r in out.values() if r["kind"] == "recorder"]
        top = max((r["mb"]["albums"] for r in recs), default=1) or 1
        for r in recs:
            r["score"] = round(r["mb"]["albums"] / top, 3)    # relative: the most recorded-by is 1.00
    ranked = Ranked(sorted(out.values(), key=lambda r: (-r["score"], -len(r["mentions"]), -r["shared"])))
    ranked.label_mode, ranked.label_name = label_mode, label_name
    ranked.composer_mode = composer_mode
    if label_mode:
        attach_works(ranked)
    return ranked


def add_recorders(wiki: Wiki, seed: Article, out: dict, partners: dict, seed_links, keep: int = 15) -> None:
    """for a composer: MusicBrainz "played" pairs are albums with the composer's name on them, so the useful
    reading is who recorded them. Other composers (couplings: "Beethoven: … / Mozart: …") are dropped."""
    found = []
    for oid, m in partners.items():
        if not m["albums"]:
            continue
        e = wiki.entry(m["wiki"]) if m["wiki"] else None
        if e is not None and e.path == seed.path:
            continue
        first = None
        if e is not None:
            first = out[e.path]["first"] if e.path in out else None
            if first is None:
                try:
                    first = Article(wiki, e, full=False).first_sentence
                except Exception:
                    first = ""
            if composer_head(first):
                continue
        found.append((m, e))
    for m, e in sorted(found, key=lambda t: -t[0]["albums"])[:keep]:
        if e is not None and e.path in out:
            out[e.path]["kind"], out[e.path]["mb"] = "recorder", m
        elif e is not None:
            try:
                target = Article(wiki, e, full=False)
            except Exception:
                continue
            out[e.path] = {"path": e.path, "title": target.title, "kind": "recorder", "first": target.first_sentence,
                           "mentions": [], "infobox": None, "back": False, "shared": 0.0, "mb": m}
        else:
            out[f"mb:{m['id']}"] = {"path": None, "title": m["name"], "kind": "recorder", "first": "", "mentions": [],
                                    "infobox": None, "back": False, "shared": 0.0, "mb": m, "offwiki": True}


def attach_works(ranked: list) -> None:
    """for a label: hang each linked record on the artist its first sentence names ("… album by Blondes"),
    so the label reads as artists with their records, not two loose lists"""
    artists = [(re.sub(r"\s*\(.*?\)\s*$", "", r["title"]), r) for r in ranked if r["kind"] == "musician"]
    for rec in ranked:
        if rec["kind"] != "record" or not rec["first"]:
            continue
        best = None
        for nm, a in artists:
            if len(nm) < 3:
                continue
            m = re.search(r"(?<!\w)" + re.escape(nm) + r"(?!\w)", rec["first"])
            if m and (best is None or m.start() < best[0]):
                best = (m.start(), a)
        if best:
            yr = re.search(r"released[^.]{0,40}?\b((?:19|20)\d\d)\b", rec["first"]) or re.search(r"\b((?:19|20)\d\d)\b", rec["first"])
            best[1].setdefault("works", []).append((plain_record(rec["title"]), int(yr.group(1)) if yr else None))
            rec["owner"] = best[1]["title"]


def plain_record(title: str) -> str:
    """"Swisher (album)" -> "Swisher" """
    return re.sub(r"\s*\((?:[^()]*\b(?:album|EP|single|song|soundtrack|mixtape|compilation)\b[^()]*)\)\s*$", "", title, flags=re.I)


def window(sent: str, anchor: str, width: int) -> str:
    """the sentence, or the part of it around the link's words if it's long"""
    if len(sent) <= width:
        return sent
    i = sent.find(anchor) if anchor else -1
    if i < 0 or i + len(anchor) < width - 20:
        return sent[:width].rsplit(" ", 1)[0] + "…"
    start = max(0, i - width // 2)
    start = sent.find(" ", start) + 1 if start else 0
    piece = sent[start:start + width]
    if start + width < len(sent):
        piece = piece.rsplit(" ", 1)[0] + "…"
    return "…" + piece


def cosine(a: set, b: set) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / math.sqrt(len(a) * len(b))


LISTY = {"discography", "selected discography", "discography (partial)", "works", "selected works",
         "recordings", "selected recordings", "albums"}


def reason(r: dict, used: "dict | None" = None, width: int = 220) -> str:
    """the sentence that makes the connection. `used` (sentence -> who it was shown for) keeps one sentence
    from being printed again and again: the next-best sentence is chosen, else a pointer to the first"""
    if r["mentions"]:
        name = re.sub(r"\s*\(.*?\)\s*$", "", r["title"])
        surname = name.split()[-1].lower() if name.split() else ""
        # prose before list items; the opening first; a sentence that names it; then the shortest real one
        options = sorted(r["mentions"], key=lambda m: (
            m[0] in LISTY, not m[2], surname not in m[1].lower(), abs(len(m[1]) - 140)))
        for sec, sent, _, anchor in options:
            if used is None or sent not in used:
                if used is not None:
                    used[sent] = r["title"]
                return f"“{window(sent, anchor, width)}”" + (f"  [{sec}]" if sec and sec != "(opening)" else "")
        return f"(named in the same sentence as {used[options[0][1]]})"
    if r["infobox"]:
        return f"listed in the infobox under “{r['infobox']}”"
    return ""


# ================================================================ which page did you mean?
SUFFIXES = ("band", "musician", "singer", "rapper", "group", "duo", "American band", "British band", "rock band",
            "composer", "drummer", "saxophonist", "pianist", "singer-songwriter", "record label", "album")


class Ambiguous(Exception):
    def __init__(self, options: list):
        self.options = options


def what_is(first: str, width: int = 90) -> str:
    m = re.search(r"\b(?:is|was|are|were)\b\s+(.{0,160})", first or "")
    t = (m.group(1) if m else first or "").strip()
    return t if len(t) <= width else t[:width].rsplit(" ", 1)[0] + "…"


def music_candidates(wiki: Wiki, page: Article) -> list:
    """music pages that go by the same name: the links of a disambiguation page, "Name (disambiguation)",
    and "Name (band)", "Name (singer)" … (musician, label, record or scene pages only)"""
    base = re.sub(r"\s*\(.*?\)\s*$", "", page.title)
    seen, out = {page.path}, []
    stem = re.sub(r"\W+", "", base).casefold()

    def named_like(path):
        """a page that goes by this name: its title starts with it ("Nirvana (band)", "Nirvana 2002"), so an
        artist merely mentioned in a disambiguation entry ("… a song by Azealia Banks") is never a candidate"""
        return re.sub(r"\W+", "", posixpath.basename(path)).casefold().startswith(stem)

    def add(path):
        if not named_like(path):
            return
        x = wiki.entry(path)
        if x is None or x.path in seen:
            return
        seen.add(x.path)
        try:
            t = Article(wiki, x, full=False)
        except Exception:
            return
        if t.is_disambig():
            return
        k = t.kind()
        if k in MAIN_KINDS:
            out.append({"path": x.path, "title": t.title, "kind": k, "first": t.first_sentence})

    if page.is_disambig():
        for p in list(page.mentions)[:400]:
            add(p)
    d = wiki.exact(f"{base} (disambiguation)")
    if d is not None and d.path != page.path:
        for p in list(Article(wiki, d).mentions)[:400]:
            add(p)
    for sfx in SUFFIXES:
        x = wiki.exact(f"{base} ({sfx})")
        if x is not None:
            add(x.path)
    order = {"musician": 0, "label": 1, "record": 2, "scene": 3}
    return sorted(out, key=lambda c: order[c["kind"]])


def choose_seed(wiki: Wiki, name: str, mb: "MusicDB | None"):
    """-> (seed Article, note) or (None, note) when nothing matches; raises Ambiguous(options) when the name
    could be several music pages and none clearly dominates. Never guesses silently."""
    e = wiki.exact(name)
    if e is None:                                            # no such title: the closest one, preferring music
        found = []
        for p in suggest(wiki.zim, name, 6):
            x = wiki.entry(p)
            if x is not None and all(x.path != y.path for y in found):
                found.append(x)
        if not found:
            return None, ""
        pick = next((x for x in found[:5] if Article(wiki, x, full=False).kind() in MAIN_KINDS), found[0])
        return Article(wiki, pick), f"no page called “{name}”; closest title: {pick.title}"
    page = Article(wiki, e)
    if not page.is_disambig() and page.kind() != "other":
        return page, ""
    cands = music_candidates(wiki, page)
    if not cands:
        if page.is_disambig():
            raise Ambiguous([{"title": posixpath.basename(p).replace("_", " "), "first": ""}
                             for p in list(page.mentions)[:12]])
        return page, ""                                      # something else entirely, and no music page: read it as is
    primary = [c for c in cands if c["kind"] in ("musician", "label")]
    chosen = None
    if len(primary) == 1:
        chosen = primary[0]
    elif len(primary) > 1 and mb:
        w = sorted(((mb.weight_for_title(c["path"]), c) for c in primary), key=lambda t: -t[0])
        if w[0][0] >= 20 and w[0][0] >= 5 * max(1, w[1][0]):
            chosen = w[0][1]
    if chosen is None:
        raise Ambiguous(cands)
    x = wiki.entry(chosen["path"])
    others = [c["title"] for c in cands if c is not chosen][:6]
    note = f"“{name}” read as {chosen['title']}" + (f". Other music pages with that name: {'; '.join(others)}" if others else "")
    return Article(wiki, x), note


# ================================================================ output
def works_line(r: dict, mb: "MusicDB | None", label_name: str, limit: int = 6) -> str:
    """for a label's artist: their records on the label, from the label's article and from MusicBrainz"""
    items = {}
    for t, y in r.get("works", []):
        items.setdefault(re.sub(r"\W+", "", t.casefold()), [t, y])
    m = r.get("mb") or {}
    if mb and label_name and m.get("id"):
        for t, y in mb.label_albums(label_name, m["id"]):
            k = re.sub(r"\W+", "", t.casefold())
            if k in items:
                items[k][1] = items[k][1] or y
            else:
                items[k] = [t, y]
    n = m.get("albums", 0)
    if not items:
        return f"On the label: {n} album{'s' * (n != 1)} (MusicBrainz)" if n else ""
    ordered = sorted(items.values(), key=lambda t: (t[1] is None, t[1] or 0, t[0]))
    text = " · ".join(t + (f" ({y})" if y else "") for t, y in ordered[:limit])
    if len(ordered) > limit:
        text += f"  (+{len(ordered) - limit} more)"
    return "On the label: " + text


LABEL_HEADINGS = {"musician": "Artists on the label", "record": "Other records", "label": "Related labels",
                  "scene": "Scenes and styles"}


def main():
    ap = argparse.ArgumentParser(description="Connections from offline Wikipedia (gleaner prototype).")
    ap.add_argument("name", help='an artist, record, label or scene, e.g. "Milford Graves"')
    ap.add_argument("--zim", help="the Wikipedia .zim (default: biggest wikipedia*.zim in ~/zim)")
    ap.add_argument("--top", type=int, default=8, help="how many per group (default 8)")
    ap.add_argument("--all", action="store_true", help="also show other people, places and other links")
    ap.add_argument("--why", action="store_true", help="show how each score was made")
    ap.add_argument("--musicdb", help="music.db from tools/musicdb (default: found automatically)")
    ap.add_argument("--no-musicdb", action="store_true", help="Wikipedia only")
    a = ap.parse_args()

    wiki = Wiki(find_zim(a.zim))
    mbpath = None if a.no_musicdb else find_musicdb(a.musicdb)
    mb = MusicDB(mbpath) if mbpath else None
    print(f"connections {VERSION} · {os.path.basename(wiki.path)}"
          + (f" · music.db (MusicBrainz {mb.stamp})" if mb else " · no music.db"), file=sys.stderr)
    try:
        seed, note = choose_seed(wiki, a.name, mb)
    except Ambiguous as amb:
        print(f"“{a.name}” could be several things. Ask again with the full title:\n")
        width = max(len(c["title"]) for c in amb.options) + 18
        for c in amb.options:
            cmd = f"connections.py \"{c['title']}\""
            print(f"  {cmd:<{width}}" + (f"{what_is(c['first'])}" if c["first"] else ""))
        sys.exit(2)
    if seed is None:
        alts = wiki.suggestions(a.name)
        sys.exit(f"No article for “{a.name}”." + (" Did you mean: " + "; ".join(alts) if alts else ""))

    kind = seed.kind()
    print(f"\n{seed.title}  ({'composer' if kind == 'musician' and seed.is_composer() else kind})")
    if note:
        print(f"  ({note})")
    if seed.first_sentence:
        print("  " + (seed.first_sentence[:300] + ("…" if len(seed.first_sentence) > 300 else "")))
    wanted = ("genre", "genres", "instrument", "instruments", "instrument(s)", "labels", "label", "years active",
              "associated acts", "members", "past members", "origin", "born", "released", "recorded", "founded",
              "founder", "country of origin", "location")
    facts = [(l, t) for l, t, _ in seed.infobox_rows if l.lower().rstrip(":") in wanted and t]
    if facts:
        print()
        for l, t in facts:
            print(f"  {l}: {t[:200]}")
    print()

    ranked = connections(wiki, seed, mb=mb)
    label_mode = ranked.label_mode
    composer_mode = ranked.composer_mode
    headings = {**dict(KIND_ORDER), **LABEL_HEADINGS} if label_mode else dict(KIND_ORDER)
    if composer_mode:
        headings["musician"] = "People"
    used = {}                                   # sentences already shown, so none is repeated
    shown = 0
    for k, _ in KIND_ORDER:
        heading = headings[k]
        if k not in MAIN_KINDS and not a.all:
            continue
        if composer_mode and k == "label":
            continue                            # labels hardly matter for a composer: the performers do
        floor = 0.20 if label_mode and k == "label" else 0.12
        rows = [r for r in ranked if r["kind"] == k and not r.get("owner")
                and (r["score"] > floor or (k in MAIN_KINDS and not (label_mode and k == "label")
                                            and (r["mentions"] or r.get("mb"))))][:a.top]
        if not rows:
            continue
        print(f"\n{heading}")
        print("-" * len(heading))
        for r in rows:
            shown += 1
            print(f"{r['score']:.2f}  {r['title']}" + ("  (not on Wikipedia)" if r.get("offwiki") else ""))
            if label_mode and k == "musician":
                w = works_line(r, mb, ranked.label_name)
                if w:
                    print(f"      {w}")
            if k == "recorder":
                m = r["mb"]
                print(f"      {m['albums']} albums on MusicBrainz"
                      + (f"; first: {m['example']}" + (f" ({m['year']})" if m.get("year") else "") if m.get("example") else ""))
                continue
            why = reason(r, used)
            if why:
                print(f"      {why}")
            if r.get("mb") and not label_mode:
                t = mb_text(r["mb"])
                if t:
                    print(f"      {t}")
            if a.why:
                p = r["parts"]
                print("      " + " · ".join(f"{pk} {v:.2f}" for pk, v in p.items() if v)
                      + f"   (mentions {len(r['mentions'])}, shared {r['shared']:.2f}, back {'yes' if r['back'] else 'no'})")
    if not shown:
        print("No strong connections found." + ("" if a.all else " Try --all."))
    hidden = sum(1 for r in ranked if r["kind"] not in MAIN_KINDS)
    if not a.all and hidden:
        print(f"\n({hidden} other links to people, places and other things: add --all to see them)")


if __name__ == "__main__":
    main()
