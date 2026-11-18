# musicdb

The second source for the music conversations (after offline Wikipedia): **who actually
played with whom**, from MusicBrainz, boiled down into one small SQLite file, `music.db`,
that exlo and fatline can carry. No AI, nothing online once it's built.

| File | What it does | Where it runs |
|---|---|---|
| `build_musicdb.py` | Turns the downloads into `music.db` (one-off, heavy) | exlomax |
| `musicdb.py` | Looks an artist up (relationships, who they played with, instruments, genres) or a label (its roster and records) | anywhere with `music.db` |
| `test_musicdb.py` | Builds made-up dumps in the real formats and checks both scripts | anywhere |

Standard-library Python only (3.10+).

## Downloads (on exlomax, `D:\musicdb\downloads`)

```powershell
$mb = (curl.exe -s https://data.metabrainz.org/pub/musicbrainz/data/fullexport/LATEST).Trim()
curl.exe -L -C - -O "https://data.metabrainz.org/pub/musicbrainz/data/fullexport/$mb/mbdump.tar.bz2"
curl.exe -L -C - -O "https://data.metabrainz.org/pub/musicbrainz/data/fullexport/$mb/mbdump-derived.tar.bz2"
curl.exe -L -C - -O https://dumps.wikimedia.org/enwiki/latest/enwiki-latest-page.sql.gz
curl.exe -L -C - -O https://dumps.wikimedia.org/enwiki/latest/enwiki-latest-page_props.sql.gz
```
First build (16 Nov 2026): snapshot `20261114-002230`; 7.2 GB, 505 MB, 2.25 GB, 463 MB.

## Build

```powershell
cd D:\musicdb
py build_musicdb.py --dumps D:\musicdb\downloads
py musicdb.py "Milford Graves"
```
Steps are resumable (stop it and run again; finished steps are skipped). `--redo` starts the
database steps again but keeps the unpacked tables. The unpack is the slow part.

**Upgrading 0.4 → 0.5** (adds `label_album`, so a label can list its records): run the same command
again *without* `--redo`. Every finished step is skipped, only the new step "8b label albums" and the
final copy run (a few minutes). If it complains about a missing table, run it once with `--redo`.
Then copy the new `music.db` to exlo and fatline as before.

## What's inside music.db

- `artist`: every MusicBrainz artist, with type, years, area, English Wikipedia title (via Wikidata) and Q-id
- `rel`: member of band, collaboration, supporting musician, teacher, subgroup, founder, conductor … (with years, instruments)
- `played`: pairs of artists on the same **albums** (MusicBrainz release groups, so reissues count once;
  from performer credits on tracks and releases, plus the album's own artist credit such as
  "Milford Graves & Don Pullen") and the same **tracks**, with the earliest shared album and its year.
  Left out: various-artists compilations, DJ mixes, mixtapes, albums with more than 20 artists and
  tracks with more than 12 performers (orchestras, choirs)
- `instrument`: instruments per artist, from their performer credits (classes like "membranophone" left out)
- `genre`: MusicBrainz genre tags per artist, with votes
- `label`: labels of the artist's own albums, with how many albums ("[no label]" left out)
- `label_album`: what each label released, per credited artist: label, artist, album, year (0.5);
  lets `connections.py` and `musicdb.py` show a label as artists with their records
- `meta`: dump date, row counts, licences

Licences: MusicBrainz core data CC0; genre tags CC BY-NC-SA 3.0 (fine for this personal,
non-commercial project); Wikipedia titles CC BY-SA.
Wikidata itself is **not** used yet (its full dump is huge and slow to process in plain Python;
MusicBrainz covers most of the same facts). Add it later only if something's clearly missing.
