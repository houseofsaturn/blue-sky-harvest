# offgrid: exlo off the grid

Tools that run on **exlo** (ThinkPad X200s) and need no internet. Chat: #off-grid.

## The H2T (GPS)

The H2T is a Heltec T114 running MeshCore **companion USB** firmware (v1.18.0), plugged into
exlo by USB (`/dev/ttyACM0`). Its only job here is to tell exlo where it is.

Tools live in a private Python folder on exlo, `~/offgrid/venv`:

```
sudo apt install -y python3-venv
python3 -m venv ~/offgrid/venv
~/offgrid/venv/bin/pip install meshcore-cli adafruit-nrfutil
```

Useful commands:

```
~/offgrid/venv/bin/meshcli -s /dev/ttyACM0 infos        # name, position (adv_lat / adv_lon)
~/offgrid/venv/bin/meshcli -s /dev/ttyACM0 clock        # right time = GPS has a fix
~/offgrid/venv/bin/meshcli -s /dev/ttyACM0 get custom   # gps on/off
~/offgrid/venv/bin/meshcli -s /dev/ttyACM0 set gps 1
```

Reflashing over SSH (no button press needed):

```
~/offgrid/venv/bin/adafruit-nrfutil --verbose dfu serial \
  --package Heltec_t114_companion_radio_usb-<version>.zip \
  -p /dev/ttyACM0 -b 115200 --singlebank --touch 1200
```

The `.zip` comes from MeshCore's GitHub releases (`companion-v…`). The 1200-baud touch opens
the serial bootloader; the drag-and-drop UF2 drive only appears after a physical double-press
of reset.

## where.py

Asks the H2T for its position and clock and saves `~/offgrid/state/where.json`.

```
~/offgrid/venv/bin/python ~/offgrid/where.py          # read, save, print
~/offgrid/venv/bin/python ~/offgrid/where.py --show   # print what's saved
```

The H2T has no clock battery, so its clock is only right when the GPS has a fix. If its clock
agrees with exlo's, the position is marked **fresh**. A stale reading never overwrites the last
fresh fix.
