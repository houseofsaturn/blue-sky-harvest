# Blue Sky Harvest

A calmer way to take things from the internet. Nothing arrives unless JC chose it.

A calm network whose infrastructure is mostly self-owned; a project to learn from; old,
seemingly defunct hardware given a second life; more autonomy and less big tech, in the
spirit of the original hacker ethos; sustainable, and sometimes off-grid.

It is built around **cyby**, a jailbroken Kindle Paperwhite 2 running KOReader, and
**Blue Sky Harvest**, a private Discord server. Things posted to the server's channels
are turned into something useful and delivered to cyby, or to ctx.fm. The only automatic
source is #sstacks: a handful of chosen Substack writers, capped at a few posts a week.

```
 Discord: Blue Sky Harvest            gleaner (the bot)                 Dropbox: Apps/cyby          cyby
 ─────────────────────────            ────────────────────              ──────────────────          ────
 #gleanings     links, PDFs,  ──▶  article → clean EPUB      ──▶  *.epub / *.pdf        ──▶  documents/gleanings
                EPUBs, text         files passed through
 #sleepy-screens  images      ──▶  greyscale 758×1024 PNG,   ──▶  screensavers/*.png    ──▶  /mnt/us/screensavers
                                    5 mm margin, dithered                                      (random sleep screen)
 #readings      ebook files   ──▶  passed through untouched  ──▶  readings/*             ──▶  documents/readings
                or links
 #sstacks       Substack      ──▶  checks chosen writers;    ──▶  sstacks/*.epub        ──▶  documents/sstacks
                links          new free posts → EPUB,
                (subscribe)    weekly cap (!cap)
 #listenings    music links   ──▶  ctx.fm API: add to queue
                                    (or collection)
```

cyby collects new files by itself whenever its Wi-Fi connects or it wakes up
(the **gleanings** KOReader plugin). Deleting a post in #sleepy-screens deletes that
sleep screen; anything deleted on cyby stays deleted.

## What's here

| Folder | What it is |
|---|---|
| [`gleaner/`](gleaner/) | The Discord bot (Python). Runs on the MacBook as a background service for now; built to move to the server (fatline). |
| [`koreader/gleanings.koplugin/`](koreader/gleanings.koplugin/) | cyby's sync plugin. Copy the folder to `koreader/plugins/` on the Kindle. |
| [`tools/wikidict.py`](tools/wikidict.py) | Builds an offline Wikipedia dictionary for cyby from the Wikipedia `.zim` on exlo. |
| [`tools/mobi2epub.py`](tools/mobi2epub.py) | Turns an old Kindle MOBI into a clean EPUB with a working (optionally nested) table of contents. Used for *Labyrinths*; the start of the planned #readings fixer. |

## Secrets

No keys are in this repository, and `.gitignore` keeps them out. They live only on the
machine that runs gleaner:

- `~/.gleaner/gleaner.env`: Discord bot token, channel names, ctx.fm API key
- `~/.gleaner/dropbox.env`: Dropbox app key, secret and refresh token (for `MODE=api`)

On cyby the Dropbox details are in KOReader's own cloud-storage settings.

## The machines

- **cyby**: Kindle Paperwhite 2 (DP75SDI), firmware 5.12.2.2, WatchThis jailbreak, KUAL, KOReader.
- **MacBook**: runs gleaner today, saving into the Dropbox desktop folder (`MODE=local`).
- **exlo**: ThinkPad X200s, the semi-offline cyberdeck. Holds the full English Wikipedia (WIKISTACK).
- **fatline** (planned): the always-on server, starting on a spare ThinkPad X200 (a Pi later
  only if needed). Runs gleaner (`MODE=api`), keeps master copies of the big archives fresh,
  builds dictionaries and maps, and tops exlo up when it's home.

## What's next

1. **Wikipedia dictionary for cyby**: `tools/wikidict.py` is written and tested on a small
   archive; waiting to be run on exlo (or the Pi).
2. **Map atlases**: a `#maps` channel; the Pi renders a greyscale PDF atlas (overview page with
   tappable grid squares) from OpenStreetMap data.
3. **Save Wikipedia pictures from cyby**: a KOReader plugin that sends a picture from a
   Wikipedia lookup to #sleepy-screens, or saves it to a folder.
4. **fatline**: set up the spare X200 (SSD, Debian), move gleaner across.
5. **exlo off-grid**: GPS from the H2T, exlo's own Wi-Fi so cyby can collect from it away
   from home, local map atlases, and a daily briefing card (sunrise/sunset, moon, saved
   forecast, barometer, tide tables fetched ahead).

Parked: an iPod with Rockbox as an offline music shelf, #readings automatically fixing books with no working table of contents (convert to EPUB with chapters), cyby highlights into a reading-notes forum, a weekly reading note, WIKISTACK daily
cards on cyby, SSH to cyby, mesh radio (LoRa/Meshtastic) and Winlink.
