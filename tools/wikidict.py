#!/usr/bin/env python3
"""
wikidict: an offline Wikipedia dictionary for Cyby (KOReader), made on exlo.

Long-press a word on Cyby and the opening of its Wikipedia article appears,
with no Wi-Fi. Built from the Wikipedia .zim that WIKISTACK already reads,
keeping only the most-read articles so it stays small.

    python3 wikidict.py                    # 100,000 articles (the default)
    python3 wikidict.py --articles 250000  # bigger
    python3 wikidict.py --help

How it chooses articles: it downloads a sample of Wikipedia's public hourly
page-view counts (about 24 files, ~50 MB each, kept in ~/.cache/wikidict so a
second run needs no download), adds them up, and keeps the most-read articles.

Output: a folder (e.g. ~/wikidict/Wikipedia 100k) holding a StarDict
dictionary. Copy that folder into koreader/data/dict/ on Cyby.

Needs: python3, python3-libzim, python3-lxml (all already used by WIKISTACK).
Text from Wikipedia, CC BY-SA 4.0.
"""

import argparse
import datetime as dt
import gzip
import html
import os
import re
import struct
import sys
import time
import urllib.parse
import urllib.request
import zlib

try:
    from libzim.reader import Archive
except ImportError:
    sys.exit("wikidict: needs libzim.  sudo apt install python3-libzim")
try:
    import lxml.html
except ImportError:
    sys.exit("wikidict: needs lxml.  sudo apt install python3-lxml")

VERSION = "1.0"
HOME = os.path.expanduser("~")
ZIM_DIR = os.environ.get("WIKISTACK_ZIM_DIR", os.path.join(HOME, "zim"))
CACHE = os.path.join(os.environ.get("XDG_CACHE_HOME") or os.path.join(HOME, ".cache"), "wikidict")
OUT_DIR = os.path.join(HOME, "wikidict")
UA = f"wikidict/{VERSION} (personal offline dictionary; KOReader)"
DUMPS = "https://dumps.wikimedia.org/other/pageviews/{y}/{y}-{m:02d}/pageviews-{y}{m:02d}{d:02d}-{h:02d}0000.gz"

NOT_ARTICLE = re.compile(r"(?:Category|User|User_talk|Talk|Wikipedia|Template|Portal|Help|File|Draft|Module|"
                         r"MediaWiki|Special|TimedText|Book|Index|Media|Image|WP|Main_Page$)", re.I)
DISAMBIG = re.compile(r"(may|might|can) (also )?(refer|be used to refer) to\b.{0,40}:?\s*$", re.I)
WS = re.compile(r"\s+")
PAREN = re.compile(r"\s*\([^()]*\)$")
SKIP_CLASSES = ("reference", "noprint", "mw-ref", "mw-editsection", "IPA-label", "rt-commentedText",
                "mw-empty-elt", "hatnote", "infobox", "navbox", "metadata", "sistersitebox", "geo")


def say(*a):
    print(*a, flush=True)


# ---------------------------------------------------------------- page views

def sample_hours(n, today=None):
    """n hours spread over the last complete month, at varied times of day"""
    today = today or dt.date.today()
    first_this = today.replace(day=1)
    last_month_end = first_this - dt.timedelta(days=1)
    start = last_month_end.replace(day=1)
    days = (last_month_end - start).days + 1
    out = []
    for i in range(n):
        d = start + dt.timedelta(days=(i * days) // n)
        out.append((d.year, d.month, d.day, (i * 7 + 3) % 24))
    return out


def fetch(url, dest):
    if os.path.exists(dest) and os.path.getsize(dest) > 0:
        return dest
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    part = dest + ".part"
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=120) as r, open(part, "wb") as f:
        while True:
            b = r.read(1 << 20)
            if not b:
                break
            f.write(b)
    os.replace(part, dest)
    return dest


def norm_title(t):
    if "%" in t:
        t = urllib.parse.unquote(t)
    t = t.replace(" ", "_").strip("_")
    return t[:1].upper() + t[1:] if t else t


def count_views(files, keep=1_500_000):
    """add up English Wikipedia (desktop + mobile) views from hourly files"""
    counts = {}
    for i, path in enumerate(files, 1):
        t0 = time.time()
        with gzip.open(path, "rb") as f:
            for line in f:
                if not (line.startswith(b"en ") or line.startswith(b"en.m ")):
                    continue
                parts = line.split(b" ")
                if len(parts) < 3:
                    continue
                try:
                    title = norm_title(parts[1].decode("utf-8"))
                    n = int(parts[2])
                except (UnicodeDecodeError, ValueError):
                    continue
                if title and not NOT_ARTICLE.match(title):
                    counts[title] = counts.get(title, 0) + n
        if len(counts) > keep * 3:          # keep memory sensible on exlo: drop the long tail as we go
            cut = sorted(counts.values(), reverse=True)[keep]
            counts = {k: v for k, v in counts.items() if v > cut}
        say(f"  page views {i}/{len(files)}  ({len(counts):,} titles, {time.time() - t0:.0f}s)")
    return counts


def load_views(args):
    if args.titles:                         # a ready list, one title per line, most important first
        with open(args.titles, encoding="utf-8") as f:
            lines = [norm_title(l.strip()) for l in f if l.strip()]
        return {t: len(lines) - i for i, t in enumerate(lines)}
    folder = args.pageviews_dir or os.path.join(CACHE, "pageviews")
    files = []
    if args.pageviews_dir:
        files = sorted(os.path.join(folder, f) for f in os.listdir(folder) if f.endswith(".gz"))
    else:
        hours = sample_hours(args.hours)
        say(f"Downloading {len(hours)} hours of page views (cached in {folder.replace(HOME, '~')})")
        for j, (y, m, d, h) in enumerate(hours, 1):
            url = DUMPS.format(y=y, m=m, d=d, h=h)
            dest = os.path.join(folder, os.path.basename(url))
            try:
                fetch(url, dest)
                files.append(dest)
                say(f"  got {j}/{len(hours)}  {os.path.basename(url)}")
            except Exception as e:
                say(f"  skipped {os.path.basename(url)}: {e}")
            time.sleep(0.5)                 # be polite to Wikimedia's servers
    if not files:
        sys.exit("wikidict: no page-view files to count. Is exlo online? (or use --titles / --pageviews-dir)")
    return count_views(files)


# ---------------------------------------------------------------- the .zim

def find_zim(path):
    if path:
        return path
    if not os.path.isdir(ZIM_DIR):
        sys.exit(f"wikidict: no {ZIM_DIR}. Use --zim /path/to/wikipedia.zim")
    zims = [os.path.join(ZIM_DIR, f) for f in os.listdir(ZIM_DIR) if f.endswith(".zim")]
    if not zims:
        sys.exit(f"wikidict: no .zim files in {ZIM_DIR}")
    return max(zims, key=os.path.getsize)   # the full Wikipedia is the biggest


class Zim:
    def __init__(self, path):
        self.a = Archive(path)
        self.prefix = ""
        try:                                # old-style archives keep articles under A/
            if self.a.main_entry.get_item().path.startswith("A/"):
                self.prefix = "A/"
        except Exception:
            pass

    def entry(self, title):
        for p in (self.prefix + title, title):
            try:
                return self.a.get_entry_by_path(p)
            except Exception:
                continue
        return None

    def resolve(self, title):
        """(article entry, was_redirect) or (None, False)"""
        e = self.entry(title)
        if e is None:
            return None, False
        hops = 0
        while e.is_redirect and hops < 6:
            try:
                e = e.get_redirect_entry()
            except Exception:
                return None, False
            hops += 1
        if e.is_redirect:
            return None, False
        try:
            if not e.get_item().mimetype.startswith("text/html"):
                return None, False
        except Exception:
            return None, False
        return e, hops > 0


def choose(zim, views, n, max_syn):
    """the n most-read articles; redirects add their views to their article and become synonyms"""
    say("Matching the most-read titles against the archive")
    ranked = sorted(views.items(), key=lambda kv: kv[1], reverse=True)
    score, title_of, syns = {}, {}, {}
    checked = 0
    t0 = time.time()
    for title, v in ranked:
        checked += 1
        if checked % 50_000 == 0:
            say(f"  checked {checked:,} titles, {len(score):,} articles ({time.time() - t0:.0f}s)")
        e, redirected = zim.resolve(title)
        if e is None:
            continue
        key = e.path
        if key not in score:
            if len(score) >= n * 1.15:      # enough candidates; later titles only add to known ones
                continue
            score[key] = 0
            title_of[key] = e.title or key.split("/")[-1].replace("_", " ")
        score[key] += v
        if redirected:
            syns.setdefault(key, []).append((v, title.replace("_", " ")))
        if checked > n * 6 and len(score) >= n * 1.15:
            break
    chosen = sorted(score, key=score.get, reverse=True)[:n]
    out = []
    for key in chosen:
        s = [t for v, t in sorted(syns.get(key, []), reverse=True) if v >= 2][:max_syn]
        out.append((key, title_of[key], s))
    say(f"  chose {len(out):,} articles")
    return out


# ---------------------------------------------------------------- the opening paragraphs

def skip(el):
    cls = el.get("class") or ""
    if any(c in cls for c in SKIP_CLASSES):
        return True
    st = (el.get("style") or "").replace(" ", "")
    return "display:none" in st


def inline(el, links, out):
    """el's contents as tiny HTML: bold, italic, sub/sup, links to other entries"""
    if el.text:
        out.append(html.escape(el.text, quote=False))
    for c in el:
        tag = c.tag if isinstance(c.tag, str) else ""
        if tag and not skip(c) and tag not in ("style", "script", "link", "meta", "img", "figure", "table"):
            if tag == "sup" and (c.get("class") or "").find("reference") >= 0:
                pass
            elif tag in ("b", "strong"):
                out.append("<b>"); inline(c, links, out); out.append("</b>")
            elif tag in ("i", "em", "cite"):
                out.append("<i>"); inline(c, links, out); out.append("</i>")
            elif tag in ("sub", "sup"):
                out.append(f"<{tag}>"); inline(c, links, out); out.append(f"</{tag}>")
            elif tag == "a" and links is not None:
                target = urllib.parse.unquote((c.get("href") or "").split("#")[0].split("/")[-1])
                word = links.get(target)
                if word:
                    out.append('<a href="bword://' + html.escape(word, quote=False).replace('"', "&quot;") + '">'); inline(c, None, out); out.append("</a>")
                else:
                    inline(c, None, out)
            else:
                inline(c, links, out)
        if c.tail:
            out.append(html.escape(c.tail, quote=False))


def has_bad_parent(p, stop):
    e = p.getparent()
    while e is not None and e is not stop:
        if e.tag in ("table", "aside", "figure", "blockquote", "li") or skip(e):
            return True
        e = e.getparent()
    return False


def opening(raw, links, target_chars):
    """the article's opening paragraphs as small HTML, or None"""
    text = raw.decode("utf-8", "replace")
    start = text.find('id="mw-content-text"')
    cut = text.find("<h2", max(start, 0))
    if cut > 0:                             # only the lead section: much faster on exlo
        text = text[:cut]
    try:
        root = lxml.html.fromstring(text)
    except Exception:
        return None
    content = root.get_element_by_id("mw-content-text", None)
    if content is None:
        content = root.find("body") if root.find("body") is not None else root
    paras, total = [], 0
    for p in content.iter("p"):
        if skip(p) or has_bad_parent(p, content):
            continue
        out = []
        inline(p, links, out)
        h = WS.sub(" ", "".join(out)).strip()
        plain = WS.sub(" ", p.text_content()).strip()
        if len(plain) < 40 and not paras:
            continue
        if not plain:
            continue
        paras.append(h)
        total += len(plain)
        if total >= target_chars or len(paras) >= 3:
            break
    if not paras:
        return None
    if DISAMBIG.search(WS.sub(" ", lxml.html.fromstring("<p>" + paras[0] + "</p>").text_content())):
        return None
    return "".join(f"<p>{h}</p>" for h in paras)


# ---------------------------------------------------------------- StarDict

def stardict_key(word):
    b = word.encode("utf-8")
    return (b.translate(ASCII_LOWER), b)    # StarDict's order: ASCII case-insensitive, then exact


ASCII_LOWER = bytes.maketrans(b"ABCDEFGHIJKLMNOPQRSTUVWXYZ", b"abcdefghijklmnopqrstuvwxyz")


def dictzip(data, path, chunk=58315):
    """gzip with a random-access table (dictzip), so KOReader reads one entry without unpacking all"""
    sizes, body = [], []
    for i in range(0, len(data), chunk):
        c = zlib.compressobj(9, zlib.DEFLATED, -15)
        block = c.compress(data[i:i + chunk]) + c.flush(zlib.Z_FULL_FLUSH)
        sizes.append(len(block))
        body.append(block)
    tail = zlib.compressobj(9, zlib.DEFLATED, -15).flush(zlib.Z_FINISH)
    ra = struct.pack("<HHH", 1, chunk, len(sizes)) + b"".join(struct.pack("<H", s) for s in sizes)
    extra = b"RA" + struct.pack("<H", len(ra)) + ra
    header = (b"\x1f\x8b\x08\x04" + struct.pack("<I", int(time.time())) + b"\x02\x03"
              + struct.pack("<H", len(extra)) + extra)
    with open(path, "wb") as f:
        f.write(header)
        for b in body:
            f.write(b)
        f.write(tail)
        f.write(struct.pack("<II", zlib.crc32(data) & 0xFFFFFFFF, len(data) & 0xFFFFFFFF))
    if len(sizes) > 65535:
        raise ValueError("dictionary too large for one dictzip file")


def write_stardict(folder, name, entries, synonyms, description):
    """entries: [(headword, html)]; synonyms: [(word, index into entries)]"""
    os.makedirs(folder, exist_ok=True)
    order = sorted(range(len(entries)), key=lambda i: stardict_key(entries[i][0]))
    new_index = {old: new for new, old in enumerate(order)}
    data, idx = bytearray(), bytearray()
    for i in order:
        word, body = entries[i]
        b = body.encode("utf-8")
        idx += word.encode("utf-8") + b"\0" + struct.pack(">II", len(data), len(b))
        data += b
    base = os.path.join(folder, name)
    with open(base + ".idx", "wb") as f:
        f.write(idx)
    dictzip(bytes(data), base + ".dict.dz")
    syn = sorted(((w, new_index[i]) for w, i in synonyms), key=lambda s: stardict_key(s[0]))
    if syn:
        with open(base + ".syn", "wb") as f:
            for w, i in syn:
                f.write(w.encode("utf-8") + b"\0" + struct.pack(">I", i))
    ifo = ["StarDict's dict ifo file", "version=3.0.0", f"wordcount={len(entries)}",
           f"idxfilesize={len(idx)}", f"bookname={name}", "sametypesequence=h",
           f"description={description}", f"date={dt.date.today().isoformat()}"]
    if syn:
        ifo.insert(3, f"synwordcount={len(syn)}")
    with open(base + ".ifo", "w", encoding="utf-8", newline="\n") as f:
        f.write("\n".join(ifo) + "\n")
    return base


# ---------------------------------------------------------------- main

def short(n):
    return f"{n // 1000}k" if n >= 1000 and n % 1000 == 0 else str(n)


def main():
    ap = argparse.ArgumentParser(description="Offline Wikipedia dictionary for Cyby (KOReader)")
    ap.add_argument("--articles", type=int, default=100_000, help="how many articles (default 100000)")
    ap.add_argument("--length", type=int, default=700, help="roughly how many characters per entry (default 700)")
    ap.add_argument("--zim", help="the Wikipedia .zim (default: the biggest in ~/zim)")
    ap.add_argument("--out", default=OUT_DIR, help="where to put the dictionary (default ~/wikidict)")
    ap.add_argument("--name", help="dictionary name (default 'Wikipedia 100k')")
    ap.add_argument("--hours", type=int, default=24, help="hours of page views to sample (default 24)")
    ap.add_argument("--pageviews-dir", help="use already-downloaded hourly page-view .gz files from here")
    ap.add_argument("--titles", help="instead of page views: a text file of titles, most important first")
    ap.add_argument("--synonyms", type=int, default=4, help="other names per article, from redirects (default 4)")
    ap.add_argument("--no-links", action="store_true", help="plain text, no tappable links between entries")
    args = ap.parse_args()

    t_start = time.time()
    zim_path = find_zim(args.zim)
    say(f"wikidict {VERSION}: {args.articles:,} articles from {os.path.basename(zim_path)}")
    zim = Zim(zim_path)
    views = load_views(args)
    chosen = choose(zim, views, args.articles, args.synonyms)
    del views

    links = None
    if not args.no_links:                   # link targets: an entry's path -> its headword
        links = {}
        for key, title, _ in chosen:
            links[key.split("/")[-1]] = title

    say("Writing entries (the slow part; it shows progress)")
    entries, synonyms = [], []
    t0 = time.time()
    skipped = 0
    for i, (key, title, syns) in enumerate(chosen, 1):
        try:
            raw = bytes(zim.a.get_entry_by_path(key).get_item().content)
            body = opening(raw, links, args.length)
        except Exception:
            body = None
        if body is None:
            skipped += 1
        else:
            n = len(entries)
            entries.append((title, body))
            names = list(syns)
            plain = PAREN.sub("", title)
            if plain and plain != title:
                names.insert(0, plain)        # "Mercury (planet)" is found by "Mercury" too
            seen = {title.lower()}
            for s in names:
                if s.lower() not in seen:
                    seen.add(s.lower())
                    synonyms.append((s, n))
        if i % 5000 == 0 or i == len(chosen):
            rate = i / max(time.time() - t0, 0.001)
            left = (len(chosen) - i) / rate
            say(f"  {i:,}/{len(chosen):,}  ~{left / 60:.0f} min left")

    name = args.name or f"Wikipedia {short(args.articles)}"
    folder = os.path.join(args.out, name)
    desc = (f"Opening paragraphs of the {len(entries):,} most-read English Wikipedia articles, "
            f"from {os.path.basename(zim_path)}. Text CC BY-SA 4.0, Wikipedia contributors.")
    write_stardict(folder, name, entries, synonyms, desc)
    size = sum(os.path.getsize(os.path.join(folder, f)) for f in os.listdir(folder))
    say(f"\nDone in {(time.time() - t_start) / 60:.0f} min: {len(entries):,} entries, "
        f"{len(synonyms):,} other names, {size / 1e6:.0f} MB")
    say(f"({skipped:,} skipped: disambiguation or list pages with no opening text)")
    say(f"Dictionary folder: {folder}")
    say("Copy that whole folder into  koreader/data/dict/  on Cyby.")


if __name__ == "__main__":
    main()
