#!/usr/bin/env python3
"""
musicdb: look an artist up in music.db (made by build_musicdb.py from MusicBrainz).

    python3 musicdb.py "Milford Graves"
    python3 musicdb.py "Milford Graves" --top 25
    python3 musicdb.py "Milford Graves" --db /path/to/music.db

Finds the artist by Wikipedia title or name (the one with a Wikipedia article and the most
connections wins; others with the same name are listed), then prints:
  what MusicBrainz knows: type, years, area, genres, instruments, labels
  relationships: bands, collaborations, teachers, … (with years and instruments)
  played with: artists on the same albums (and tracks), most albums first, with their earliest shared album
If the name is a record label rather than an artist, it prints the label's roster instead: each artist
with the albums they put out on it (needs music.db 0.5 for the album titles).
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

VERSION = "0.3"
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


def show_label(con, name, top):
    """a label's roster: artists with their albums on it. True if the name is a label in music.db"""
    try:
        roster = con.execute("""SELECT a.id, a.name, a.wiki, l.n, l.name FROM label l JOIN artist a ON a.id=l.artist
                                WHERE l.name = ? COLLATE NOCASE ORDER BY l.n DESC, a.name LIMIT ?""", (name.strip(), top * 3)).fetchall()
    except sqlite3.Error:
        return False
    if not roster:
        return False
    print(f"{roster[0][4]}  (label)")
    print("\nArtists and their albums on the label")
    print("-------------------------------------")
    try:
        con.execute("SELECT 1 FROM label_album LIMIT 1")
        have_albums = True
    except sqlite3.Error:
        have_albums = False
    for aid, aname, wiki, n, lname in roster[:top]:
        print(f"   {aname}  ({n} album{'s' * (n != 1)})" + ("  ·W" if wiki else ""))
        if have_albums:
            albs = con.execute("SELECT album, year FROM label_album WHERE label = ? COLLATE NOCASE AND artist = ? "
                               "ORDER BY year IS NULL, year, album LIMIT 6", (lname, aid)).fetchall()
            if albs:
                print("      " + " · ".join(f"{t}" + (f" ({y})" if y else "") for t, y in albs))
    print("\n·W = has an English Wikipedia article.  Data: MusicBrainz.")
    return True


def main():
    ap = argparse.ArgumentParser(description="Look an artist up in music.db (MusicBrainz).")
    ap.add_argument("name")
    ap.add_argument("--db")
    ap.add_argument("--top", type=int, default=15)
    a = ap.parse_args()
    con = sqlite3.connect(find_db(a.db))
    art, others = find_artist(con, a.name)
    if not art and show_label(con, a.name, a.top):
        return
    if not art:
        like = [r[0] for r in con.execute("SELECT name FROM artist WHERE name LIKE ? LIMIT 8", (f"%{a.name}%",))]
        sys.exit(f"No artist called “{a.name}”." + (" Close: " + "; ".join(like) if like else ""))
    aid = art[0]
    print(label(art))
    g = [r[0] for r in con.execute("SELECT name FROM genre WHERE artist=? ORDER BY votes DESC LIMIT 6", (aid,))]
    ins = [f"{r[0]} ({r[1]})" for r in con.execute(
        "SELECT name, n FROM instrument WHERE artist=? ORDER BY n DESC LIMIT 8", (aid,))]
    labs = [f"{r[0]} ({r[1]})" for r in con.execute(
        "SELECT name, n FROM label WHERE artist=? ORDER BY n DESC LIMIT 8", (aid,))]
    if g:
        print("  genres: " + ", ".join(g))
    if ins:
        print("  instruments on credits: " + ", ".join(ins))
    if labs:
        print("  labels (albums): " + ", ".join(labs))
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
        SELECT x.name, x.wiki, p.albums, p.tracks, p.example, p.year FROM played p
        JOIN artist x ON x.id = CASE WHEN p.a=? THEN p.b ELSE p.a END
        WHERE p.a=? OR p.b=?
        ORDER BY p.albums DESC, p.tracks DESC LIMIT ?
    """, (aid, aid, aid, a.top)).fetchall()
    if played:
        print("\nPlayed with (shared albums and tracks)")
        print("--------------------------------------")
        for name, wiki, nalb, ntr, ex, yr in played:
            counts = ", ".join(x for x in (f"{nalb} album{'s' * (nalb != 1)}" if nalb else "",
                                           f"{ntr} track{'s' * (ntr != 1)}" if ntr else "") if x)
            first = f"\n      first: {ex}" + (f" ({yr})" if yr else "") if ex else ""
            print(f"   {name}  ({counts})" + ("  ·W" if wiki else "") + first)
    if not rels and not played:
        print("\nMusicBrainz has no relationships or performer credits for this artist yet.")
    print("\n·W = has an English Wikipedia article.  Data: MusicBrainz.")


if __name__ == "__main__":
    main()
