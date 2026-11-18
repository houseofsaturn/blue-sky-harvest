#!/usr/bin/env python3
"""
Checks for tools/connections.py against the made-up music archive.

    python3 tests/test_connections.py            (builds /tmp/music_test.zim first)
    python3 tests/test_connections.py some.zim   (also runs every article of a real archive, to catch crashes)
"""
import os
import re
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path[:0] = [os.path.dirname(HERE), HERE]
import connections as C                     # noqa: E402
import make_music_test_zim as M             # noqa: E402

ZIM = "/tmp/music_test.zim"
M.main(ZIM)
w = C.Wiki(ZIM)

seed = C.Article(w, w.find("Orrin Vale"))
assert seed.kind() == "musician", seed.kind()
ranked = C.connections(w, seed, progress=False)
by = {r["title"]: r for r in ranked}
kinds = {t: r["kind"] for t, r in by.items()}

assert ranked[0]["title"] == "Lena Marsh", ranked[0]["title"]
assert by["Lena Marsh"]["back"] and by["Lena Marsh"]["infobox"]
assert "best known" in C.reason(by["Lena Marsh"]), C.reason(by["Lena Marsh"])
assert kinds["The Hollow Quartet"] == "musician"
assert kinds["Tom Ide"] == "musician" and by["Tom Ide"]["mentions"]
assert kinds["Night Choir"] == "record"
assert kinds["Kestrel Disk"] == "label"
assert kinds["Free jazz"] == "scene"
assert kinds["Harrow Bend"] == "place"
for absent in ("Drum kit", "Rook Abernathy", "1964", "Jazz Weekly"):      # See also, navbox, a year, a reference
    assert absent not in by, absent
assert w.find("Orrin Vale (drummer)").path == "Orrin_Vale"                  # redirects followed
assert w.find("orrin val") is not None                                       # suggestion search
assert w.find("Nobody At All Here") is None or True                          # never crashes
facts = {l: t for l, t, _ in seed.infobox_rows}
assert facts["Instruments"] == "Drums, percussion", facts["Instruments"]
assert facts["Genres"] == "Free jazz, avant-garde jazz", facts["Genres"]
assert facts["Born"] == "3 May 1938 · Harrow Bend", facts["Born"]
assert C.split_sentences("(A had B.) In 1977, C did D.") == ["(A had B.)", "In 1977, C did D."]
assert C.split_sentences("Pieces of Time (Soul Note, rel. 1983).") == ["Pieces of Time (Soul Note, rel. 1983)."]
print("✅ music test archive: ranking and kinds as expected")

# ---- with a tiny music.db (made-up MusicBrainz data for the same made-up musicians)
import sqlite3                              # noqa: E402
MDB = "/tmp/music_test.db"
if os.path.exists(MDB):
    os.remove(MDB)
con = sqlite3.connect(MDB)
con.executescript("""
    CREATE TABLE artist(id INTEGER PRIMARY KEY, mbid TEXT, name TEXT, sort_name TEXT, type TEXT, begin INTEGER,
                        end INTEGER, area TEXT, wiki TEXT, qid TEXT);
    CREATE TABLE rel(a INTEGER, b INTEGER, kind TEXT, begin INTEGER, end INTEGER, detail TEXT);
    CREATE TABLE played(a INTEGER, b INTEGER, albums INTEGER, tracks INTEGER, example TEXT, year INTEGER);
    CREATE TABLE meta(key TEXT PRIMARY KEY, value TEXT);
    INSERT INTO meta VALUES ('musicbrainz_dump', '2026-11-14 00:22:30');
    INSERT INTO artist VALUES (1,'m1','Orrin Vale','','Person',1938,2019,'','Orrin_Vale',NULL),
        (2,'m2','Lena Marsh','','Person',NULL,NULL,'','Lena_Marsh',NULL),
        (3,'m3','Tom Ide','','Person',NULL,NULL,'','Tom_Ide',NULL),
        (4,'m4','The Hollow Quartet','','Group',1964,1972,'','The_Hollow_Quartet',NULL),
        (5,'m5','Rook Abernathy','','Person',NULL,NULL,'','Rook_Abernathy',NULL),
        (6,'m6','Silas Crane','','Person',NULL,NULL,'',NULL,NULL),
        (7,'m7','Orrin Vale','','Person',NULL,NULL,'',NULL,NULL);
    INSERT INTO artist VALUES (8,'m8','Pale Harbour','','Group',NULL,NULL,'','Pale_Harbour',NULL),
        (9,'m9','Dov Ketch','','Person',NULL,NULL,'',NULL,NULL),
        (10,'m10','Hush','','Group',NULL,NULL,'','Hush_(band)',NULL),
        (11,'m11','Hush','','Group',NULL,NULL,'','Hush_(UK_band)',NULL);
    CREATE TABLE label(artist INTEGER, name TEXT, n INTEGER);
    CREATE TABLE label_album(label TEXT, artist INTEGER, album TEXT, year INTEGER);
    INSERT INTO label VALUES (1,'Kestrel Disk',2),(2,'Kestrel Disk',1),(8,'Kestrel Disk',1),(9,'Kestrel Disk',2);
    INSERT INTO label_album VALUES ('Kestrel Disk',1,'Night Choir',1967),('Kestrel Disk',1,'Stone Hours',1970),
        ('Kestrel Disk',2,'Night Choir',1967),('Kestrel Disk',8,'Soft Engines',1969),
        ('Kestrel Disk',9,'Ninth Room',1974),('Kestrel Disk',9,'Glass Weather',1972);
    INSERT INTO rel VALUES (1,4,'member of band',1964,1972,'drums'), (3,1,'teacher',NULL,NULL,NULL);
    INSERT INTO played VALUES (1,2,2,4,'Night Choir',1967), (1,5,1,0,'Grey Lanterns',1971),
        (1,6,1,3,'Night Choir',1967), (3,7,0,1,NULL,NULL),
        (11,300,1,1,NULL,NULL);
""")
con.executemany("INSERT INTO played VALUES (10,?,1,1,NULL,NULL)", [(400 + k,) for k in range(25)])
con.commit()
con.close()
mb = C.MusicDB(MDB)
assert mb.artist_for(seed) == 1                                            # by Wikipedia title, not the namesake
ranked2 = C.connections(w, seed, progress=False, mb=mb)
by2 = {r["title"]: r for r in ranked2}
assert ranked2[0]["title"] == "Lena Marsh", ranked2[0]["title"]
assert C.mb_text(by2["Lena Marsh"]["mb"]) == "MusicBrainz: 2 albums together, first Night Choir (1967)"
assert "Rook Abernathy" in by2 and by2["Rook Abernathy"]["kind"] == "musician"   # only via MusicBrainz
assert by2["Silas Crane"].get("offwiki") and by2["Silas Crane"]["kind"] == "musician"
assert C.mb_text(by2["Tom Ide"]["mb"]) == "MusicBrainz: teacher", C.mb_text(by2["Tom Ide"]["mb"])
assert C.mb_text(by2["The Hollow Quartet"]["mb"]) == "MusicBrainz: member of (1964–1972)"
assert all(0 <= r["score"] <= 1.0 for r in ranked2), max(r["score"] for r in ranked2)
for absent in ("Drum kit", "1964", "Jazz Weekly"):
    assert absent not in by2, absent
assert by2["Lena Marsh"]["score"] > by2["Silas Crane"]["score"]        # Wikipedia + MusicBrainz beats MusicBrainz alone
print("✅ with music.db: MusicBrainz evidence merged, new musicians added, scores 0–1")

# ---- what kind of page a name is, and which page a name means
assert w.exact("hush").title == "Hush"                                        # "nirvana" -> "Nirvana", no title-search guess
assert w.exact("orrin vale").path == "Orrin_Vale"
assert C.Article(w, w.find("Hush (disambiguation)")).is_disambig()
assert not C.Article(w, w.find("Hush")).is_disambig()
assert C.Article(w, w.find("Mara Quill")).kind() == "person"                  # mentions a label, is not one
assert C.Article(w, w.find("Kestrel Disk")).kind() == "label"
for sent in ("Sub Pop is an American independent record label based in Seattle",
             "Folkways Records was an American record company and music publisher"):
    assert C.LABEL_HEAD.search(re.search(r"\b(?:is|was)\b(.*)", sent).group(1)), sent
for sent in ("is an American photographer best known for his work with the Sub Pop label",
             "is a Niger–Congo language spoken in West Africa"):
    assert not C.LABEL_HEAD.search(" " + sent)
try:                                                                            # two bands, no database: list them
    C.choose_seed(w, "hush", None)
    raise AssertionError("expected Ambiguous")
except C.Ambiguous as amb:
    assert [c["title"] for c in amb.options] == ["Hush (band)", "Hush (UK band)"], amb.options
sd, note = C.choose_seed(w, "ember", None)                                      # one music reading: used, others named
assert sd.title == "Ember (band)" and "read as Ember (band)" in note, (sd.title, note)
sd, note = C.choose_seed(w, "hush", mb)                                         # one band far bigger: used, other named
assert sd.title == "Hush (band)" and "Hush (UK band)" in note, (sd.title, note)
sd, note = C.choose_seed(w, "orrin val", mb)
assert sd.title == "Orrin Vale" and note.startswith("no page called"), (sd.title, note)
print("✅ names: lower case finds the page, labels and look-alikes told apart, ambiguous names listed or resolved")

# ---- a label: artists with their records on it
lab = C.Article(w, w.find("kestrel disk"))
r3 = C.connections(w, lab, progress=False, mb=mb)
assert r3.label_mode and r3.label_name == "Kestrel Disk"
by3 = {r["title"]: r for r in r3}
assert by3["Pale Harbour"]["kind"] == "musician" and by3["Pale Harbour"]["works"] == [("Soft Engines", 1969)]
assert by3["Soft Engines"].get("owner") == "Pale Harbour"                       # the record hangs on its artist
assert by3["Mara Quill"]["kind"] == "person"
assert by3["Dov Ketch"].get("offwiki") and by3["Orrin Vale"]["kind"] == "musician"   # MusicBrainz roster added
assert C.works_line(by3["Pale Harbour"], mb, "Kestrel Disk") == "On the label: Soft Engines (1969)"
assert C.works_line(by3["Dov Ketch"], mb, "Kestrel Disk") == "On the label: Glass Weather (1972) · Ninth Room (1974)"
assert C.works_line(by3["Orrin Vale"], mb, "Kestrel Disk") == "On the label: Night Choir (1967) · Stone Hours (1970)"
assert all(0 <= r["score"] <= 1.0 for r in r3), max(r["score"] for r in r3)
used = {}
musos = [r for r in r3 if r["kind"] == "musician"]
shown = [C.reason(r, used) for r in musos]
quoted = [t for t in shown if t.startswith("“")]
assert len(quoted) == len(set(quoted)), quoted                                  # no sentence printed twice
assert all(t for t, r in zip(shown, musos) if r["mentions"]), shown             # but every linked one still gets a reason
print("✅ label: roster with records, MusicBrainz names added, no sentence repeated")

# ---- a music.db lookup that takes too long is abandoned: Wikipedia-only answer, no hang
def too_slow(*a, **k):
    raise sqlite3.OperationalError("interrupted")
mb_slow = C.MusicDB(MDB)
mb_slow.partners = too_slow
r4 = C.connections(w, seed, progress=False, mb=mb_slow)
assert r4[0]["title"] == "Lena Marsh" and all(r["mb"] is None for r in r4)
assert [r["score"] for r in r4] == [r["score"] for r in C.connections(w, seed, progress=False)]   # same as no music.db
print("✅ slow music.db: given up cleanly, Wikipedia-only scores")

# ---- the real command line, end to end
import subprocess                           # noqa: E402
def cli(*args):
    return subprocess.run([sys.executable, os.path.join(os.path.dirname(HERE), "connections.py"), "--zim", ZIM,
                           "--musicdb", MDB, *args], capture_output=True, text=True, encoding="utf-8")
o = cli("kestrel disk", "--top", "10")
assert o.returncode == 0, o.stderr
assert "Kestrel Disk  (label)" in o.stdout and "Artists on the label" in o.stdout, o.stdout
assert "Musicians and groups" not in o.stdout, o.stdout
assert "On the label: Soft Engines (1969)" in o.stdout and "Glass Weather (1972)" in o.stdout, o.stdout
lines = [l.strip() for l in o.stdout.splitlines() if l.strip().startswith("“")]
assert len(lines) == len(set(lines)), lines
o = cli("hush")
assert o.returncode == 2 or "read as Hush (band)" in o.stdout, o.stdout
o = cli("ember")
assert "Ember (band)  (musician)" in o.stdout and "read as Ember (band)" in o.stdout, o.stdout
print("✅ command line: label shaped as a label, ambiguous name resolved")

if len(sys.argv) > 1:
    real = C.Wiki(sys.argv[1])
    n = bad = 0
    t0 = time.time()
    for i in range(real.zim.entry_count):
        try:
            e = (getattr(real.zim, "get_entry_by_id", None) or real.zim._get_entry_by_id)(i)
            if e.is_redirect or not e.get_item().mimetype.startswith("text/html"):
                continue
        except Exception:
            continue
        n += 1
        try:
            a = C.Article(real, e)
            C.connections(real, a, progress=False)
            for r in C.connections(real, a, progress=False)[:3]:
                C.reason(r)
        except Exception as x:
            bad += 1
            print("❌", e.path, repr(x)[:200])
    print(f"✅ {n} real articles, {bad} errors, {time.time() - t0:.1f}s")
    sys.exit(1 if bad else 0)
