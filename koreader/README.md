# gleanings.koplugin

Cyby's half of gleaner. It downloads new files from the `cyby` Dropbox app folder into
`documents/gleanings`, ebooks from `books/` into `documents/books`, and mirrors `screensavers/` into `/mnt/us/screensavers` for sleep screens.

- Syncs by itself when Wi-Fi connects or Cyby wakes (Tools → Gleanings → Sync automatically).
- Downloads by Dropbox file id, so non-English filenames work, and remembers what it has
  delivered, so files you delete on Cyby don't come back.
- Use **Tools → Gleanings → Sync now**, not KOReader's Cloud storage → Synchronize now
  (that one re-downloads deleted files).
- Tools → Gleanings → "Use #sleepy-screens images as sleep screen" switches KOReader's sleep
  screen to a random image from the folder.

**Install:** copy `gleanings.koplugin/` to `koreader/plugins/` on the Kindle and restart
KOReader. It uses the Dropbox server named `cyby` in KOReader's Cloud storage, which needs a
sync folder set (`/mnt/us/documents/gleanings`).
