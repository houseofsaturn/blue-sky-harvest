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
- The wider ethos (JC, 11 Nov 2026):
  - a **calm network** whose infrastructure JC mostly owns
  - a project JC **learns from**
  - **giving life back** to seemingly defunct technology (old Kindle, ThinkPads, maybe an iPod)
  - a more **autonomous** network, moving away from big tech (less reliance on the iPhone
    and MacBook)
  - the original **hacker ethos**
  - **sustainable**, and sometimes **off-grid**
  Weigh every design choice against these.

## How this project is organised
One chat per area inside the claude.ai project. Chats can't talk to each other directly,
so **this file is the shared notebook**: when a chat finishes something, it updates
"Current state" / "Next" here and pushes to GitHub, so the next chat starts from the
latest picture. Pull before editing (another chat may have pushed).
- **gleaner**: the Discord bot and its channels, incl. the #readings TOC fixer
- **cyby**: the Kindle, KOReader plugin, Wikipedia dictionary, saving Wikipedia pictures,
  highlights / reading notes
- **fatline**: the always-on server (spare X200) and moving gleaner onto it
- **#off-grid** (exlo off-grid): GPS (H2T), exlo's own Wi-Fi for cyby, the daily briefing card
- **maps**: #maps channel and map atlases (touches fatline, cyby and exlo)
- **parked**: iPod / Rockbox, Winlink / radio, as and when
- **#faq** (general questions): questions about the project as a whole, housekeeping, cross-area decisions
- **ctx.fm**: JC's music library (queue / collection / rotation / notes) and how it joins
  the project (#listenings, cyby, iPod). API reference: `docs/ctx-api/` (README = short version)
WIKISTACK has its own repo and project. Its *code* may be reused here (JC, 12 Nov 2026), e.g. its ZIM
reader (`Stack`), link relatedness (`LinkJudge`) and article parser in `wikistack.py`; its story
and game content stays out.

## Rules
- **Device names are lowercase**: cyby, exlo, fatline, gleaner — even at the start of a sentence.
- **Never ask JC to paste secrets into chat** (Discord token, Dropbox keys, ctx.fm key).
  Use `read -s` prompts that write to `~/.gleaner/*.env`. The Mac's shell is **zsh**:
  `read -s "K?prompt: "` (bash's `read -p` fails there).
- Secrets never go in this repo.
- Push every change to GitHub as well as sending JC the file. GitHub is the master copy.
- gleaner runs on **fatline** now. To deploy a change: push to GitHub, then JC runs
  `ssh fatline`, `cd ~/blue-sky-harvest/gleaner && git pull && bash service.sh restart`,
  and checks the status shows the new version. No more downloading gleaner.py by hand.
  On fatline (bash) secrets prompts are `read -rs -p "Key: " K`; on the Mac (zsh) `read -s "K?prompt: "`.
- Plugin update on cyby (plugged into the Mac):
  `rm -rf /Volumes/Kindle/koreader/plugins/gleanings.koplugin && unzip -o ~/Downloads/gleanings.koplugin.zip -d /Volumes/Kindle/koreader/plugins/`,
  verify with grep, eject, restart KOReader.
- The WIKISTACK project has sealed story content (`claude/SEALED_STORY.md` in that repo):
  never reveal it to JC.

## Current state (Nov 2026)
- **gleaner 0.9.1 runs on fatline** (moved 14 Nov 2026, all channels tested OK): systemd user
  service `gleaner.service` with linger, code in `~/blue-sky-harvest/gleaner` (git clone via
  read-only deploy key), settings in `~/.gleaner/` (copied from the personal MacBook with scp),
  `MODE=api` (Dropbox API, existing dropbox.env worked). `bash service.sh status | log | restart`.
  The personal MacBook's copy is uninstalled; its `~/gleaner` and `~/.gleaner` can be deleted
  after a few calm days (keep a private backup of `~/.gleaner` if wanted).
- Discord channels (Blue Sky Harvest): `#gleanings`, `#sleepy-screens`, `#readings`,
  `#sstacks`, `#listenings`. Env has `SCREENSAVER_CHANNEL=sleepy-screens`,
  `LISTEN_CHANNEL=listenings`; readings and sstacks are the code defaults.
- **cyby** (Kindle Paperwhite 2, KOReader v2026.07.1): gleanings plugin syncs
  `documents/gleanings`, `documents/readings`, `documents/sstacks` and `/mnt/us/screensavers`.
  Use Tools → Gleanings → Sync now, never Cloud storage → Synchronize. About 1.2 GB free.
  User patches live in `koreader/patches/` (repo) → `koreader/patches/` on cyby;
  `2-cyby-title.lua` shows "cyby" instead of "KOReader" on the home screen.
  Dictionaries: English Wiktionary (first) and GCIDE. Backup of KOReader data:
  `~/cyby-backup` on the Mac (rsync commands in chat history).
- #sstacks subscribed to Kevin Munger's *Never Met a Science* (kevinmunger.substack.com).
  Substack's archive API didn't answer from the Mac; the RSS fallback works.
- Other ways in: drag files into Dropbox → Apps → cyby → readings (or sstacks) on the Mac.
- ctx.fm API spec saved in `docs/ctx-api/openapi.yaml` (12 Nov 2026), with a summary of the routes that matter
  in `docs/ctx-api/README.md`. gleaner uses only `profile` and `url-add` so far.
- `tools/mobi2epub.py` fixed *Labyrinths* (MOBI7 with a TOC KOReader couldn't read).

## Machines
- **exlo**: ThinkPad X200s, Debian + NsCDE, 480 GB SSD, full English Wikipedia ZIM for
  WIKISTACK. The off-grid cyberdeck. Python 3.13.5. Wi-Fi is an Intel 5300 (iwlwifi):
  **no AP mode** (only IBSS/managed/monitor, and Kindles can't join ad-hoc), so exlo's own
  network for cyby needs a USB Wi-Fi dongle with AP support (AR9271 / ath9k_htc preferred);
  the 5300 stays as the upstream client. The H2T shows up as `/dev/ttyACM0`.
  Lid (14 Nov 2026): `/etc/systemd/logind.conf` had `HandleLidSwitch=ignore` (and on mains);
  overridden by `/etc/systemd/logind.conf.d/99-exlo-lid.conf` → suspend on lid-close, battery
  or mains. Revisit when the hotspot exists (exlo may need to stay awake, lid shut, serving cyby).
  Fan: idles ~2400 RPM in `auto` at ~37 °C (normal); `thinkfan` / a clean are options.
- **The server ("fatline")**: decided to start with JC's spare **ThinkPad X200** (in his
  office) instead of a Pi: free, exlo's twin, battery as a UPS, easy to move. Needs a
  2.5" SATA SSD (500 GB–1 TB), Debian, TLP battery limits, lid-closed. Then gleaner moves
  there with `MODE=api` and the Mac copy is uninstalled. Pi only if power or noise bothers him.
  Hardware checked (14 Nov 2026): **8 GB RAM** (2x 4 GB DDR3-1333 fitted, shows 7.7 GiB) and a
  **128 GB SSD** (119.2 GiB) already in it; was running Ubuntu Studio. 128 GB is plenty for
  gleaner; a bigger SSD only when big archives / map data need it. Spare: 2x Kingston
  KTA-MB1600S/4G. Run memtest86+ once Debian is on.
  Drive plan (14 Nov 2026): fit JC's spare **SanDisk Extreme II 480 GB** (SDSSDXP, 2.5" SATA)
  inside *before* installing Debian, since fatline will hold archives / backups. Check its
  health with `smartctl -a` after install. Spares: the 128 GB from the X200, several SanDisk
  250 GB SSDs (could go in USB cases for backups), a LaCie Rugged Mini (USB, probably a spinning
  disk; archives only, spin-down when idle, would be reformatted).
  **Build progress (14 Nov 2026):** Debian 13.7 (trixie) netinst installed, headless, user `jc`,
  ethernet `enp0s25`; USB stick written on exlo with dd. Mac reaches both with `ssh fatline` /
  `ssh exlo` (key login, ~/.ssh/config shortcuts). Done: avahi, lid ignore, consoleblank=60,
  unattended-upgrades, contrib enabled, TLP + tp-smapi-dkms with 40/80 thresholds active
  (needed `options thinkpad_ec force_io=1`). Reboot test passed; deploy key + clone done;
  gleaner moved and running. **Checks done (14–15 Nov 2026):** memtest86+ 3 full passes, 0 errors
  (~10 h); SSD SMART PASSED (0 reallocated, avg erase count 33, spare 100%, 1,076 h; baseline
  Total_Bad_Block 582, watch it doesn't grow; 810 past unexpected power losses); smartd now
  monitors it. BIOS has **no** "Power On with AC Attach" (only SpeedStep "Mode for AC/battery"),
  so after a long power cut fatline stays off until the power button is pressed. Still to do:
  genuine battery. btop installed (15 Nov 2026). **`fatline` command** (`fatline/fatline`, bash,
  0.1.0, linked into `~/.local/bin`): status, recent, today, log, restart, update, health, learn;
  each job echoes the real commands in grey, because JC wants to *learn* the command line from
  it (keep that teaching style when extending it). Ideas JC liked, not built: a login screen
  (motd) showing what gleaner delivered since last login, Gemini/w3m small-web browsing.
  **Location / remote access (15 Nov 2026):** fatline will live in JC's **office at the gallery**
  (work network; advised to check with IT, ideally a guest network/segment: fatline only needs
  outbound internet). Remote access: **Tailscale** for the Mac and exlo (outbound only, no ports
  opened; disable key expiry for fatline); JC wants to **migrate to Headscale** (self-hosted
  coordination server) when the time is right. Possible extra: a `!fatline` status command in
  Discord via gleaner.
  **Tailscale set up (15 Nov 2026):** fatline (100.90.163.115) and the personal MacBook joined
  (tailnet login chosen by JC; fatline needed `apt install curl` first; the Mac app's sign-in
  button did nothing, so `/Applications/Tailscale.app/Contents/MacOS/Tailscale up` gave the link).
  Personal MacBook: `ssh fatline` → HostName `fatline` (MagicDNS), works anywhere. Still to do:
  disable key expiry for fatline (admin console), Tailscale on the work laptop (and repoint its
  `fatline.local` shortcut to `fatline`), Tailscale on exlo.
  Battery: fatline's is an **unbranded clone** (label 10.8 V 5200 mAh 56.2 Wh; chip claims SANYO,
  48.8 Wh, 23 cycles, so the figures are likely fake). Stuck at 36%, won't charge even with
  `tlp fullcharge` (light green). exlo had a similar problem. JC will source a genuine Lenovo
  battery (fits X200 and X200s); fatline runs on mains meanwhile.
  Software side ready (11 Nov 2026): step-by-step guide in `fatline/README.md` (Debian netinst,
  no desktop, SSH as `fatline.local` via avahi, lid ignore, consoleblank, unattended-upgrades,
  TLP 40/80 via tp-smapi-dkms, read-only GitHub deploy key, `scp -r ~/.gleaner`),
  `gleaner/service.sh` now does Linux too (systemd user service + linger; log via journalctl),
  and `gleaner/dropbox_login.py` makes `~/.gleaner/dropbox.env` (same Dropbox app as cyby's
  KOReader; needs files.content.write). On fatline gleaner lives in `~/blue-sky-harvest/gleaner`
  and updates with `git pull && bash service.sh restart`.
- **exlomax**: high-spec Windows 11 Pro PC in JC's office (department-owned, full permission;
  reached over SSH from the MacBook). Ryzen 9 5900X (12 cores / 24 threads), 32 GB RAM,
  RTX 3080 Ti (12 GB), Python 3.12, ~1.36 TB free on D: (Oct 2026). Already holds a copy of
  exlo's Wikipedia ZIM (`wikipedia_en_all_maxi_2026-08.zim`). **Not part of Blue Sky
  Harvest's infrastructure**: only for heavy one-off processing during the build (e.g. the
  Wikipedia dictionary, map rendering). Nothing should depend on it running. Specs come
  from the WIKISTACK repo (docs/HANDOVER.md).
- **H2T**: Heltec T114 with GPS, running **MeshCore** (not Meshtastic; read it with meshcore-cli / the `meshcore` Python package). Mesh messaging rejected; GPS for exlo is the use.
- **Heltec WiFi LoRa 32 V4** dev kit with antenna (ESP32-S3, LoRa, OLED): spare, no job yet.
  Parked with the H2T for #off-grid; maybe a small gleaner status display for fatline one day.
- **USB dual-band Wi-Fi adapter** ("600 Mbps", chipset unknown): for exlo's own hotspot for
  cyby (second card, so exlo can stay connected while serving cyby). Check the chip with
  `lsusb` on exlo before relying on it. Not needed on fatline (ethernet + built-in Wi-Fi).
- **iPod** (generation unknown, check model number A1136 / A1238): idea is Rockbox + SD mod.
- GitHub account houseofsaturn (repos: wikistack, blue-sky-harvest). JC's 2FA currently lives
  on his work MacBook; he's advised to move it to a phone authenticator app.

## Next
1. Wikipedia dictionary for cyby: run `tools/wikidict.py` on exlomax (it already has the ZIM).
   **On hold until JC is back in the office** (14 Nov 2026); he chose exlomax over his MacBooks.
   Script now prints pip install hints for Mac/Windows; use `--zim D:\...\wikipedia_en_all_maxi_2026-08.zim`.
2. ~~Set up fatline and move gleaner to it~~ done 14 Nov 2026. Small fatline leftovers above.
3. Map atlases: `#maps` channel, greyscale PDF atlases from OpenStreetMap, rendered on the server.
5. exlo off-grid: GPS from the H2T, exlo's own Wi-Fi hotspot so cyby can collect from exlo
   away from home, local maps, a daily briefing card (sunrise/sunset, moon, saved forecast,
   barometer via a BME280, tide tables fetched ahead).
   **Progress (14 Nov 2026, #off-grid):** H2T now belongs to exlo (the phone has its own GPS; the
   Heltec V4 can be the phone's BLE board later). Reflashed over SSH to MeshCore **companion USB
   v1.18.0** (`Heltec_t114_companion_radio_usb-v1.18.0-81dbae5.zip`) with `adafruit-nrfutil dfu
   serial ... -p /dev/ttyACM0 -b 115200 --singlebank --touch 1200` (the 1200-baud touch opens the
   *serial* bootloader, not the UF2 drive; the drive needs a physical double-press). Tools in
   `~/offgrid/venv` (meshcore-cli, adafruit-nrfutil). `meshcli -s /dev/ttyACM0 infos` answers
   (node name jcjcjcjc) with adv_lat/adv_lon. GPS on/off is a custom var: `get custom`, `set gps 1`.
   **GPS fix confirmed** (14 Nov 2026: H2T clock correct after a while by the window).
   `offgrid/where.py` (0.1.0) reads position + clock and saves `~/offgrid/state/where.json`
   (fresh only if the H2T clock agrees with exlo's). Next: the briefing card (sun, moon first).
   Still to ask: which coast for tides. Hotspot needs the USB dongle (check its chip with `lsusb`).
6. #readings auto-fixing books with no working table of contents (mobi2epub, Calibre).

Idea in discussion (ctx.fm chat, 12 Nov 2026): **music conversations in #listenings**. gleaner answers
"artists connected to Milford Graves", "who mattered in 70s free jazz" from Wikipedia (links,
infoboxes, link-back / shared-link ranking). JC always names the artist or topic; gleaner does **not**
read "what's on rotation" as a starting point (decided 12 Nov 2026). ctx has two jobs only: queue
the pick JC reacts to, and mark or skip suggestions already in his queue or collection.
**No AI in the final build** (JC's decision): every suggestion comes with the Wikipedia sentence that
connects it.
**A command language, not a chatbot** (JC, 12 Nov 2026): gleaner recognises a small, fixed set of request
templates (e.g. "define X", "connected to X", "N records of X"), strips filler, looks the subject up by
title, and does one job per template. Unknown phrasing gets the list of forms it knows (and is logged so
we can decide what to teach next). JC wants to learn its language like a command line: deliberate,
focused questions fit the slow, calm network. Keep the vocabulary small and predictable. "Primer" EPUBs for cyby (a calm, finished reading pack through several articles) are **on ice**
until the conversations work.
**Prototype built (12 Nov 2026): `tools/connections.py`** (libzim + lxml only; borrows WIKISTACK's skip
lists, link handling and LinkJudge scoring rather than importing wikistack.py). `python3 connections.py
"Milford Graves" [--why] [--all]` → links ranked by mentions, lead, infobox, link-back, shared links;
grouped as musicians/groups, records, labels, scenes (people/places/other with --all), each with its
sentence. Tests: `tools/tests/test_connections.py` (made-up music archive + crash run over a real .zim;
3,821 climate-mini articles, 0 errors). Repo cloned on exlo at `~/blue-sky-harvest` (update: `git pull`).
**First real run (16 Nov 2026, exlo, maxi ZIM): "Milford Graves" read 138 linked articles in 3.6 s.**
Ranking looked right (NYAQ, Ayler, Cyrille, Logan, Pullen, W. Parker; Graves/Pullen Yale concert,
Bäbi, NYAQ albums; Tzadik, DIW, ESP; free jazz). 0.2 fixes: infobox clean-up (CSS, hlists, hidden
dates, ref marks), sentences split after "." inside brackets / quotes, "rel." etc., reason sentence
centred on the name, records no longer tie (shared cap 0.5). Open: ESP-Disk ranks low (no link back
though 6 mentions); JC to judge who's missing. Second run (0.2, --top 15) looked good to JC.
Parked: repeated reason sentences (several links share one sentence, e.g. the opening; fix idea: use
another sentence, else the target's own first line). Scores = mentioned 0.30 + lead 0.15 + infobox
0.10 + links back 0.25 + shared 0.20 (explained to JC; hide numbers in Discord).
**Next (JC at exlomax, 16 Nov 2026 pm): build the music database on exlomax** from Wikidata (facts:
genre, label, instrument, member of, active years; truthy dump ~40 GB bz2) + Wikipedia categories +
MusicBrainz (CC0; performer credits, member-of-band, collaboration). Output: one small file for exlo /
fatline. Downloads are big: start them first.
**Done 16 Nov 2026:** downloads on exlomax in `D:\musicdb\downloads` (MB snapshot 20261114-002230:
mbdump 7.2 GB, derived 505 MB; enwiki page 2.25 GB, page_props 463 MB). **Wikidata dropped for now**
(huge, slow in plain Python; MusicBrainz covers most of it). `tools/musicdb/`: `build_musicdb.py`
(stdlib; resumable steps; unpack → wiki match via Q-ids → artists → rel → performer credits →
played-together pairs (≤12 performers per item) → instruments, genres → `music.db`), `musicdb.py`
(lookup), `test_musicdb.py` (made-up dumps in real formats; passes). Next: JC runs the build on
exlomax, then `musicdb.py "Milford Graves"`, then fold it into connections.py.

Idea in discussion (cyby chat, 14 Nov 2026): **look up later from cyby**. JC highlights a passage on
cyby, taps a button in KOReader's highlight menu, and it's queued (works offline); on the next sync the
gleanings plugin drops it in the Dropbox app folder and gleaner posts it to its own Discord channel
(quote, note, title, link to the original via the EPUB's DC:source, Wikipedia search link); react ✅
when done. Only what JC taps is sent, never all highlights. **gleaner is the one tool** (JC): this is
gleaner working in the other direction, not a new tool; channels are doors into gleaner, and this one is
separate from #gleanings because the job differs. Names are **undecided**: placeholders are button
"Look up later", channel `#lookups`, folder `lookups/`. JC is unsure "glean" is the right word for it;
rejected so far: seek/#seekings, harvest words (#sheaves, #threshing…), #marginalia, Snow Crash nouns
(#hypercards, #intel). Reading-notes button comes later, on the same pipe. **Not built yet.**

Parked: saving Wikipedia pictures from cyby (KOReader plugin → #sleepy-screens or a folder;
on ice, 14 Nov 2026); iPod (Rockbox, SD mod, offline music shelf, listening notes); cyby highlights to a
reading-notes forum; weekly reading note; WIKISTACK daily cards on cyby; SSH to cyby (timed
out, unresolved); Winlink / amateur radio (JC wants a Foundation licence some day);
Calibre wireless to KOReader.
