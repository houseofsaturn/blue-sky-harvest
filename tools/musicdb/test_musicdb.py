#!/usr/bin/env python3
"""
Test build_musicdb.py + musicdb.py on small MADE-UP dumps in the real formats
(MusicBrainz tar.bz2 of PostgreSQL COPY text files; Wikipedia .sql.gz INSERT lines).

    python3 test_musicdb.py
"""
import gzip
import io
import os
import sqlite3
import subprocess
import sys
import tarfile
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
N = "\\N"


def tsv(rows):
    out = []
    for r in rows:
        out.append("\t".join(N if v is None else str(v).replace("\\", "\\\\").replace("\t", "\\t") for v in r))
    return ("\n".join(out) + "\n").encode()


def tarbz2(path, files):
    with tarfile.open(path, "w:bz2") as t:
        for name, data in files.items():
            ti = tarfile.TarInfo(name)
            ti.size = len(data)
            t.addfile(ti, io.BytesIO(data))


def artist(i, name, typ=1, b=None, e=None, area=1):
    return [i, f"mbid-{i}", name, name, b, None, None, e, None, None, typ, area, None, "", 0, "2026", "f", None, None]


def lrow(i, link, e0, e1):
    return [i, link, e0, e1, 0, "2026", 0, "", ""]


def build(d):
    # link types: id, parent, child_order, gid, e0, e1, name, description, phrases…, (16 cols)
    lt = lambda i, e0, e1, name: [i, None, 0, f"g{i}", e0, e1, name, "", "", "", "", "2026", "f", "t", 0, 0]
    core = {
        "artist_type": [[1, "Person", None, 0, "", "g"], [2, "Group", None, 0, "", "g"], [5, "Orchestra", None, 0, "", "g"]],
        "area": [[1, "a1", "Harrow Bend", 3, 0, "2026", None, None, None, None, None, None, "f", ""]],
        "artist": [artist(1, "Orrin Vale", 1, 1938, 2019), artist(2, "Lena Marsh"), artist(3, "Tom Ide"),
                   artist(4, "The Hollow Quartet", 2, 1964, 1972), artist(5, "Odd\tName"),
                   artist(6, "Big Orchestra", 5)] + [artist(100 + k, f"Player {k}") for k in range(14)]
                  + [artist(7, "Orrin Vale")],                                          # a namesake, no links
        "link_type": [lt(10, "artist", "artist", "member of band"), lt(11, "artist", "artist", "teacher"),
                      lt(12, "artist", "artist", "married"),                                # not kept
                      lt(20, "artist", "recording", "instrument"), lt(21, "artist", "release", "performer"),
                      lt(22, "artist", "recording", "producer"),                            # not a performer
                      lt(30, "artist", "url", "wikidata"), lt(31, "artist", "url", "wikipedia")],
        "link": [[100, 10, 1964, None, None, 1972, None, None, 1, "2026", "t"],
                 [101, 11, None, None, None, None, None, None, 0, "2026", "f"],
                 [102, 12, None, None, None, None, None, None, 0, "2026", "f"],
                 [200, 20, None, None, None, None, None, None, 1, "2026", "f"],             # drums
                 [201, 20, None, None, None, None, None, None, 1, "2026", "f"],             # alto saxophone
                 [202, 21, None, None, None, None, None, None, 0, "2026", "f"],
                 [203, 22, None, None, None, None, None, None, 0, "2026", "f"],
                 [300, 30, None, None, None, None, None, None, 0, "2026", "f"],
                 [301, 31, None, None, None, None, None, None, 0, "2026", "f"]],
        "link_attribute_type": [[14, None, 14, 0, "g", "instrument", "", "2026"],
                                [50, 14, 14, 0, "g", "drums", "", "2026"],
                                [51, 14, 14, 0, "g", "alto saxophone", "", "2026"]],
        "link_attribute": [[100, 50, "2026"], [200, 50, "2026"], [201, 51, "2026"]],
        "l_artist_artist": [lrow(1, 100, 1, 4), lrow(2, 100, 2, 4), lrow(3, 101, 3, 1), lrow(4, 102, 1, 2)],
        "l_artist_recording": [lrow(1, 200, 1, 900), lrow(2, 201, 2, 900), lrow(3, 200, 1, 901), lrow(4, 201, 2, 901),
                               lrow(5, 203, 3, 900)]                                         # producer: no pair
                              + [lrow(10 + k, 200, 100 + k, 950) for k in range(14)] + [lrow(30, 200, 1, 950)],
        "l_artist_release": [lrow(1, 202, 1, 700), lrow(2, 202, 3, 700)],
        "url": [[1, "u1", "https://www.wikidata.org/wiki/Q101", 0, "2026"],
                [2, "u2", "https://www.wikidata.org/wiki/Q102", 0, "2026"],
                [3, "u3", "https://de.wikipedia.org/wiki/Tom_Ide", 0, "2026"],              # not English
                [4, "u4", "https://en.wikipedia.org/wiki/The_Hollow_Quartet", 0, "2026"]],
        "l_artist_url": [lrow(1, 300, 1, 1), lrow(2, 300, 2, 2), lrow(3, 301, 3, 3), lrow(4, 301, 4, 4)],
        "recording": [[900, "r", "Night Choir", 1, 300, "", 0, "2026", "f"],
                      [901, "r", "Stone Hours", 1, 300, "", 0, "2026", "f"],
                      [950, "r", "Symphony", 1, 300, "", 0, "2026", "f"]],
        "release": [[700, "r", "Kestrel Sessions", 1, 1, None, None, None, None, None, "", 0, -1, "2026"]],
        "genre": [[1, "g", "free jazz", "", 0, "2026"], [2, "g", "jazz", "", 0, "2026"]],
        "track": [[1, 2, 3]],                                                                # a table we skip
    }
    files = {f"mbdump/{k}": tsv(v) for k, v in core.items()}
    files["TIMESTAMP"] = b"2026-11-14 00:22:30.000000+00\n"
    tarbz2(os.path.join(d, "mbdump.tar.bz2"), files)
    derived = {"tag": [[1, "free jazz", 5], [2, "seen live", 9], [3, "jazz", 3]],
               "artist_tag": [[1, 1, 4, "2026"], [1, 2, 9, "2026"], [1, 3, 1, "2026"], [2, 1, 0, "2026"]]}
    tarbz2(os.path.join(d, "mbdump-derived.tar.bz2"), {f"mbdump/{k}": tsv(v) for k, v in derived.items()})
    with gzip.open(os.path.join(d, "enwiki-latest-page_props.sql.gz"), "wt", encoding="utf-8") as f:
        f.write("-- MySQL dump\nINSERT INTO `page_props` VALUES (11,'wikibase_item','Q101',NULL),"
                "(11,'page_image_free','X.jpg',NULL),(12,'wikibase_item','Q102',NULL),(13,'wikibase_item','Q999',NULL);\n")
    with gzip.open(os.path.join(d, "enwiki-latest-page.sql.gz"), "wt", encoding="utf-8") as f:
        f.write("INSERT INTO `page` VALUES (11,0,'Orrin_Vale',0,0,0.5,'20261101','20261101',1,100,'wikitext',NULL),"
                "(12,0,'Lena_Marsh_(saxophonist)',0,0,0.5,'20261101','20261101',1,100,'wikitext',NULL),"
                "(14,1,'Orrin_Vale',0,0,0.5,'20261101','20261101',1,100,'wikitext',NULL),"
                "(13,0,'Somebody\\'s_Page',0,0,0.5,'20261101','20261101',1,100,'wikitext',NULL);\n")


def run(*args):
    r = subprocess.run([sys.executable, *args], capture_output=True, text=True, encoding="utf-8")
    if r.returncode:
        print(r.stdout, r.stderr)
        raise SystemExit("❌ failed: " + " ".join(args))
    return r.stdout


def main():
    with tempfile.TemporaryDirectory() as d:
        dumps = os.path.join(d, "downloads")
        os.makedirs(dumps)
        build(dumps)
        out = run(os.path.join(HERE, "build_musicdb.py"), "--dumps", dumps)
        assert "all done" in out, out
        again = run(os.path.join(HERE, "build_musicdb.py"), "--dumps", dumps)            # resumes: skips steps
        assert "already done" in again, again
        dbp = os.path.join(d, "music.db")
        con = sqlite3.connect(dbp)
        A = {r[0]: r for r in con.execute("SELECT id, name, type, begin, end, area, wiki, qid FROM artist")}
        assert A[1][6] == "Orrin_Vale" and A[1][7] == "Q101", A[1]
        assert A[2][6] == "Lena_Marsh_(saxophonist)", A[2]
        assert A[3][6] is None, A[3]                                   # German Wikipedia link ignored
        assert A[4][6] == "The_Hollow_Quartet", A[4]                   # direct English Wikipedia link
        assert A[5][1] == "Odd\tName", A[5]                            # escapes undone
        assert A[1][2] == "Person" and A[1][3] == 1938 and A[1][5] == "Harrow Bend", A[1]
        rel = set(con.execute("SELECT a, b, kind, begin, end, detail FROM rel"))
        assert (1, 4, "member of band", 1964, 1972, "drums") in rel, rel
        assert (3, 1, "teacher", None, None, None) in rel, rel
        assert not any(r[2] == "married" for r in rel), rel
        played = {(a, b): (r, s, e) for a, b, r, s, e in con.execute("SELECT * FROM played")}
        assert played[(1, 2)][0] == 2 and played[(1, 2)][2] in ("Night Choir", "Stone Hours"), played
        assert played[(1, 3)] == (0, 1, "Kestrel Sessions"), played     # release credit; producer not counted
        assert not any(a >= 100 or b >= 100 for a, b in played), played  # 15 on one recording: no pairs
        ins = set(con.execute("SELECT artist, name, n FROM instrument"))
        assert (1, "drums", 3) in ins and (2, "alto saxophone", 2) in ins, ins
        gen = set(con.execute("SELECT artist, name, votes FROM genre"))
        assert gen == {(1, "free jazz", 4), (1, "jazz", 1)}, gen       # "seen live" isn't a genre; 0 votes dropped
        meta = dict(con.execute("SELECT key, value FROM meta"))
        assert meta["musicbrainz_dump"].startswith("2026-11-14"), meta
        con.close()
        look = run(os.path.join(HERE, "musicdb.py"), "Orrin Vale", "--db", dbp)
        print(look)
        assert look.startswith("Orrin Vale  (Person, 1938–2019, Harrow Bend)  · Wikipedia: Orrin Vale"), look
        assert "member of:" in look and "The Hollow Quartet  (1964–1972, drums)  ·W" in look, look
        assert "teachers:" in look and "Tom Ide" in look, look
        assert "Lena Marsh  (2 recordings)  ·W" in look, look
        assert "also called this" in look, look                        # the namesake is mentioned, not chosen
        print("✅ build_musicdb + musicdb: all checks passed")


if __name__ == "__main__":
    main()
