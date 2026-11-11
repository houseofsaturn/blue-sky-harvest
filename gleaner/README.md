# gleaner

The Discord courier for **cyby**. It watches five channels on Blue Sky Harvest.

### #gleanings → cyby's library
| You post | cyby gets |
|---|---|
| a link to an article | a clean EPUB: title, byline, text, greyscale images |
| a link to a PDF or EPUB | the file, as-is (up to 60 MB) |
| an attached PDF or EPUB | the file, as-is (within Discord's upload limit) |
| an attached .txt / .md / .html | an EPUB |
| a block of pasted text (25+ words) | an EPUB, titled from its first line |

Short chat lines are ignored.

### #sleepy-screens → cyby's sleep screens
Post images (attached or linked). Each becomes a 758×1024 greyscale PNG: never cropped or
enlarged, at least a 5 mm white margin, usually placed towards a corner (one in five centred).
Put the word `centre` in the message to centre it. Delete the post to delete the sleep screen.

### #readings → cyby's books folder
Attach an ebook (EPUB, PDF, MOBI, AZW3, FB2, DjVu, CBZ, TXT and other formats KOReader opens),
or post a direct download link (up to 60 MB). It's passed through untouched, keeping its own
filename (made plain ASCII), and cyby files it in `documents/readings`. Files too big for Discord
can be dropped straight into Dropbox → Apps → cyby → readings.
Cover and metadata files posted with a book (Calibre's `.opf`, `cover.jpg`) are left out quietly.

### #sstacks → cyby's sstacks folder
A few chosen Substack writers. Post a Substack link (`name.substack.com`, a post, or
`substack.com/@writer`) to subscribe. gleaner checks every 3 hours and sends each new **free**
post as a clean EPUB; paid-only posts are skipped with a 🔒 note, podcasts and threads ignored.
Only posts published after you subscribe, never a back catalogue.

`!list` · `!unsubscribe name` · `!cap 3` (at most 3 a week) · `!cap` (this week so far) ·
`!cap off` · `!check` (look now) · `!recent`. Over the cap, posts wait for next week, but never
more than a week's worth: the oldest waiting is let go. State lives in `~/.gleaner/sstacks.json`.

Try a publication without Discord: `.venv/bin/python gleaner.py --sstack https://name.substack.com ~/Desktop/test`

### #listenings → ctx.fm
Post a music link (Bandcamp, YouTube and so on) and it is added to the ctx.fm queue.
Include the word `collection` to add it to the collection instead.

### Reactions and commands
⏳ working · ✅ done · ⚠️ partly done · ❌ failed. Anything posted while gleaner was
offline (the Mac asleep, say) is picked up when it comes back, up to 7 days.

`!help` (per channel), `!ping`, `!recent`, `!count`, `!ctx`.

## Set up (Mac)

```bash
cd ~/gleaner
bash setup.sh             # once: installs libraries, asks for the Discord token
bash service.sh install   # run in the background, start at login, restart if it stops
```

`service.sh` also has `status`, `log`, `restart` (after updating gleaner.py) and `uninstall`.
`bash run.sh` runs it in a Terminal window instead.

### Settings: `~/.gleaner/gleaner.env` (private, never commit it)

```
DISCORD_TOKEN=…
CHANNEL=gleanings
SCREENSAVER_CHANNEL=sleepy-screens
LISTEN_CHANNEL=listenings
BOOKS_CHANNEL=readings
SSTACKS_CHANNEL=sstacks
CTX_API_KEY=ctx_…
MODE=local
# CTX_BASE_URL=https://ctx.fm
# OUTPUT_DIR=~/Library/CloudStorage/Dropbox/Apps/cyby
# DROPBOX_SUBFOLDER=
```

Save secrets without them showing on screen (zsh):
`read -s "K?ctx API key: "; echo "CTX_API_KEY=$K" >> ~/.gleaner/gleaner.env; unset K`

## Test a conversion without Discord

```bash
.venv/bin/python gleaner.py --test "https://some.site/article" ~/Desktop/gleaner-test
```

## Moving to the Raspberry Pi (or exlo)

1. Clone this repository and copy `~/.gleaner/` across.
2. In `~/.gleaner/gleaner.env` set `MODE=api`. gleaner then uploads with the Dropbox key in
   `~/.gleaner/dropbox.env`, so no Dropbox app is needed.
3. `bash setup.sh`, then run it as a service (a systemd unit on Linux, to be written).
4. Stop the Mac's copy (`bash service.sh uninstall`) so only one gleaner answers.

On Debian, if `pip` fails building `lxml` or `Pillow`, install them first:
`sudo apt install python3-lxml python3-pil python3-venv`, then create the venv with
`python3 -m venv --system-site-packages .venv`.
