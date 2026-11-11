# Blue Sky Harvest: context for Claude

Read this first in any new chat or session about this project. README.md has the
architecture; this file has the working context.

## Who and why
- **JC**, Liverpool. Works at an art gallery; plays in a touring trio. Not a programmer:
  give exact Terminal commands to copy, one step at a time, and explain what each does.
- The ethos, in JC's words: "a calmer realm in which to experience the internet … quality
  over quantity. A fine-tuned, curated, safe space." **Nothing arrives unless JC chose it.**
  No RSS dumps, no auto-feeds. The one exception is #sstacks (a few chosen Substack writers,
  free posts only, weekly cap).
- Wider aim: rescue obsolete hardware (old Kindle, ThinkPads, maybe an iPod) and own the
  infrastructure, relying less on the iPhone and MacBook.

## Rules
- **Device names are lowercase**: cyby, exlo, fatline, gleaner — even at the start of a sentence.
- **Never ask JC to paste secrets into chat** (Discord token, Dropbox keys, ctx.fm key).
  Use `read -s` prompts that write to `~/.gleaner/*.env`. The Mac's shell is **zsh**:
  `read -s "K?prompt: "` (bash's `read -p` fails there).
- Secrets never go in this repo.
- Push every change to GitHub as well as sending JC the file. GitHub is the master copy.
- When sending a new gleaner.py: JC downloads it, then
  `mv ~/Downloads/gleaner.py ~/gleaner/gleaner.py && cd ~/gleaner && bash service.sh restart`,
  and check the log shows the new version (`grep __version__ ~/gleaner/gleaner.py`).
- Plugin update on cyby (plugged into the Mac):
  `rm -rf /Volumes/Kindle/koreader/plugins/gleanings.koplugin && unzip -o ~/Downloads/gleanings.koplugin.zip -d /Volumes/Kindle/koreader/plugins/`,
  verify with grep, eject, restart KOReader.
- The WIKISTACK project has sealed story content (`claude/SEALED_STORY.md` in that repo):
  never reveal it to JC.

## Current state (Nov 2026)
- **gleaner 0.9.0** runs on JC's personal MacBook (repo has 0.9.1: only "Cyby" → "cyby" in
  bot messages; deploy whenever convenient) as a launchd service
  (`com.blueskyharvest.gleaner`, log `~/Library/Logs/gleaner.log`), `MODE=local` into
  `~/Library/CloudStorage/Dropbox/Apps/cyby`.
- Discord channels (Blue Sky Harvest): `#gleanings`, `#sleepy-screens`, `#readings`,
  `#sstacks`, `#listenings`. Env has `SCREENSAVER_CHANNEL=sleepy-screens`,
  `LISTEN_CHANNEL=listenings`; readings and sstacks are the code defaults.
- **cyby** (Kindle Paperwhite 2, KOReader v2026.07.1): gleanings plugin syncs
  `documents/gleanings`, `documents/readings`, `documents/sstacks` and `/mnt/us/screensavers`.
  Use Tools → Gleanings → Sync now, never Cloud storage → Synchronize. About 1.2 GB free.
  Dictionaries: English Wiktionary (first) and GCIDE. Backup of KOReader data:
  `~/cyby-backup` on the Mac (rsync commands in chat history).
- #sstacks subscribed to Kevin Munger's *Never Met a Science* (kevinmunger.substack.com).
  Substack's archive API didn't answer from the Mac; the RSS fallback works.
- Other ways in: drag files into Dropbox → Apps → cyby → readings (or sstacks) on the Mac.
- `tools/mobi2epub.py` fixed *Labyrinths* (MOBI7 with a TOC KOReader couldn't read).

## Machines
- **exlo**: ThinkPad X200s, Debian + NsCDE, 480 GB SSD, full English Wikipedia ZIM for
  WIKISTACK. The off-grid cyberdeck.
- **The server ("fatline")**: decided to start with JC's spare **ThinkPad X200** (in his
  office) instead of a Pi: free, exlo's twin, battery as a UPS, easy to move. Needs a
  2.5" SATA SSD (500 GB–1 TB), Debian, TLP battery limits, lid-closed. Then gleaner moves
  there with `MODE=api` and the Mac copy is uninstalled. Pi only if power or noise bothers him.
  Waiting on: RAM and drive size of the X200.
- **H2T**: Heltec T114 Meshtastic node with GPS. Mesh messaging rejected; GPS for exlo is the use.
- **iPod** (generation unknown, check model number A1136 / A1238): idea is Rockbox + SD mod.
- GitHub account houseofsaturn (repos: wikistack, blue-sky-harvest). JC's 2FA currently lives
  on his work MacBook; he's advised to move it to a phone authenticator app.

## Next
1. Wikipedia dictionary for cyby: run `tools/wikidict.py` on exlo or the server.
2. Set up the X200 server (fatline) and move gleaner to it.
3. Map atlases: `#maps` channel, greyscale PDF atlases from OpenStreetMap, rendered on the server.
4. Save Wikipedia pictures from cyby (KOReader plugin → #sleepy-screens via webhook, or a folder).
5. exlo off-grid: GPS from the H2T, exlo's own Wi-Fi hotspot so cyby can collect from exlo
   away from home, local maps, a daily briefing card (sunrise/sunset, moon, saved forecast,
   barometer via a BME280, tide tables fetched ahead).
6. #readings auto-fixing books with no working table of contents (mobi2epub, Calibre).

Parked: iPod (Rockbox, SD mod, offline music shelf, listening notes); cyby highlights to a
reading-notes forum; weekly reading note; WIKISTACK daily cards on cyby; SSH to cyby (timed
out, unresolved); Winlink / amateur radio (JC wants a Foundation licence some day);
Calibre wireless to KOReader.
