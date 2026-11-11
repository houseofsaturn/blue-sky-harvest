# fatline

The always-on home server for Blue Sky Harvest. Named after the instant interstellar
link in *Hyperion*. It's JC's spare **ThinkPad X200**, exlo's twin, given a second life:
free, quiet, low power, with its own battery as a built-in UPS.

Jobs, in order:
1. **Run gleaner** around the clock (`MODE=api`), so the MacBook can sleep and cyby still
   gets its post.
2. Later: build map atlases for #maps, keep master copies of the big archives (Wikipedia
   ZIM, dictionaries) fresh, and top exlo up when it's home.

It runs **Debian with no desktop**. JC works on it from the MacBook over SSH
(`ssh fatline.local`), so after setup it needs no screen or keyboard and lives with the
lid shut.

Commands below are run either **on the Mac** (Terminal, zsh) or **on fatline** (over SSH,
bash). Each step says which.

---

## 0. Check the hardware

Power it on and press **F1** at the ThinkPad logo to open BIOS Setup. Note:
- **Memory** (Main / Config screen): 2 GB is enough for gleaner; 4 GB+ is comfortable for maps.
- **Hard drive**: what's in the bay now (look on the label once it's out). An **SSD** is
  strongly recommended: silent, cooler, much less power, and doesn't mind running 24/7.
  Any 2.5" SATA SSD of 7 mm thickness fits; 500 GB–1 TB leaves room for archives.
  (The X200's SATA port is slower than a modern SSD, which doesn't matter here.)
- While in BIOS: under **Config → Power** (wording varies), turn on
  **"Power On with AC Attach"** if it's there, so fatline starts by itself after a power cut
  that outlasts the battery.
- Check the battery holds some charge. A tired battery is fine: it only needs to cover blips.

## 1. Install Debian (once)

**On the Mac:**
1. Download the Debian **netinst** image for **amd64** from debian.org (the "small
   installation image").
2. Write it to a USB stick with balenaEtcher (simplest) and plug it into fatline.
3. Plug fatline into the router with an **ethernet cable** for the install (more reliable
   than Wi-Fi for an always-on box; Wi-Fi can be set up later if it has to live elsewhere).

**On fatline:** boot from USB (**F12** at the ThinkPad logo → USB). In the installer:
- Choose **Install** (the plain text installer is fine).
- **Hostname:** `fatline` · Domain: leave blank.
- **Root password:** leave **blank**. Your own user then gets `sudo` (admin) rights.
- **User:** your name / username (e.g. `jc`) and a strong password.
- **Partitioning:** Guided, use entire disk, all files in one partition.
- **Software selection:** untick *Debian desktop environment* and *GNOME*; tick
  **SSH server** and **standard system utilities**. Nothing else.
- Install GRUB to the disk when asked. Remove the USB stick and reboot.

Log in on fatline's own screen once and note its address: `ip -4 addr` (look for
`192.168.x.x`). From now on everything can be done from the Mac.

## 2. Reach it from the Mac by name, with a key instead of a password

**On fatline** (still at its own keyboard):
```bash
sudo apt update && sudo apt install -y avahi-daemon
```
That lets the Mac find it as `fatline.local`.

**On the Mac:**
```zsh
ls ~/.ssh/id_ed25519.pub || ssh-keygen -t ed25519      # make a key if you don't have one (Enter for defaults)
ssh-copy-id jc@fatline.local                            # use your fatline username; asks for the password once
ssh jc@fatline.local                                    # should now log straight in
```
To type just `ssh fatline`, add this to `~/.ssh/config` on the Mac:
```
Host fatline
  HostName fatline.local
  User jc
```

## 3. Make it a good always-on machine

**On fatline**, over SSH. Each block can be pasted whole.

Keep running with the lid shut:
```bash
sudo mkdir -p /etc/systemd/logind.conf.d
printf '[Login]\nHandleLidSwitch=ignore\nHandleLidSwitchExternalPower=ignore\nHandleLidSwitchDocked=ignore\n' \
  | sudo tee /etc/systemd/logind.conf.d/fatline-lid.conf
sudo systemctl restart systemd-logind
```

Turn the screen off after a minute of no typing (saves power and the backlight):
```bash
sudo sed -i 's/^GRUB_CMDLINE_LINUX_DEFAULT="\(.*\)"/GRUB_CMDLINE_LINUX_DEFAULT="\1 consoleblank=60"/' /etc/default/grub
sudo update-grub
```

Security updates install themselves:
```bash
sudo apt install -y unattended-upgrades
sudo dpkg-reconfigure -plow unattended-upgrades       # answer Yes
```

Battery care: keep it between 40% and 80% so it lasts for years as a UPS. The X200 needs the
`tp_smapi` driver for charge limits, which is in Debian's **contrib** section:
```bash
sudo sed -i 's/ main\b/ main contrib/' /etc/apt/sources.list   # if your sources use a .sources file, see note below
sudo apt update
sudo apt install -y tlp linux-headers-amd64 tp-smapi-dkms
printf 'START_CHARGE_THRESH_BAT0=40\nSTOP_CHARGE_THRESH_BAT0=80\n' | sudo tee /etc/tlp.d/50-fatline.conf
sudo tlp start && sudo tlp-stat -b | grep -i thresh
```
Note: if `/etc/apt/sources.list` is empty and there's a file in `/etc/apt/sources.list.d/`
ending in `.sources` instead, ask in the fatline chat and we'll edit that.

Reboot and check it comes back on its own: `sudo reboot`, wait a minute, `ssh fatline`.

## 4. Get the Blue Sky Harvest code onto fatline

The repo is private, so fatline gets its own **read-only** key for it (a GitHub "deploy key"):
it can download updates but can't change anything on GitHub.

**On fatline:**
```bash
sudo apt install -y git python3-venv
ssh-keygen -t ed25519 -C fatline -f ~/.ssh/github -N ""
cat ~/.ssh/github.pub
printf 'Host github.com\n  IdentityFile ~/.ssh/github\n' >> ~/.ssh/config
```
The `.pub` line is a **public** key: safe to copy around. On GitHub, open
houseofsaturn/blue-sky-harvest → **Settings → Deploy keys → Add deploy key**, title
`fatline`, paste it, leave *Allow write access* **unticked**, Add.

**On fatline:**
```bash
git clone git@github.com:houseofsaturn/blue-sky-harvest.git ~/blue-sky-harvest
```
(answer `yes` to the fingerprint question the first time). Updating later is just
`cd ~/blue-sky-harvest && git pull`.

## 5. Move gleaner across

**a. Copy gleaner's settings from the Mac** (Discord token, ctx.fm key, #sstacks
subscriptions and cap). They travel inside SSH, never through chat. **On the Mac:**
```zsh
scp -r ~/.gleaner fatline:
```

**b. Switch it to Dropbox API mode. On fatline:**
```bash
chmod 700 ~/.gleaner && chmod 600 ~/.gleaner/*
sed -i 's/^MODE=.*/MODE=api/' ~/.gleaner/gleaner.env
sed -i 's/^OUTPUT_DIR=/# OUTPUT_DIR=/' ~/.gleaner/gleaner.env
grep MODE ~/.gleaner/gleaner.env                       # should say MODE=api
```

**c. Log in to Dropbox** with the same Dropbox app cyby uses (the one whose folder is
Apps/cyby). First, on the Mac's browser: dropbox.com/developers/apps → that app →
**Permissions** tab → tick `files.metadata.read`, `files.content.read`,
`files.content.write` → **Submit**. Keep the **Settings** tab open for the app key and
secret (press *Show* for the secret). **On fatline:**
```bash
cd ~/blue-sky-harvest/gleaner
python3 dropbox_login.py
```
It asks for the key and secret (hidden as you paste), gives you a link to open on the Mac,
then asks for the code Dropbox shows. It finishes by listing the folders it can see.
You should see `gleanings`, `readings`, `screensavers`, `sstacks`.
(If `~/.gleaner/dropbox.env` already came across from the Mac, just run
`python3 dropbox_login.py --check`.)

**d. Install gleaner's libraries. On fatline:**
```bash
bash setup.sh
```

**e. The switch-over.** Only one gleaner may run at a time, or posts get handled twice.
Anything posted in the gap is picked up when fatline's copy starts.

On the **Mac**:
```zsh
cd ~/gleaner && bash service.sh uninstall
```
On **fatline**:
```bash
cd ~/blue-sky-harvest/gleaner && bash service.sh install
```
The status should show gleaner logged in with its version and channel list.

**f. Test.** In Discord: `!ping` in #gleanings, then post an article. On cyby: Tools →
Gleanings → Sync now. Check #sleepy-screens, #readings, #sstacks (`!list`, `!cap`) and
#listenings too.

**g. Tidy the Mac** once a few days have gone well: the `~/gleaner` folder and
`~/.gleaner` on the Mac can go (fatline has the master copy of the settings; GitHub has
the code). Back up `~/.gleaner` somewhere private first if you like.

## Everyday use

All on fatline (`ssh fatline`, then `cd ~/blue-sky-harvest/gleaner`):

| What | Command |
|---|---|
| Is it running? | `bash service.sh status` |
| Watch the log | `bash service.sh log` (Ctrl+C stops watching, not gleaner) |
| Update gleaner after a change on GitHub | `git pull && bash service.sh restart` |
| Check the version | `grep __version__ gleaner.py` |
| Check Dropbox | `python3 dropbox_login.py --check` |
| Battery | `sudo tlp-stat -b` |
| Shut down safely | `sudo poweroff` |
