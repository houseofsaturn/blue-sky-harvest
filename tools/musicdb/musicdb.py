#!/usr/bin/env python3
"""
musicdb: look an artist up in music.db (made by build_musicdb.py from MusicBrainz).

    python3 musicdb.py "Milford Graves"
    python3 musicdb.py "Milford Graves" --top 25
    python3 musicdb.py "Milford Graves" --db /path/to/music.db

Finds the artist by Wikipedia title or name (the one with a Wikipedia article and the most
connections wins; others with the same name are listed), then prints:
  what MusicBrainz knows: type, years, area, genres, instruments
  relationships: bands, collaborations, teachers, … (with years and instruments)
  played with: artists credited on the same recordings / releases, most first, with an example
Default database: music.db next to this script, else ~/musicdb/music.db.
Data: MusicBrainz (CC0; genre tags CC BY-NC-SA). Standard library only.
"""
from __future__ import annotations

import argparse
import os
import sqlite3
import sys

try:
    sys.stdout.reconfigure(errors="replace")
except Exception:
    pass

VERSION = "0.1"
REL_WORDS = {   # (a -> b, b -> a): how to say it from each side
    "member of band": ("member of", "members"),
    "collaboration": ("collaborated on", "collaborators"),
    "supporting musician": ("supporting musician for", "supporting musicians"),
    "instrumental supporting musician": ("played for", "instrumental support"),
    "vocal supporting musician": ("sang for", "vocal support"),
    "teacher": ("taught", "teachers"),
    "subgroup": ("subgroup of", "subgroups"),
    "conductor position": ("conductor of", "conductors"),
    "founder": ("founded", "founders"),
    "artistic director": ("artistic director of", "artistic directors"),
    "tribute": ("tribute to", "tributes"),
    "is person": ("performing name of", "performing names"),
}


def find_db(arg):
    for p in ([arg] if arg else []) + [os.path.join(os.path.dirname(os.path.abspath(__file__)), "music.db"),
                                        os.path.join(os.path.expanduser("~"), "musicdb", "music.db")]:
        if p and os.path.exists(p):
            return p
    sys.exit("musicdb: no music.db found. Use --db /path/to/music.db")


def years(b, e):
    if b and e:
        return f"{b}–{e}"
    if b:
        return f"{b}–"
    if e:
        return f"–{e}"
    return ""


def find_artist(con, name):
    q = name.strip()
    cands = con.execute(
        "SELECT id, name, type, begin, end, area, wiki FROM artist WHERE wiki = ? OR name = ? COLLATE NOCASE",
        (q.replace(" ", "_"), q)).fetchall()
    if not cands:
        return None, []

    def weight(c):
        n = con.execute("SELECT (SELECT count(*) FROM played WHERE a=? OR b=?) + (SELECT count(*) FROM rel WHERE a=? OR b=?)",
                        (c[0], c[0], c[0], c[0])).fetchone()[0]
        return (c[6] is not None and c[6].replace("_", " ").lower() == q.lower(), c[6] is not None, n)
    cands.sort(key=weight, reverse=True)
    return cands[0], cands[1:]


def label(row):
    i, name, typ, b, e, area, wiki = row
    bits = [typ or "", years(b, e), area or ""]
    s = name + "  (" + ", ".join(x for x in bits if x) + ")"
    return s + ("  · Wikipedia: " + wiki.replace("_", " ") if wiki else "")


def main():
    ap = argparse.ArgumentParser(description="Look an artist up in music.db (MusicBrainz).")
    ap.add_argument("name")
    ap.add_argument("--db")
    ap.add_argument("--top", type=int, default=15)
    a = ap.parse_args()
    con = sqlite3.connect(find_db(a.db))
    art, others = find_artist(con, a.name)
    if not art:
        like = [r[0] for r in con.execute("SELECT name FROM artist WHERE name LIKE ? LIMIT 8", (f"%{a.name}%",))]
        sys.exit(f"No artist called “{a.name}”." + (" Close: " + "; ".join(like) if like else ""))
    aid = art[0]
    print(label(art))
    g = [r[0] for r in con.execute("SELECT name FROM genre WHERE artist=? ORDER BY votes DESC LIMIT 6", (aid,))]
    ins = [f"{r[0]} ({r[1]})" for r in con.execute(
        "SELECT name, n FROM instrument WHERE artist=? ORDER BY n DESC LIMIT 8", (aid,))]
    if g:
        print("  genres: " + ", ".join(g))
    if ins:
        print("  instruments on credits: " + ", ".join(ins))
    if others:
        print("  (also called this: " + "; ".join(label(o) for o in others[:4]) + ")")

    rels = con.execute("""
        SELECT r.kind, 0, x.name, x.wiki, r.begin, r.end, r.detail FROM rel r JOIN artist x ON x.id=r.b WHERE r.a=?
        UNION ALL
        SELECT r.kind, 1, x.name, x.wiki, r.begin, r.end, r.detail FROM rel r JOIN artist x ON x.id=r.a WHERE r.b=?
    """, (aid, aid)).fetchall()
    if rels:
        print("\nRelationships")
        print("-------------")
        groups = {}
        for kind, rev, name, wiki, b, e, det in rels:
            head = REL_WORDS.get(kind, (kind, kind))[rev]
            groups.setdefault(head, []).append((name, wiki, b, e, det))
        for head, items in groups.items():
            print(f"{head}:")
            for name, wiki, b, e, det in sorted(items, key=lambda t: (t[2] or 9999, t[0]))[:a.top]:
                extra = ", ".join(x for x in (years(b, e), det) if x)
                print(f"   {name}" + (f"  ({extra})" if extra else "") + ("  ·W" if wiki else ""))

    played = con.execute("""
        SELECT x.name, x.wiki, x.type, p.recordings, p.releases, p.example FROM played p
        JOIN artist x ON x.id = CASE WHEN p.a=? THEN p.b ELSE p.a END
        WHERE p.a=? OR p.b=?
        ORDER BY p.recordings + 3 * p.releases DESC LIMIT ?
    """, (aid, aid, aid, a.top)).fetchall()
    if played:
        print("\nPlayed with (shared credits)")
        print("----------------------------")
        for name, wiki, typ, nrec, nrel, ex in played:
            counts = ", ".join(x for x in (f"{nrec} recording{'s' * (nrec != 1)}" if nrec else "",
                                           f"{nrel} release{'s' * (nrel != 1)}" if nrel else "") if x)
            print(f"   {name}  ({counts})" + ("  ·W" if wiki else "") + (f"\n      e.g. {ex}" if ex else ""))
    if not rels and not played:
        print("\nMusicBrainz has no relationships or performer credits for this artist yet.")
    print("\n·W = has an English Wikipedia article.  Data: MusicBrainz.")


if __name__ == "__main__":
    main()
