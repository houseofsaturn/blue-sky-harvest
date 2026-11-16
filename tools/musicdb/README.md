# musicdb

The second source for the music conversations (after offline Wikipedia): **who actually
played with whom**, from MusicBrainz, boiled down into one small SQLite file, `music.db`,
that exlo and fatline can carry. No AI, nothing online once it's built.

| File | What it does | Where it runs |
|---|---|---|
| `build_musicdb.py` | Turns the downloads into `music.db` (one-off, heavy) | exlomax |
| `musicdb.py` | Looks an artist up: relationships, who they played with, instruments, genres | anywhere with `music.db` |
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

## What's inside music.db

- `artist`: every MusicBrainz artist, with type, years, area, English Wikipedia title (via Wikidata) and Q-id
- `rel`: member of band, collaboration, supporting musician, teacher, subgroup, founder, conductor … (with years, instruments)
- `played`: pairs credited as performers on the same recordings / releases (recordings with more than 12 credited performers, e.g. orchestras, are left out), with counts and an example title
- `instrument`: instruments per artist, from their performer credits
- `genre`: MusicBrainz genre tags per artist, with votes
- `meta`: dump date, row counts, licences

Licences: MusicBrainz core data CC0; genre tags CC BY-NC-SA 3.0 (fine for this personal,
non-commercial project); Wikipedia titles CC BY-SA.
Wikidata itself is **not** used yet (its full dump is huge and slow to process in plain Python;
MusicBrainz covers most of the same facts). Add it later only if something's clearly missing.
