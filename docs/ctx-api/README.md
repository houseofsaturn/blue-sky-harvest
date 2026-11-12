# ctx.fm REST API: reference for Blue Sky Harvest

`openapi.yaml` is ctx.fm's own OpenAPI 3.1 spec (113 routes), as JC downloaded it on
12 Nov 2026. The live, interactive version is at https://ctx.fm/api/docs/ and the
current spec is always at `GET https://ctx.fm/api/openapi.json`. That spec only lists
the routes the caller's key can see, so if this copy goes stale, download a fresh one
with JC's key rather than guessing. JC also had a JSON copy of the spec. It's identical,
so only the YAML is kept here.

This file is the short version: what matters to us and what gleaner already uses.

## Auth
- A personal API key: header `Authorization: Bearer ctx_…`. It lives in
  `~/.gleaner/gleaner.env` as `CTX_API_KEY`. **Never in this repo, never pasted into chat.**
- Keys are created in ctx.fm's web app. (`/api/api-keys/` needs a logged-in session,
  not a key.)
- Ignore the `jwt` and `nafs` schemes. They're for ctx's own apps and services.

## Rate limits (per account, shared by all its keys)
- Every request: 20 per second, bursts up to 200.
- `url-add` and `plain-language-add`: 60 per hour each. `library-export`: 6 per hour.
  `collage-feed`: 300 per hour. `link-check`: 30 per hour.
- When it's over a limit, ctx replies `429` with `Retry-After: N` (in seconds). A refused
  call costs nothing. gleaner already waits and retries once if N ≤ 60.

## Pagination
Lists use `?cursor=` and `?limit=` (1–100, default 50). Pass `next_cursor` back until
it is `null`. The exception is `GET /api/library/`, which returns whole lists unless
capped.

## How ctx thinks about music
- An **object** (`media_object`) is anything: an album, a song, a link or a collage. It has
  `display_name`, `artists`, `year`, `release_date`, `primary_type` / `subtype`,
  `track_count`, `cover_url`, and `fingerprints` (`kind` + `value`: the IDs and links it's
  known by elsewhere).
- A **library entry** is JC's relationship to an object. Its `status` is either
  `queue` (to listen to) or `collection` (kept). It also has an `on_rotation` flag (in
  heavy play right now) and his **notes** (`private` or `friends`).
- There's **no play history** and no "listened" event. The nearest things are moving an
  entry from queue to collection, setting it on rotation, and leaving a note.

## The routes we use or might use

| Route | What it does | Used by |
|---|---|---|
| `GET /api/profile/` | who the key belongs to, plus `queue_order` | gleaner `!ctx` |
| `POST /api/url-add/` `{url, target_status}` | adds a release by link. It's queued, so poll `GET /api/url-add/{id}/` until COMPLETED or FAILED | gleaner #listenings |
| `POST /api/plain-language-add/` `{query, target_status}` | adds something from a description, e.g. "the new Grouper album". Poll it. It may come back `AWAITING_DISAMBIGUATION` with `candidates`, and you answer with `POST …/{id}/select/` `{candidate_id}`. Can also be `NO_MATCH` | not yet |
| `GET /api/library/?status=queue` | the queue as `entries` (also `type`, `sort`, `q` search, `label_id`) | not yet |
| `GET /api/library/` | queue and collection together, plus counts by artist and label | not yet |
| `PATCH /api/library-entries/{id}/` `{status}` / `{on_rotation}` | moves an entry to collection, or sets or clears rotation | not yet |
| `PATCH /api/library/queue/reorder/` `{ordered_entry_ids}` | puts the whole queue in a new order | not yet |
| `DELETE /api/library-entries/{id}/` | removes an entry | not yet |
| `GET/POST /api/notes/` `{media_object_id, text, visibility}` and `PATCH/DELETE /api/notes/{id}/` | JC's notes on an object | not yet |
| `GET /api/home/` | what's on rotation, recent adds, and counts of pending recs and friend requests | not yet |
| `GET /api/object/{id}/` | full details of an object: tracks (`contains`), label, release date, links | not yet |
| `GET /api/library/export/?format=json\|csv\|txt\|bundle` | the whole library with notes and collages (6 per hour) | not yet: a good fit for an offline copy on exlo |
| `GET /api/recs/received/` and `POST /api/recs/{id}/accept/` | records friends have recommended to JC | not yet |

Also in the API but less relevant: collages (curated lists, with annotations, following
and covers), friends and recs, Bandcamp collection sync, label collages, community chat,
imports and undo.

## Ideas (not decided: see the ctx.fm chat)
- **Listening slip on cyby**: a weekly EPUB of the top of the queue (cover, artists,
  year, label, tracks from `/api/object/{id}/`, plus JC's notes) dropped into a cyby
  folder.
- **#listenings commands**: `!queue` lists the next few, `!next` picks one,
  `!kept` moves it to the collection, `!spin` puts it on rotation, `!note <text>` adds a
  private note. Also plain-language adds: post "the new Grouper album" with no link.
- **Album covers as sleep screens**: `cover_url` → the existing #sleepy-screens code.
- **iPod / Rockbox**: queue → playlist of music JC already owns. Rockbox's play log →
  move the album to collection or put it on rotation (ctx has no "played" event, so
  that's the nearest match).
- **Offline copy on exlo**: `library/export?format=json` on a schedule from fatline.
