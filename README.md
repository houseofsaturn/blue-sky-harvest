# Blue Sky Harvest

A calmer way to take things from the internet. Nothing arrives unless JC chose it.

It is built around **Cyby**, a jailbroken Kindle Paperwhite 2 running KOReader, and
**Blue Sky Harvest**, a private Discord server. Things posted to the server's channels
are turned into something useful and delivered to Cyby, or to ctx.fm. The only automatic
source is #sstacks: a handful of chosen Substack writers, capped at a few posts a week.

```
 Discord: Blue Sky Harvest            gleaner (the bot)                 Dropbox: Apps/cyby          Cyby
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

Cyby collects new files by itself whenever its Wi-Fi connects or it wakes up
(the **gleanings** KOReader plugin). Deleting a post in #sleepy-screens deletes that
sleep screen; anything deleted on Cyby stays deleted.

## What's here

| Folder | What it is |
|---|---|
| [`gleaner/`](gleaner/) | The Discord bot (Python). Runs on the MacBook as a background service for now; built to move to a Raspberry Pi. |
| [`koreader/gleanings.koplugin/`](koreader/gleanings.koplugin/) | Cyby's sync plugin. Copy the folder to `koreader/plugins/` on the Kindle. |
| [`tools/wikidict.py`](tools/wikidict.py) | Builds an offline Wikipedia dictionary for Cyby from the Wikipedia `.zim` on exlo. |
| [`tools/mobi2epub.py`](tools/mobi2epub.py) | Turns an old Kindle MOBI into a clean EPUB with a working (optionally nested) table of contents. Used for *Labyrinths*; the start of the planned #readings fixer. |

## Secrets

No keys are in this repository, and `.gitignore` keeps them out. They live only on the
machine that runs gleaner:

- `~/.gleaner/gleaner.env`: Discord bot token, channel names, ctx.fm API key
- `~/.gleaner/dropbox.env`: Dropbox app key, secret and refresh token (for `MODE=api`)

On Cyby the Dropbox details are in KOReader's own cloud-storage settings.

## The machines

- **Cyby**: Kindle Paperwhite 2 (DP75SDI), firmware 5.12.2.2, WatchThis jailbreak, KUAL, KOReader.
- **MacBook**: runs gleaner today, saving into the Dropbox desktop folder (`MODE=local`).
- **exlo**: ThinkPad X200s, the semi-offline cyberdeck. Holds the full English Wikipedia (WIKISTACK).
- **The Pi** (planned): the always-on home server. Runs gleaner (`MODE=api`), keeps master
  copies of the big archives fresh, builds dictionaries and maps, and tops exlo up when it's home.

## What's next

1. **Wikipedia dictionary for Cyby**: `tools/wikidict.py` is written and tested on a small
   archive; waiting to be run on exlo (or the Pi).
2. **Map atlases**: a `#maps` channel; the Pi renders a greyscale PDF atlas (overview page with
   tappable grid squares) from OpenStreetMap data.
3. **Save Wikipedia pictures from Cyby**: a KOReader plugin that sends a picture from a
   Wikipedia lookup to #sleepy-screens, or saves it to a folder.
4. **The Pi**: hardware, set-up, move gleaner across.
5. **exlo off-grid**: GPS from the H2T, exlo's own Wi-Fi so Cyby can collect from it away
   from home, local map atlases, and a daily briefing card (sunrise/sunset, moon, saved
   forecast, barometer, tide tables fetched ahead).

Parked: #readings automatically fixing books with no working table of contents (convert to EPUB with chapters), Cyby highlights into a reading-notes forum, a weekly reading note, WIKISTACK daily
cards on Cyby, SSH to Cyby, mesh radio (LoRa/Meshtastic) and Winlink.
