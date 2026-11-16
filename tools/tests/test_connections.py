#!/usr/bin/env python3
"""
Checks for tools/connections.py against the made-up music archive.

    python3 tests/test_connections.py            (builds /tmp/music_test.zim first)
    python3 tests/test_connections.py some.zim   (also runs every article of a real archive, to catch crashes)
"""
import os
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
    INSERT INTO rel VALUES (1,4,'member of band',1964,1972,'drums'), (3,1,'teacher',NULL,NULL,NULL);
    INSERT INTO played VALUES (1,2,2,4,'Night Choir',1967), (1,5,1,0,'Grey Lanterns',1971),
        (1,6,1,3,'Night Choir',1967), (3,7,0,1,NULL,NULL);
""")
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
