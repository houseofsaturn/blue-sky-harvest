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
print("✅ music test archive: ranking and kinds as expected")

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
