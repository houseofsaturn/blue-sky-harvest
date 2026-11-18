#!/usr/bin/env python3
"""
build_musicdb: turn the MusicBrainz dumps (+ two small Wikipedia tables) into one small
SQLite file, music.db, for the music conversations (connections.py / gleaner #listenings).

Heavy, one-off: run on exlomax. Nothing else depends on exlomax; the result is copied
to exlo and fatline. Python 3.10+ standard library only.

    py build_musicdb.py --dumps D:\\musicdb\\downloads --work D:\\musicdb\\work --out D:\\musicdb\\music.db

The dumps folder needs (names as downloaded):
    mbdump.tar.bz2                    MusicBrainz core (CC0)
    mbdump-derived.tar.bz2            MusicBrainz tags (CC BY-NC-SA 3.0: personal, non-commercial use)
    enwiki-latest-page.sql.gz         Wikipedia page ids -> titles
    enwiki-latest-page_props.sql.gz   Wikipedia page ids -> Wikidata ids (Q…)

Steps (each one is skipped if already done, so you can stop and run it again):
  1 unpack   only the MusicBrainz tables we need, into --work\\mbdump  (the slow part)
  2 wiki     which MusicBrainz artists have an English Wikipedia article
  3 artists  every artist, with type, years, area and Wikipedia title
  4 links    artist-to-artist relationships (member of band, collaboration, teacher, …)
  5 credits  performer credits on recordings and releases (who played what)
  6 albums   every credit traced to its album (MusicBrainz "release group", so reissues count once),
             plus the album's own artist credit (e.g. "Milford Graves & Don Pullen");
             various-artists compilations, DJ mixes and mixtapes are left out
  7 played   pairs of artists on the same albums (and the same tracks), with the earliest album as example
  8 tags     genres (MusicBrainz genre names only), instruments, and labels per artist
  8b label albums  which albums each label put out, per credited artist (for label discographies; 0.5)
  9 finish   copy the results into the small --out file, with indexes

What ends up in music.db:
  artist(id, mbid, name, sort_name, type, begin, end, area, wiki, qid)
  rel(a, b, kind, begin, end, detail)          a --kind--> b, e.g. Graves "member of band" NYAQ
  played(a, b, albums, tracks, example, year)  a < b; example = their earliest shared album
  instrument(artist, name, n)                  from performer credits (generic classes left out)
  genre(artist, name, votes)
  label(artist, name, n)                       labels of the artist's own albums, n = albums
  label_album(label, artist, album, year)      what a label released, per credited artist (0.5)
  meta(key, value)                             dump dates, counts, build time
"""
from __future__ import annotations

import argparse
import gzip
import os
import re
import shutil
import sqlite3
import sys
import tarfile
import threading
import time
from collections import Counter
from urllib.parse import unquote

VERSION = "0.5"

try:                                    # Windows consoles can choke on non-ASCII names
    sys.stdout.reconfigure(errors="replace")
    sys.stderr.reconfigure(errors="replace")
except Exception:
    pass

# ---------------------------------------------------------------- MusicBrainz tables we need
# column positions, from musicbrainz-server admin/sql/CreateTables.sql (checked 16 Nov 2026)
CORE = ["artist", "artist_type", "area", "link", "link_type", "link_attribute", "link_attribute_type",
        "l_artist_artist", "l_artist_recording", "l_artist_release", "l_artist_url", "url",
        "release", "genre", "track", "medium", "release_group",
        "release_group_secondary_type_join", "release_group_secondary_type", "artist_credit_name",
        "release_label", "label"]
DERIVED = ["artist_tag", "tag", "release_group_meta"]
COLS = {
    "artist": 19, "artist_type": 6, "area": 14, "link": 11, "link_type": 16, "link_attribute": 3,
    "link_attribute_type": 8, "l_artist_artist": 9, "l_artist_recording": 9, "l_artist_release": 9,
    "l_artist_url": 9, "url": 5, "recording": 9, "release": 14, "genre": 6, "artist_tag": 4, "tag": 3,
    "track": 12, "medium": 9, "release_group": 8, "release_group_secondary_type_join": 3,
    "release_group_secondary_type": 6, "artist_credit_name": 5, "release_label": 5, "label": 16,
    "release_group_meta": 7,
}

# artist <-> artist relationship types worth keeping (MusicBrainz link_type names)
REL_KINDS = {"member of band", "collaboration", "supporting musician", "instrumental supporting musician",
             "vocal supporting musician", "teacher", "subgroup", "conductor position", "founder",
             "artistic director", "tribute", "is person"}
# artist -> recording / release types that mean "performed on it"
PERF_KINDS = {"performer", "instrument", "vocal", "performing orchestra", "conductor"}
URL_KINDS = {"wikidata", "wikipedia"}
MAX_PERFORMERS = 12     # a recording with more credited performers (orchestras, choirs) makes no pairs
MAX_ALBUM = 20          # an album with more credited artists makes no pairs
SKIP_RG_TYPES = {"Compilation", "DJ-mix", "Mixtape/Street"}
VARIOUS_ARTISTS = "89ad4ac3-39f7-470e-963a-56509c546377"
# instrument *classes* rather than instruments (Hornbostel–Sachs and family names)
GENERIC_INSTR = re.compile(r"^(membrano|idio|chordo|aero|electro|lamello|metallo)phones?$|\binstruments?$|"
                           r"^(plucked|bowed|struck|rubbed|blown|free reed|lip[- ]reed|edge[- ]blown)\b|"
                           r"^(strings|woodwind|brass|keyboard|percussion family|other instruments?)$", re.I)


LOGFILE = None
MIN_FREE_GB = 3.0       # stop before the machine runs short of memory


def log(msg: str) -> None:
    line = f"{time.strftime('%H:%M:%S')} {msg}"
    print(line, flush=True)
    if LOGFILE:
        with open(LOGFILE, "a", encoding="utf-8") as fh:
            fh.write(line + "\n")


def free_memory_gb():
    """available physical memory in GB (Windows or Linux), or None if unknown"""
    try:
        if os.name == "nt":
            import ctypes

            class MS(ctypes.Structure):
                _fields_ = [("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong),
                            ("ullTotalPhys", ctypes.c_ulonglong), ("ullAvailPhys", ctypes.c_ulonglong),
                            ("ullTotalPageFile", ctypes.c_ulonglong), ("ullAvailPageFile", ctypes.c_ulonglong),
                            ("ullTotalVirtual", ctypes.c_ulonglong), ("ullAvailVirtual", ctypes.c_ulonglong),
                            ("ullAvailExtendedVirtual", ctypes.c_ulonglong)]
            m = MS()
            m.dwLength = ctypes.sizeof(MS)
            ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(m))
            return m.ullAvailPhys / 1e9
        with open("/proc/meminfo") as fh:
            for line in fh:
                if line.startswith("MemAvailable:"):
                    return int(line.split()[1]) / 1e6
    except Exception:
        return None
    return None


def watchdog():
    """runs in the background: stops the build before the machine starts to freeze"""
    low = 0
    while True:
        time.sleep(5)
        free = free_memory_gb()
        if free is None:
            return
        low = low + 1 if free < MIN_FREE_GB else 0
        if low >= 2:
            log(f"🛑 stopping: only {free:.1f} GB of memory left. Nothing is lost: run the same command again "
                f"to carry on, and tell Claude which step this was.")
            os._exit(3)


def be_gentle():
    """lower this process's priority so the desktop and SSH stay responsive"""
    try:
        if os.name == "nt":
            import ctypes
            ctypes.windll.kernel32.SetPriorityClass(ctypes.windll.kernel32.GetCurrentProcess(), 0x4000)  # below normal
        else:
            os.nice(10)
    except Exception:
        pass


def unescape(f: str):
    """PostgreSQL COPY text format: \\N is NULL; backslash escapes."""
    if f == "\\N":
        return None
    if "\\" not in f:
        return f
    return re.sub(r"\\(.)", lambda m: {"t": "\t", "n": "\n", "r": "\r", "\\": "\\"}.get(m.group(1), m.group(1)), f)


def rows(work: str, table: str):
    path = os.path.join(work, "mbdump", table)
    n = COLS[table]
    size = os.path.getsize(path)
    big = size > 300e6
    t0 = time.time()
    with open(path, encoding="utf-8", newline="\n") as fh:
        for k, line in enumerate(fh, 1):
            if big and k % 5_000_000 == 0:
                free = free_memory_gb()
                log(f"      {table}: {k:,} rows ({time.time() - t0:,.0f} s"
                    + (f", {free:.1f} GB memory free)" if free is not None else ")"))
            parts = line.rstrip("\n").split("\t")
            if len(parts) < n:          # extra columns at the end (newer schema) are fine
                raise SystemExit(f"❌ {table}: expected {n} columns, got {len(parts)}. The MusicBrainz "
                                 f"schema may have changed; tell Claude.\n   first bad line: {line[:200]!r}")
            yield [unescape(p) for p in parts]


def as_int(v):
    return int(v) if v not in (None, "") else None


# ================================================================ 1 unpack
def step_unpack(dumps: str, work: str) -> None:
    out = os.path.join(work, "mbdump")
    os.makedirs(out, exist_ok=True)
    for archive, tables in (("mbdump.tar.bz2", CORE), ("mbdump-derived.tar.bz2", DERIVED)):
        want = {t for t in tables if not os.path.exists(os.path.join(out, t))}
        if not want:
            log(f"1 unpack: {archive} already done")
            continue
        path = os.path.join(dumps, archive)
        if not os.path.exists(path):
            raise SystemExit(f"❌ missing {path}")
        log(f"1 unpack: reading {archive} ({os.path.getsize(path) / 1e9:.1f} GB) for {', '.join(sorted(want))}. "
            f"The whole file has to be decompressed even for the tables we skip.")
        t0 = time.time()
        got = set()
        with tarfile.open(path, mode="r|bz2") as tar:
            for m in tar:
                name = m.name.split("/")[-1]
                if m.name.startswith("mbdump/") and name in want and m.isfile():
                    src = tar.extractfile(m)
                    part = os.path.join(out, name + ".part")
                    with open(part, "wb") as dst:
                        shutil.copyfileobj(src, dst, 16 << 20)
                    os.replace(part, os.path.join(out, name))
                    got.add(name)
                    log(f"   {name}: {m.size / 1e6:,.0f} MB  ({time.time() - t0:,.0f} s so far)")
                elif m.isfile() and m.size > 1e9:
                    log(f"   (skipping {name}: {m.size / 1e9:,.1f} GB, {time.time() - t0:,.0f} s so far)")
                elif m.name.startswith(("TIMESTAMP", "SCHEMA_SEQUENCE", "REPLICATION_SEQUENCE")) and m.isfile():
                    data = tar.extractfile(m).read().decode("utf-8", "replace").strip()
                    with open(os.path.join(out, m.name), "w", encoding="utf-8") as fh:
                        fh.write(data)
        missing = want - got
        if missing:
            raise SystemExit(f"❌ {archive} has no {', '.join(sorted(missing))}. Is the download complete?")
        log(f"1 unpack: {archive} done in {(time.time() - t0) / 60:,.1f} min")


# ================================================================ helpers for the work database
def db(path: str) -> sqlite3.Connection:
    con = sqlite3.connect(path)
    con.execute("PRAGMA journal_mode=OFF")
    con.execute("PRAGMA synchronous=OFF")
    con.execute("PRAGMA temp_store=FILE")
    con.execute("PRAGMA cache_size=-512000")        # ~512 MB page cache (also bounds SQLite's sorting memory)
    con.execute("CREATE TABLE IF NOT EXISTS step(name TEXT PRIMARY KEY, at TEXT)")
    return con


def done(con, name) -> bool:
    return con.execute("SELECT 1 FROM step WHERE name=?", (name,)).fetchone() is not None


def mark(con, name) -> None:
    con.execute("INSERT OR REPLACE INTO step VALUES (?, ?)", (name, time.strftime("%Y-%m-%d %H:%M")))
    con.commit()


def lookups(work: str) -> dict:
    """the small tables, kept in memory: link types, attribute types, artist types, areas, genres"""
    lt = {}
    for r in rows(work, "link_type"):
        lt[int(r[0])] = (r[6], r[4], r[5])                 # name, entity_type0, entity_type1
    at = {}
    for r in rows(work, "link_attribute_type"):
        at[int(r[0])] = (r[5], as_int(r[2]))               # name, root id
    instr_root = {i for i, (n, _) in at.items() if n in ("instrument", "vocal")}
    instruments = {i: n for i, (n, root) in at.items()
                   if root in instr_root and i not in instr_root and not GENERIC_INSTR.search(n)}
    return {
        "link_type": lt,
        "instruments": instruments,
        "artist_type": {int(r[0]): r[1] for r in rows(work, "artist_type")},
        "area": {int(r[0]): r[2] for r in rows(work, "area")},
        "genre": {r[2].lower() for r in rows(work, "genre")},
    }


def wanted_links(work: str, L: dict) -> dict:
    """link id -> (kind, begin year, end year) for the link types we keep"""
    keep = {}
    for i, (name, e0, e1) in L["link_type"].items():
        if e0 == "artist" and e1 == "artist" and name in REL_KINDS:
            keep[i] = name
        elif e0 == "artist" and e1 in ("recording", "release") and name in PERF_KINDS:
            keep[i] = name
        elif e0 == "artist" and e1 == "url" and name in URL_KINDS:
            keep[i] = name
    out = {}
    for r in rows(work, "link"):
        k = keep.get(int(r[1]))
        if k:
            out[int(r[0])] = (k, as_int(r[2]), as_int(r[5]))
    return out


# ================================================================ 2 wiki
SQL_PAGE = re.compile(r"\((\d+),(-?\d+),'((?:[^'\\]|\\.)*)'")
SQL_PROP = re.compile(r"\((\d+),'wikibase_item','(Q\d+)'")


def sql_lines(path: str):
    """every line that can hold rows: the dumps put either many rows after "INSERT INTO … VALUES" on one
    line, or the header alone with one row per following line (seen in the Nov 2026 enwiki dumps)"""
    with gzip.open(path, "rt", encoding="utf-8", errors="replace") as fh:
        for line in fh:
            if line.startswith(("--", "/*", "LOCK", "UNLOCK", "DROP", "CREATE", ")", "  `", "  KEY", "  PRIMARY")):
                continue
            yield line


def sql_unescape(s: str) -> str:
    return re.sub(r"\\(.)", lambda m: m.group(1), s)


def step_wiki(con, dumps: str, work: str, L: dict, links: dict) -> None:
    if done(con, "wiki"):
        log("2 wiki: already done")
        return
    log("2 wiki: which artists link to Wikidata or English Wikipedia")
    urls = {}
    for r in rows(work, "url"):
        u = r[2]
        if "wikidata.org/wiki/Q" in u or "en.wikipedia.org/wiki/" in u:
            urls[int(r[0])] = u
    qid, enwiki = {}, {}
    for r in rows(work, "l_artist_url"):
        k = links.get(int(r[1]))
        u = urls.get(int(r[3]))
        if not k or not u:
            continue
        a = int(r[2])
        m = re.search(r"wikidata\.org/wiki/(Q\d+)", u)
        if m:
            qid.setdefault(a, m.group(1))
        m = re.search(r"en\.wikipedia\.org/wiki/([^?#]+)", u)
        if m:
            enwiki.setdefault(a, unquote(m.group(1)).replace(" ", "_"))
    log(f"   {len(qid):,} artists with a Wikidata id, {len(enwiki):,} with a direct English Wikipedia link")

    want_q = set(qid.values())
    q_page = {}
    t0 = time.time()
    for line in sql_lines(os.path.join(dumps, "enwiki-latest-page_props.sql.gz")):
        for m in SQL_PROP.finditer(line):
            if m.group(2) in want_q:
                q_page[m.group(2)] = int(m.group(1))
    log(f"   page_props: {len(q_page):,} of those Wikidata ids have an English article ({time.time() - t0:,.0f} s)")
    want_pages = set(q_page.values())
    page_title = {}
    t0 = time.time()
    for line in sql_lines(os.path.join(dumps, "enwiki-latest-page.sql.gz")):
        for m in SQL_PAGE.finditer(line):
            pid = int(m.group(1))
            if pid in want_pages and m.group(2) == "0":
                page_title[pid] = sql_unescape(m.group(3))
    log(f"   page: {len(page_title):,} titles ({time.time() - t0:,.0f} s)")

    con.execute("CREATE TABLE wiki(artist INTEGER PRIMARY KEY, qid TEXT, wiki TEXT)")
    data = []
    for a in set(qid) | set(enwiki):
        q = qid.get(a)
        title = page_title.get(q_page.get(q)) if q else None
        data.append((a, q, title or enwiki.get(a)))
    con.executemany("INSERT INTO wiki VALUES (?,?,?)", data)
    mark(con, "wiki")
    log(f"   {sum(1 for d in data if d[2]):,} artists matched to an English Wikipedia article")


# ================================================================ 3 artists
def step_artists(con, work: str, L: dict) -> None:
    if done(con, "artists"):
        log("3 artists: already done")
        return
    log("3 artists")
    con.execute("CREATE TABLE artist(id INTEGER PRIMARY KEY, mbid TEXT, name TEXT, sort_name TEXT, type TEXT, "
                "begin INTEGER, end INTEGER, area TEXT, wiki TEXT, qid TEXT)")
    wiki = {a: (q, w) for a, q, w in con.execute("SELECT artist, qid, wiki FROM wiki")}
    batch = []
    for r in rows(work, "artist"):
        a = int(r[0])
        q, w = wiki.get(a, (None, None))
        batch.append((a, r[1], r[2], r[3], L["artist_type"].get(as_int(r[10])), as_int(r[4]), as_int(r[7]),
                      L["area"].get(as_int(r[11])), w, q))
        if len(batch) >= 200_000:
            con.executemany("INSERT INTO artist VALUES (?,?,?,?,?,?,?,?,?,?)", batch)
            batch.clear()
    con.executemany("INSERT INTO artist VALUES (?,?,?,?,?,?,?,?,?,?)", batch)
    mark(con, "artists")
    log(f"   {con.execute('SELECT count(*) FROM artist').fetchone()[0]:,} artists")


def attrs_for(work: str, link_ids: set, L: dict) -> dict:
    """link id -> [instrument names] for the given links"""
    out = {}
    for r in rows(work, "link_attribute"):
        lid = int(r[0])
        if lid in link_ids:
            name = L["instruments"].get(int(r[1]))
            if name:
                out.setdefault(lid, []).append(name)
    return out


# ================================================================ 4 links
def step_links(con, work: str, L: dict, links: dict) -> None:
    if done(con, "links"):
        log("4 links: already done")
        return
    log("4 links: artist-to-artist relationships")
    con.execute("CREATE TABLE rel(a INTEGER, b INTEGER, kind TEXT, begin INTEGER, end INTEGER, detail TEXT)")
    data, used = [], set()
    for r in rows(work, "l_artist_artist"):
        lid = int(r[1])
        k = links.get(lid)
        if k and k[0] in REL_KINDS:
            data.append([int(r[2]), int(r[3]), k[0], k[1], k[2], lid])
            used.add(lid)
    at = attrs_for(work, used, L)
    for d in data:
        d[5] = ", ".join(sorted(set(at.get(d[5], [])))) or None
    con.executemany("INSERT INTO rel VALUES (?,?,?,?,?,?)", data)
    mark(con, "links")
    log(f"   {len(data):,} relationships: " + ", ".join(f"{k} {n:,}" for k, n in Counter(d[2] for d in data).most_common()))


# ================================================================ 5 credits
def step_credits(con, work: str, L: dict, links: dict) -> None:
    if done(con, "credits"):
        log("5 credits: already done")
        return
    log("5 credits: performer credits on recordings and releases")
    con.execute("CREATE TABLE perf(kind INTEGER, item INTEGER, artist INTEGER, link INTEGER)")   # kind 0 rec, 1 rel
    used = set()
    for kind, table in ((0, "l_artist_recording"), (1, "l_artist_release")):
        batch, n = [], 0
        for r in rows(work, table):
            lid = int(r[1])
            k = links.get(lid)
            if k and k[0] in PERF_KINDS:
                batch.append((kind, int(r[3]), int(r[2]), lid))
                used.add(lid)
                n += 1
                if len(batch) >= 500_000:
                    con.executemany("INSERT INTO perf VALUES (?,?,?,?)", batch)
                    batch.clear()
        con.executemany("INSERT INTO perf VALUES (?,?,?,?)", batch)
        log(f"   {table}: {n:,} performer credits")
    log("   instruments")
    at = attrs_for(work, used, L)
    con.execute("CREATE TABLE link_instr(link INTEGER, name TEXT)")
    con.executemany("INSERT INTO link_instr VALUES (?,?)", ((lid, n) for lid, ns in at.items() for n in set(ns)))
    mark(con, "credits")


# ================================================================ 6 albums
def step_albums(con, work: str) -> None:
    if done(con, "albums"):
        log("6 albums: already done")
        return
    log("6 albums: tracing credits to albums")
    t0 = time.time()
    skip_types = {int(r[0]) for r in rows(work, "release_group_secondary_type") if r[1] in SKIP_RG_TYPES}
    skip_rg = {int(r[0]) for r in rows(work, "release_group_secondary_type_join") if int(r[1]) in skip_types}
    log(f"   {len(skip_rg):,} compilations / DJ mixes / mixtapes left out")
    years = {}
    for r in rows(work, "release_group_meta"):
        if r[2]:
            years[int(r[0])] = int(r[2])
    con.execute("CREATE TABLE rg(id INTEGER PRIMARY KEY, name TEXT, ac INTEGER, year INTEGER)")
    batch = []
    for r in rows(work, "release_group"):
        i = int(r[0])
        if i not in skip_rg:
            batch.append((i, r[2], int(r[3]), years.get(i)))
    con.executemany("INSERT INTO rg VALUES (?,?,?,?)", batch)
    del batch, years
    con.execute("CREATE TABLE release_rg(id INTEGER PRIMARY KEY, rg INTEGER)")
    con.executemany("INSERT INTO release_rg VALUES (?,?)", ((int(r[0]), int(r[4])) for r in rows(work, "release")))
    con.execute("CREATE TABLE med(id INTEGER PRIMARY KEY, rel INTEGER)")
    con.executemany("INSERT INTO med VALUES (?,?)", ((int(r[0]), int(r[1])) for r in rows(work, "medium")))
    need = {r[0] for r in con.execute("SELECT DISTINCT item FROM perf WHERE kind=0")}
    con.execute("CREATE TABLE trk(rec INTEGER, med INTEGER)")
    con.executemany("INSERT INTO trk VALUES (?,?)",
                    ((int(r[2]), int(r[3])) for r in rows(work, "track") if int(r[2]) in need))
    del need
    con.execute("CREATE TABLE acn(ac INTEGER, artist INTEGER)")
    con.executemany("INSERT INTO acn VALUES (?,?)", ((int(r[0]), int(r[2])) for r in rows(work, "artist_credit_name")))
    va = con.execute("SELECT id FROM artist WHERE mbid=?", (VARIOUS_ARTISTS,)).fetchone()
    va = va[0] if va else -1
    for what, sql in (
        ("indexes", "CREATE INDEX trk_rec ON trk(rec)"),
        ("", "CREATE INDEX acn_ac ON acn(ac)"),
        ("credits → albums",
         f"""CREATE TABLE album_artist AS SELECT DISTINCT rg, artist FROM (
               SELECT r.rg, p.artist FROM perf p JOIN trk t ON t.rec=p.item JOIN med m ON m.id=t.med
                      JOIN release_rg r ON r.id=m.rel WHERE p.kind=0
               UNION ALL
               SELECT r.rg, p.artist FROM perf p JOIN release_rg r ON r.id=p.item WHERE p.kind=1
               UNION ALL
               SELECT g.id, a.artist FROM rg g JOIN acn a ON a.ac=g.ac
             ) WHERE rg IN (SELECT id FROM rg) AND artist != {va}"""),
        ("", "CREATE INDEX album_artist_rg ON album_artist(rg)"),
    ):
        if what:
            log(f"   {what}…")
        con.execute(sql)
        con.commit()
    n = con.execute("SELECT count(*) FROM album_artist").fetchone()[0]
    mark(con, "albums")
    log(f"   {n:,} artist-album credits ({time.time() - t0:,.0f} s)")


# ================================================================ 7 played
def step_played(con, work: str) -> None:
    if done(con, "played"):
        log("7 played: already done")
        return
    log("7 played: who was on the same albums and tracks")
    t0 = time.time()
    for what, sql in (
        ("one row per artist per track",
         "CREATE TABLE IF NOT EXISTS p1 AS SELECT DISTINCT item, artist FROM perf WHERE kind=0"),
        ("index", "CREATE INDEX IF NOT EXISTS p1_item ON p1(item)"),
        ("tracks with 2–12 performers",
         f"CREATE TABLE IF NOT EXISTS psize AS SELECT item FROM p1 GROUP BY item "
         f"HAVING count(*) BETWEEN 2 AND {MAX_PERFORMERS}"),
        ("track pairs",
         "CREATE TABLE IF NOT EXISTS tpairs AS SELECT x.artist a, y.artist b, count(*) n "
         "FROM psize s JOIN p1 x ON x.item=s.item JOIN p1 y ON y.item=x.item AND x.artist < y.artist "
         "GROUP BY x.artist, y.artist"),
        ("albums with 2–20 artists",
         f"CREATE TABLE IF NOT EXISTS asize AS SELECT rg FROM album_artist GROUP BY rg "
         f"HAVING count(*) BETWEEN 2 AND {MAX_ALBUM}"),
        ("album pairs (the big one)",
         "CREATE TABLE IF NOT EXISTS apairs AS "
         "SELECT x.artist a, y.artist b, count(*) n, min(coalesce(g.year, 9999) * 100000000 + g.id) ex "
         "FROM asize s JOIN album_artist x ON x.rg=s.rg JOIN album_artist y ON y.rg=x.rg AND x.artist < y.artist "
         "JOIN rg g ON g.id=x.rg GROUP BY x.artist, y.artist"),
        ("merging",
         "CREATE TABLE IF NOT EXISTS played AS "
         "SELECT a, b, sum(albums) albums, sum(tracks) tracks, max(ex) ex FROM ("
         "  SELECT a, b, n albums, 0 tracks, ex FROM apairs UNION ALL SELECT a, b, 0, n, NULL FROM tpairs"
         ") GROUP BY a, b"),
    ):
        log(f"   {what}…")
        con.execute(sql)
        con.commit()
        log(f"   … done ({time.time() - t0:,.0f} s)")
    con.executescript("""
        CREATE TABLE played2 AS
            SELECT p.a, p.b, p.albums, p.tracks, g.name example, g.year year
            FROM played p LEFT JOIN rg g ON g.id = p.ex % 100000000;
        DROP TABLE played; ALTER TABLE played2 RENAME TO played;
        DROP TABLE p1; DROP TABLE psize; DROP TABLE tpairs; DROP TABLE asize; DROP TABLE apairs;
    """)
    mark(con, "played")
    n = con.execute("SELECT count(*) FROM played").fetchone()[0]
    log(f"   {n:,} artist pairs played together ({time.time() - t0:,.0f} s)")


# ================================================================ 8 tags
def step_tags(con, work: str, L: dict) -> None:
    if done(con, "tags"):
        log("8 tags: already done")
        return
    log("8 tags: instruments, genres and labels")
    con.executescript("""
        CREATE TABLE instrument AS
            SELECT p.artist, li.name, count(DISTINCT p.kind || ':' || p.item) n
            FROM perf p JOIN link_instr li ON li.link = p.link GROUP BY p.artist, li.name;
    """)
    genre_tags = {int(r[0]): r[1] for r in rows(work, "tag") if r[1] and r[1].lower() in L["genre"]}
    con.execute("CREATE TABLE genre(artist INTEGER, name TEXT, votes INTEGER)")
    batch = []
    for r in rows(work, "artist_tag"):
        g = genre_tags.get(int(r[1]))
        if g and int(r[2]) > 0:
            batch.append((int(r[0]), g, int(r[2])))
    con.executemany("INSERT INTO genre VALUES (?,?,?)", batch)
    con.execute("CREATE TABLE lab(id INTEGER PRIMARY KEY, name TEXT)")
    con.executemany("INSERT INTO lab VALUES (?,?)", ((int(r[0]), r[2]) for r in rows(work, "label")))
    con.execute("CREATE TABLE rlab(rel INTEGER, label INTEGER)")
    con.executemany("INSERT INTO rlab VALUES (?,?)", ((int(r[1]), int(r[2])) for r in rows(work, "release_label") if r[2]))
    con.executescript("""
        CREATE INDEX release_rg_rg ON release_rg(rg);
        CREATE TABLE label AS
            SELECT a.artist, l.name, count(DISTINCT g.id) n
            FROM rg g JOIN acn a ON a.ac=g.ac JOIN release_rg r ON r.rg=g.id JOIN rlab x ON x.rel=r.id JOIN lab l ON l.id=x.label
            WHERE l.name NOT LIKE '[%'
            GROUP BY a.artist, l.name;
    """)
    mark(con, "tags")
    log(f"   {con.execute('SELECT count(*) FROM instrument').fetchone()[0]:,} artist instruments, {len(batch):,} artist genres, "
        f"{con.execute('SELECT count(*) FROM label').fetchone()[0]:,} artist labels")


# ================================================================ 8b albums on each label (for label discographies)
def step_label_albums(con) -> None:
    if done(con, "label_albums"):
        log("8b label albums: already done")
        return
    log("8b label albums: which albums each label put out, per credited artist")
    con.executescript("""
        DROP TABLE IF EXISTS label_album;
        CREATE TABLE label_album AS
            SELECT DISTINCT l.name label, a.artist, g.name album, g.year
            FROM rg g JOIN acn a ON a.ac=g.ac JOIN release_rg r ON r.rg=g.id
                 JOIN rlab x ON x.rel=r.id JOIN lab l ON l.id=x.label
            WHERE l.name NOT LIKE '[%';
    """)
    mark(con, "label_albums")
    log(f"   {con.execute('SELECT count(*) FROM label_album').fetchone()[0]:,} label albums")


# ================================================================ 9 finish
def step_finish(con, work: str, out: str, dumps: str) -> None:
    log(f"9 finish: writing {out}")
    if os.path.exists(out):
        os.remove(out)
    con.execute("ATTACH ? AS o", (out,))
    stamp = ""
    p = os.path.join(work, "mbdump", "TIMESTAMP")
    if os.path.exists(p):
        stamp = open(p, encoding="utf-8").read().strip()
    con.executescript(f"""
        CREATE TABLE o.artist AS SELECT * FROM artist;
        CREATE TABLE o.rel AS SELECT * FROM rel;
        CREATE TABLE o.played AS SELECT * FROM played;
        CREATE TABLE o.instrument AS SELECT * FROM instrument WHERE n > 0;
        CREATE TABLE o.genre AS SELECT * FROM genre;
        CREATE TABLE o.label AS SELECT * FROM label;
        CREATE TABLE o.label_album AS SELECT * FROM label_album;
        CREATE INDEX o.label_a ON label(artist);
        CREATE INDEX o.label_n ON label(name COLLATE NOCASE);
        CREATE INDEX o.label_album_l ON label_album(label COLLATE NOCASE, artist);
        CREATE INDEX o.artist_name ON artist(name COLLATE NOCASE);
        CREATE INDEX o.artist_wiki ON artist(wiki);
        CREATE INDEX o.rel_a ON rel(a);
        CREATE INDEX o.rel_b ON rel(b);
        CREATE INDEX o.played_a ON played(a);
        CREATE INDEX o.played_b ON played(b);
        CREATE INDEX o.instrument_a ON instrument(artist);
        CREATE INDEX o.genre_a ON genre(artist);
        CREATE TABLE o.meta(key TEXT PRIMARY KEY, value TEXT);
    """)
    meta = {"version": VERSION, "built": time.strftime("%Y-%m-%d %H:%M"), "musicbrainz_dump": stamp,
            "licence": "MusicBrainz core data CC0; genre tags CC BY-NC-SA 3.0 (personal use); Wikipedia titles CC BY-SA"}
    for t in ("artist", "rel", "played", "instrument", "genre", "label", "label_album"):
        meta[f"rows_{t}"] = str(con.execute(f"SELECT count(*) FROM o.{t}").fetchone()[0])
    con.executemany("INSERT INTO o.meta VALUES (?,?)", meta.items())
    con.commit()
    con.execute("DETACH o")
    o = sqlite3.connect(out)
    o.execute("VACUUM")
    o.close()
    log(f"   done: {os.path.getsize(out) / 1e6:,.0f} MB")
    for k, v in meta.items():
        if k.startswith("rows_"):
            log(f"   {k[5:]}: {int(v):,}")


def main():
    ap = argparse.ArgumentParser(description="Build music.db from MusicBrainz + Wikipedia dumps.")
    ap.add_argument("--dumps", required=True, help="folder with the four downloads")
    ap.add_argument("--work", help="folder for unpacked tables and the work database (default: next to --dumps)")
    ap.add_argument("--out", help="the result (default: music.db next to --dumps)")
    ap.add_argument("--redo", action="store_true", help="start the database steps (2-9) again; keeps the unpacked tables")
    a = ap.parse_args()
    parent = os.path.dirname(os.path.abspath(a.dumps))
    work = a.work or os.path.join(parent, "work")
    out = a.out or os.path.join(parent, "music.db")
    os.makedirs(work, exist_ok=True)
    for v in ("TMP", "TEMP", "SQLITE_TMPDIR"):        # SQLite's scratch files on the big drive, not C:
        os.environ[v] = work
    for f in ("enwiki-latest-page.sql.gz", "enwiki-latest-page_props.sql.gz"):
        if not os.path.exists(os.path.join(a.dumps, f)):
            raise SystemExit(f"❌ missing {os.path.join(a.dumps, f)}")
    global LOGFILE
    LOGFILE = os.path.join(work, "build.log")
    be_gentle()
    threading.Thread(target=watchdog, daemon=True).start()
    log(f"build_musicdb {VERSION}: dumps {a.dumps}  work {work}  out {out}  (log: {LOGFILE})")
    free = free_memory_gb()
    if free is not None:
        log(f"   {free:.1f} GB memory free; will stop itself below {MIN_FREE_GB:.0f} GB")
    t0 = time.time()
    step_unpack(a.dumps, work)
    wpath = os.path.join(work, "work.db")
    if a.redo and os.path.exists(wpath):
        os.remove(wpath)
    con = db(wpath)
    log("   reading link types, instruments, areas, genres…")
    L = lookups(work)
    log("   reading links (one big table)…")
    links = wanted_links(work, L)
    log(f"   {len(links):,} links of the kinds we keep")
    step_wiki(con, a.dumps, work, L, links)
    step_artists(con, work, L)
    step_links(con, work, L, links)
    step_credits(con, work, L, links)
    step_albums(con, work)
    step_played(con, work)
    step_tags(con, work, L)
    step_label_albums(con)
    step_finish(con, work, out, a.dumps)
    log(f"✅ all done in {(time.time() - t0) / 60:,.1f} min. Try:  py musicdb.py \"Milford Graves\" --db {out}")


if __name__ == "__main__":
    main()
