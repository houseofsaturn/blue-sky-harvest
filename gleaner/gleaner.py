#!/usr/bin/env python3
"""
gleaner — a Discord courier for Cyby (a jailbroken Kindle running KOReader).

Post in #gleanings (in Blue Sky Harvest):
  * a link to an article      -> cleaned up and bound into an EPUB
  * a link to a PDF           -> kept as a PDF
  * an attached PDF or EPUB   -> passed through as-is
  * an attached .txt / .md / .html file, or a block of pasted text
                              -> bound into an EPUB

Finished files are written to the Dropbox app folder that Cyby syncs from:
  * "local" mode (default): saved straight into the Dropbox desktop app's
    folder, e.g. ~/Library/CloudStorage/Dropbox/Apps/cyby
  * "api" mode: uploaded with the Dropbox API, for machines without the
    desktop app (a Raspberry Pi, exlo)

Commands in the channel:
  !help     what gleaner understands
  !recent   the last few files delivered
  !ping     check gleaner is awake

Settings live in ~/.gleaner/gleaner.env (and ~/.gleaner/dropbox.env for
api mode). See README.md.
"""

from __future__ import annotations

import asyncio
import datetime as dt
import html
import io
import json
import logging
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from dataclasses import dataclass, field
from pathlib import Path

import discord
import trafilatura
from ebooklib import epub
from PIL import Image

__version__ = "0.9.0"

CONFIG_DIR = Path(os.environ.get("GLEANER_CONFIG_DIR", Path.home() / ".gleaner"))
USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_0) AppleWebKit/605.1.15 "
    "(KHTML, like Gecko) Version/17.0 Safari/605.1.15"
)
URL_RE = re.compile(r"https?://[^\s<>\"']+")
MAX_DOWNLOAD = 60 * 1024 * 1024        # 60 MB per page or file
MAX_IMAGES = 40                          # per article
IMAGE_MAX_WIDTH = 758                    # Paperwhite 2 screen width
MIN_TEXT_WORDS = 25                      # pasted text shorter than this is ignored
CATCHUP_DAYS = 7                         # on waking, look back this far for missed posts
CATCHUP_LIMIT = 200                      # ...through at most this many messages

log = logging.getLogger("gleaner")


# --------------------------------------------------------------------------
# settings
# --------------------------------------------------------------------------

def load_env_file(path: Path) -> dict:
    values = {}
    if not path.exists():
        return values
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values


@dataclass
class Settings:
    discord_token: str
    channel_name: str = "gleanings"
    screens_channel: str = "screensaver"
    listen_channel: str = "listening"
    books_channel: str = "readings"
    sstacks_channel: str = "sstacks"
    ctx_api_key: str = ""
    ctx_base: str = "https://ctx.fm"
    mode: str = "local"                  # "local" or "api"
    output_dir: Path = field(default_factory=lambda: default_dropbox_dir())
    dropbox_subfolder: str = ""          # e.g. "articles"; "" = top of app folder
    dropbox_app_key: str = ""
    dropbox_app_secret: str = ""
    dropbox_refresh: str = ""

    @classmethod
    def load(cls) -> "Settings":
        env = load_env_file(CONFIG_DIR / "gleaner.env")
        env.update({k: v for k, v in os.environ.items() if k.startswith("GLEANER_")})
        token = env.get("DISCORD_TOKEN") or env.get("GLEANER_DISCORD_TOKEN", "")
        if not token:
            sys.exit(f"No DISCORD_TOKEN found in {CONFIG_DIR / 'gleaner.env'}")
        s = cls(discord_token=token)
        s.channel_name = env.get("CHANNEL", s.channel_name).lstrip("#")
        s.screens_channel = env.get("SCREENSAVER_CHANNEL", s.screens_channel).lstrip("#")
        s.listen_channel = env.get("LISTEN_CHANNEL", s.listen_channel).lstrip("#")
        s.books_channel = env.get("BOOKS_CHANNEL", s.books_channel).lstrip("#")
        s.sstacks_channel = env.get("SSTACKS_CHANNEL", s.sstacks_channel).lstrip("#")
        s.ctx_api_key = env.get("CTX_API_KEY", "")
        s.ctx_base = env.get("CTX_BASE_URL", s.ctx_base).rstrip("/")
        s.mode = env.get("MODE", s.mode).lower()
        if env.get("OUTPUT_DIR"):
            s.output_dir = Path(os.path.expanduser(env["OUTPUT_DIR"]))
        s.dropbox_subfolder = env.get("DROPBOX_SUBFOLDER", "").strip("/")
        if s.mode == "api":
            dbx = load_env_file(CONFIG_DIR / "dropbox.env")
            s.dropbox_app_key = dbx.get("APPKEY", "")
            s.dropbox_app_secret = dbx.get("APPSECRET", "")
            s.dropbox_refresh = dbx.get("REFRESH", "")
            if not (s.dropbox_app_key and s.dropbox_app_secret and s.dropbox_refresh):
                sys.exit(f"MODE=api needs APPKEY, APPSECRET and REFRESH in {CONFIG_DIR / 'dropbox.env'}")
        return s


def default_dropbox_dir() -> Path:
    home = Path.home()
    for candidate in (
        home / "Library/CloudStorage/Dropbox/Apps/cyby",
        home / "Dropbox/Apps/cyby",
    ):
        if candidate.exists():
            return candidate
    return home / "Library/CloudStorage/Dropbox/Apps/cyby"


# --------------------------------------------------------------------------
# delivery: local Dropbox folder or Dropbox API
# --------------------------------------------------------------------------

class Delivery:
    def __init__(self, settings: Settings):
        self.s = settings
        self._access_token = ""
        self._access_expiry = dt.datetime.min

    def describe(self) -> str:
        if self.s.mode == "api":
            return f"Dropbox API → /{self.s.dropbox_subfolder}" if self.s.dropbox_subfolder else "Dropbox API → app folder"
        return str(self.target_dir())

    def target_dir(self) -> Path:
        d = self.s.output_dir
        if self.s.dropbox_subfolder:
            d = d / self.s.dropbox_subfolder
        return d

    def save(self, filename: str, data: bytes, subfolder: str = "") -> str:
        """Store the file, returning the name it was stored under."""
        if self.s.mode == "api":
            return self._upload(filename, data, subfolder)
        folder = self.target_dir() / subfolder if subfolder else self.target_dir()
        folder.mkdir(parents=True, exist_ok=True)
        path = unique_path(folder / filename)
        tmp = path.with_name("." + path.name + ".part")
        tmp.write_bytes(data)
        tmp.rename(path)                 # appear complete, never half-written
        return path.name

    def recent(self, n: int = 8, subfolder: str = "") -> list[str]:
        if self.s.mode == "api":
            return self._list_recent(n, subfolder)
        folder = self.target_dir() / subfolder if subfolder else self.target_dir()
        if not folder.exists():
            return []
        files = [p for p in folder.iterdir() if p.is_file() and not p.name.startswith(".")]
        files.sort(key=lambda p: p.stat().st_mtime, reverse=True)
        return [p.name for p in files[:n]]

    def count(self, subfolder: str = "") -> int:
        return len(self.recent(100000, subfolder))

    def delete_prefix(self, prefix: str, subfolder: str) -> int:
        """Remove files in `subfolder` whose names start with `prefix`."""
        if self.s.mode == "api":
            names = [n for n in self._list_recent(100000, subfolder) if n.startswith(prefix)]
            for n in names:
                self._api("files/delete_v2", {"path": self._remote_path(n, subfolder)})
            return len(names)
        folder = self.target_dir() / subfolder
        if not folder.exists():
            return 0
        gone = 0
        for p in folder.iterdir():
            if p.is_file() and p.name.startswith(prefix):
                p.unlink()
                gone += 1
        return gone

    # ---- Dropbox API ----
    def _token(self) -> str:
        if self._access_token and dt.datetime.now() < self._access_expiry:
            return self._access_token
        body = urllib.parse.urlencode({
            "grant_type": "refresh_token",
            "refresh_token": self.s.dropbox_refresh,
            "client_id": self.s.dropbox_app_key,
            "client_secret": self.s.dropbox_app_secret,
        }).encode()
        with urllib.request.urlopen("https://api.dropbox.com/oauth2/token", body, timeout=30) as r:
            payload = json.load(r)
        self._access_token = payload["access_token"]
        self._access_expiry = dt.datetime.now() + dt.timedelta(seconds=int(payload.get("expires_in", 14400)) - 300)
        return self._access_token

    def _remote_folder(self, subfolder: str = "") -> str:
        parts = [p for p in (self.s.dropbox_subfolder, subfolder) if p]
        return "/" + "/".join(parts) if parts else ""

    def _remote_path(self, filename: str, subfolder: str = "") -> str:
        return f"{self._remote_folder(subfolder)}/{filename}"

    def _api(self, endpoint: str, payload: dict) -> dict:
        req = urllib.request.Request(
            f"https://api.dropboxapi.com/2/{endpoint}",
            data=json.dumps(payload).encode(),
            headers={"Authorization": f"Bearer {self._token()}", "Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.load(r)

    def _upload(self, filename: str, data: bytes, subfolder: str = "") -> str:
        arg = {"path": self._remote_path(filename, subfolder), "mode": "add", "autorename": True, "mute": True}
        req = urllib.request.Request(
            "https://content.dropboxapi.com/2/files/upload",
            data=data,
            headers={
                "Authorization": f"Bearer {self._token()}",
                "Dropbox-API-Arg": json.dumps(arg, ensure_ascii=True),
                "Content-Type": "application/octet-stream",
            },
        )
        with urllib.request.urlopen(req, timeout=120) as r:
            return json.load(r)["name"]

    def _list_recent(self, n: int, subfolder: str = "") -> list[str]:
        try:
            data = self._api("files/list_folder", {"path": self._remote_folder(subfolder)})
        except urllib.error.HTTPError as e:
            if e.code == 409:            # folder doesn't exist yet
                return []
            raise
        entries = list(data["entries"])
        while data.get("has_more"):
            data = self._api("files/list_folder/continue", {"cursor": data["cursor"]})
            entries += data["entries"]
        entries = [e for e in entries if e[".tag"] == "file"]
        entries.sort(key=lambda e: e.get("server_modified", ""), reverse=True)
        return [e["name"] for e in entries[:n]]


def unique_path(path: Path) -> Path:
    if not path.exists():
        return path
    for i in range(2, 1000):
        candidate = path.with_name(f"{path.stem} ({i}){path.suffix}")
        if not candidate.exists():
            return candidate
    return path.with_name(f"{path.stem} {uuid.uuid4().hex[:6]}{path.suffix}")


# --------------------------------------------------------------------------
# fetching
# --------------------------------------------------------------------------

class GleanError(Exception):
    """A problem worth telling the user about in plain words."""


def http_get(url: str, accept: str = "*/*") -> tuple[bytes, str, str]:
    """Return (body, content_type, final_url)."""
    req = urllib.request.Request(url, headers={
        "User-Agent": USER_AGENT,
        "Accept": accept,
        "Accept-Language": "en-GB,en;q=0.9",
    })
    try:
        with urllib.request.urlopen(req, timeout=45) as r:
            body = r.read(MAX_DOWNLOAD + 1)
            if len(body) > MAX_DOWNLOAD:
                raise GleanError("that file is over 60 MB, too big to send to Cyby")
            ctype = r.headers.get("Content-Type", "").split(";")[0].strip().lower()
            return body, ctype, r.geturl()
    except urllib.error.HTTPError as e:
        if e.code in (401, 402, 403):
            raise GleanError(f"the site refused access (HTTP {e.code}); it may be paywalled or blocking bots")
        if e.code == 404:
            raise GleanError("the page wasn't found (HTTP 404)")
        raise GleanError(f"the site returned an error (HTTP {e.code})")
    except urllib.error.URLError as e:
        raise GleanError(f"couldn't reach the site ({e.reason})")
    except TimeoutError:
        raise GleanError("the site took too long to respond")


def looks_like_pdf(url: str, ctype: str, body: bytes) -> bool:
    return ctype == "application/pdf" or body[:5] == b"%PDF-" or urllib.parse.urlparse(url).path.lower().endswith(".pdf")


# --------------------------------------------------------------------------
# article extraction
# --------------------------------------------------------------------------

@dataclass
class Article:
    title: str
    author: str = ""
    source: str = ""
    url: str = ""
    date: str = ""
    html_body: str = ""                  # clean XHTML fragment
    images: dict = field(default_factory=dict)   # placeholder src -> (filename, bytes)


def extract_article(page_html: str, url: str) -> Article:
    result = trafilatura.extract(
        page_html,
        url=url,
        output_format="xml",
        include_images=True,
        include_links=False,
        include_tables=True,
        include_formatting=True,
        favor_precision=True,
        with_metadata=True,
    )
    if not result:
        raise GleanError("couldn't find an article on that page (it may need JavaScript or a login)")
    meta = trafilatura.extract_metadata(page_html, default_url=url)
    title = (meta.title if meta and meta.title else "") or "Untitled article"
    sitename = meta.sitename if meta and meta.sitename else ""
    art = Article(
        title=tidy_title(clean_text(title), sitename),
        author=clean_text(meta.author) if meta and meta.author else "",
        source=clean_text(meta.sitename) if meta and meta.sitename else urllib.parse.urlparse(url).netloc.removeprefix("www."),
        url=url,
        date=meta.date if meta and meta.date else "",
    )
    art.html_body = xml_to_xhtml(result, art)
    if len(re.sub(r"<[^>]+>", " ", art.html_body).split()) < 60:
        raise GleanError("only found a few lines of text on that page (it may be paywalled or need JavaScript)")
    return art


def clean_text(s: str) -> str:
    return re.sub(r"\s+", " ", s or "").strip()


def tidy_title(title: str, sitename: str = "") -> str:
    """Drop trailing site names and dates: 'Story | DW | 19.01.2020' -> 'Story'."""
    def squash(s: str) -> str:
        return re.sub(r"[^a-z0-9]", "", s.lower().removeprefix("www.").split(".")[0] if "." in s and " " not in s else s.lower())

    site = squash(sitename)
    while True:
        m = re.match(r"^(.{6,}?)\s+(?:\||–|—|·|::)\s+([^|–—·]{1,40})$", title)
        if not m:
            m2 = re.match(r"^(.{6,}?)\s+-\s+([^-]{1,40})$", title)
            if m2 and site and (site in squash(m2.group(2)) or squash(m2.group(2)) in site):
                m = m2
        if not m:
            return title
        tail = m.group(2).strip().lower()
        is_site = bool(site) and bool(squash(tail)) and (site in squash(tail) or squash(tail) in site)
        is_date = bool(re.fullmatch(r"[\d./\- ]{6,12}", tail))
        if not (is_site or is_date or len(tail) <= 25):
            return title
        title = m.group(1).strip()


def xml_to_xhtml(xml_text: str, art: Article) -> str:
    """Convert trafilatura's XML output into a simple XHTML fragment."""
    from lxml import etree

    root = etree.fromstring(xml_text.encode("utf-8"), etree.XMLParser(recover=True, huge_tree=True))
    main = root.find("main") if root.find("main") is not None else root
    out: list[str] = []
    seen_title = clean_text(art.title).lower()

    def inline(el) -> str:
        parts = [html.escape(el.text or "")]
        for child in el:
            inner = inline(child)
            tag = child.tag
            if tag == "hi":
                rend = child.get("rend", "")
                if "#b" in rend:
                    inner = f"<strong>{inner}</strong>"
                elif "#i" in rend:
                    inner = f"<em>{inner}</em>"
                elif "#sup" in rend:
                    inner = f"<sup>{inner}</sup>"
                elif "#sub" in rend:
                    inner = f"<sub>{inner}</sub>"
                elif "#t" in rend:
                    inner = f"<code>{inner}</code>"
            elif tag == "lb":
                inner = "<br/>"
            elif tag == "ref":
                pass                     # links dropped: plain text reads better on e-ink
            elif tag == "code":
                inner = f"<code>{inner}</code>"
            parts.append(inner)
            parts.append(html.escape(child.tail or ""))
        return "".join(parts)

    def block(el):
        tag = el.tag
        if tag == "p":
            text = inline(el).strip()
            if text:
                out.append(f"<p>{text}</p>")
        elif tag == "head":
            text = inline(el).strip()
            if text and clean_text(re.sub(r"<[^>]+>", "", text)).lower() != seen_title:
                level = {"h1": 2, "h2": 2, "h3": 3, "h4": 4}.get(el.get("rend", "h2"), 3)
                out.append(f"<h{level}>{text}</h{level}>")
        elif tag == "quote":
            out.append("<blockquote>")
            if len(el):
                if el.text and el.text.strip():
                    out.append(f"<p>{html.escape(el.text.strip())}</p>")
                for child in el:
                    block(child)
            else:
                out.append(f"<p>{inline(el)}</p>")
            out.append("</blockquote>")
        elif tag == "list":
            ordered = el.get("rend", "") in ("ol", "#ol")
            out.append("<ol>" if ordered else "<ul>")
            for item in el.findall("item"):
                out.append(f"<li>{inline(item).strip()}</li>")
            out.append("</ol>" if ordered else "</ul>")
        elif tag == "code":
            out.append(f"<pre>{html.escape(''.join(el.itertext()))}</pre>")
        elif tag == "graphic":
            src = el.get("src")
            if src and len(art.images) < MAX_IMAGES:
                key = f"img-{len(art.images) + 1}"
                art.images[key] = urllib.parse.urljoin(art.url, src)
                alt = html.escape(el.get("alt") or el.get("title") or "")
                out.append(f'<div class="figure"><img src="{key}" alt="{alt}"/></div>')
        elif tag == "table":
            out.append("<table>")
            for row in el.findall("row"):
                cells = "".join(
                    f"<{'th' if c.get('role') == 'head' else 'td'}>{inline(c).strip()}</{'th' if c.get('role') == 'head' else 'td'}>"
                    for c in row.findall("cell")
                )
                out.append(f"<tr>{cells}</tr>")
            out.append("</table>")
        elif tag in ("div", "main", "doc"):
            for child in el:
                block(child)
        else:
            text = inline(el).strip()
            if text:
                out.append(f"<p>{text}</p>")
            elif len(el):
                for child in el:
                    block(child)

    for child in main:
        block(child)
    return "\n".join(out)


def fetch_images(art: Article) -> None:
    """Download images, convert to small greyscale JPEGs, drop failures."""
    ready = {}
    for key, src in list(art.images.items()):
        try:
            if src.startswith("data:"):
                continue
            body, _, _ = http_get(src, accept="image/*")
            img = Image.open(io.BytesIO(body))
            img.load()
            if img.width < 60 or img.height < 60:
                continue                 # tracking pixels and icons
            if getattr(img, "is_animated", False):
                img.seek(0)
            img = img.convert("L")
            if img.width > IMAGE_MAX_WIDTH:
                img = img.resize((IMAGE_MAX_WIDTH, round(img.height * IMAGE_MAX_WIDTH / img.width)), Image.LANCZOS)
            buf = io.BytesIO()
            img.save(buf, "JPEG", quality=72, optimize=True)
            ready[key] = (f"images/{key}.jpg", buf.getvalue())
        except Exception as e:           # one bad image shouldn't sink the article
            log.info("skipping image %s: %s", src, e)
    for key in art.images:
        if key not in ready:
            art.html_body = re.sub(rf'<div class="figure"><img src="{re.escape(key)}"[^>]*/></div>\n?', "", art.html_body)
    for key, (name, _) in ready.items():
        art.html_body = art.html_body.replace(f'src="{key}"', f'src="{name}"')
    art.images = ready


# --------------------------------------------------------------------------
# EPUB building
# --------------------------------------------------------------------------

CSS = """
body { font-family: serif; line-height: 1.45; margin: 0; }
h1 { font-size: 1.5em; line-height: 1.2; margin: 0 0 0.4em 0; }
h2 { font-size: 1.2em; margin: 1.2em 0 0.4em 0; }
h3, h4 { font-size: 1.05em; margin: 1em 0 0.3em 0; }
p { margin: 0 0 0.7em 0; text-indent: 0; }
.byline { font-size: 0.85em; margin: 0 0 1.4em 0; }
.byline p { margin: 0 0 0.2em 0; }
.source { font-size: 0.8em; margin-top: 2em; border-top: 1px solid #000; padding-top: 0.5em; word-break: break-all; }
blockquote { margin: 0.8em 1.2em; font-style: italic; }
.figure { text-align: center; margin: 1em 0; }
.figure img { max-width: 100%; height: auto; }
pre { white-space: pre-wrap; font-size: 0.8em; }
table { border-collapse: collapse; font-size: 0.85em; }
td, th { border: 1px solid #000; padding: 0.2em 0.4em; }
"""


def build_epub(art: Article) -> bytes:
    book = epub.EpubBook()
    book.set_identifier(f"urn:uuid:{uuid.uuid4()}")
    book.set_title(art.title)
    book.set_language("en")
    if art.author:
        book.add_author(art.author)
    if art.source:
        book.add_metadata("DC", "publisher", art.source)
    if art.url:
        book.add_metadata("DC", "source", art.url)
    book.add_metadata("DC", "date", art.date or dt.date.today().isoformat())
    book.add_metadata("DC", "subject", "gleanings")

    style = epub.EpubItem(uid="style", file_name="style.css", media_type="text/css", content=CSS.encode())
    book.add_item(style)

    byline_bits = []
    if art.author:
        byline_bits.append(f"<p>{html.escape(art.author)}</p>")
    meta_line = " · ".join(x for x in (art.source, nice_date(art.date)) if x)
    if meta_line:
        byline_bits.append(f"<p>{html.escape(meta_line)}</p>")
    footer = (
        f'<div class="source"><p>Gleaned {dt.date.today():%-d %B %Y}'
        + (f" from {html.escape(art.url)}" if art.url else "")
        + "</p></div>"
    )
    chapter = epub.EpubHtml(title=art.title, file_name="article.xhtml", lang="en")
    chapter.content = (
        f"<h1>{html.escape(art.title)}</h1>"
        f'<div class="byline">{"".join(byline_bits)}</div>'
        f"{art.html_body}{footer}"
    )
    chapter.add_item(style)
    book.add_item(chapter)

    for name, data in art.images.values():
        book.add_item(epub.EpubItem(uid=Path(name).stem, file_name=name, media_type="image/jpeg", content=data))

    book.toc = [epub.Link("article.xhtml", art.title, "article")]
    book.add_item(epub.EpubNcx())
    book.add_item(epub.EpubNav())
    book.spine = [chapter]

    buf = io.BytesIO()
    epub.write_epub(buf, book, {"epub3_pages": False})
    return buf.getvalue()


def nice_date(iso: str) -> str:
    try:
        return dt.date.fromisoformat(iso[:10]).strftime("%-d %b %Y")
    except (ValueError, TypeError):
        return ""


def text_to_article(text: str, title_hint: str = "") -> Article:
    text = text.replace("\r\n", "\n").strip()
    lines = text.split("\n")
    first = lines[0].lstrip("# ").strip()
    if title_hint:
        title, body = title_hint, text
    elif len(first) <= 120 and len(lines) > 1:
        title, body = first, "\n".join(lines[1:]).strip()
    else:
        title, body = " ".join(text.split()[:8]) + "…", text
    paras = [p.strip() for p in re.split(r"\n\s*\n", body) if p.strip()]
    if len(paras) <= 1:
        paras = [p.strip() for p in body.split("\n") if p.strip()]
    html_body = "\n".join(
        f"<p>{html.escape(p).replace(chr(10), '<br/>')}</p>" for p in paras
    )
    return Article(title=clean_text(title), source="Note", html_body=html_body)


ASCII_SWAPS = str.maketrans({
    "‘": "'", "’": "'", "‚": "'", "‛": "'",
    "“": "", "”": "", "„": "", "«": "", "»": "",
    "–": "-", "—": "-", "…": "...", " ": " ",
    "ß": "ss", "æ": "ae", "Æ": "AE", "œ": "oe", "ø": "o", "Ø": "O",
})


def safe_filename(title: str, ext: str) -> str:
    """A plain-ASCII filename. KOReader's Dropbox download can't handle
    accented letters or curly quotes in a filename, so 'Café “Noir”' becomes
    'Cafe Noir'. The real title is kept inside the EPUB itself."""
    import unicodedata
    name = unicodedata.normalize("NFKD", title.translate(ASCII_SWAPS))
    name = name.encode("ascii", "ignore").decode("ascii")
    name = re.sub(r"[\\/:*?\"<>|\x00-\x1f]", "", name)
    name = re.sub(r"\s+", " ", name).strip(" .") or "Untitled"
    if len(name) > 90:
        name = name[:90].rsplit(" ", 1)[0].rstrip(" ,;:-")
    return f"{dt.date.today():%Y-%m-%d} {name}.{ext}"


# --------------------------------------------------------------------------
# the jobs gleaner does
# --------------------------------------------------------------------------

@dataclass
class Result:
    title: str
    kind: str          # "article", "pdf", "epub", "note"
    stored_as: str
    note: str = ""


def glean_url(url: str, delivery: Delivery) -> Result:
    url = url.rstrip(").,;>]")
    body, ctype, final_url = http_get(url, accept="text/html,application/xhtml+xml,application/pdf;q=0.9,*/*;q=0.8")
    if looks_like_pdf(final_url, ctype, body):
        stem = Path(urllib.parse.unquote(urllib.parse.urlparse(final_url).path)).stem or "document"
        title = re.sub(r"[_-]+", " ", stem).strip() or "Document"
        stored = delivery.save(safe_filename(title, "pdf"), body)
        return Result(title, "pdf", stored)
    if ctype in ("application/epub+zip",):
        stem = Path(urllib.parse.urlparse(final_url).path).stem or "book"
        stored = delivery.save(safe_filename(stem, "epub"), body)
        return Result(stem, "epub", stored)
    if ctype and not (ctype.startswith("text/") or "html" in ctype or "xml" in ctype):
        raise GleanError(f"that link is a {ctype} file, which gleaner doesn't know how to convert")
    page = decode_html(body)
    art = extract_article(page, final_url)
    fetch_images(art)
    stored = delivery.save(safe_filename(art.title, "epub"), build_epub(art))
    words = len(re.sub(r"<[^>]+>", " ", art.html_body).split())
    note = f"{words:,} words, about {max(1, round(words / 230))} min"
    if art.images:
        note += f", {len(art.images)} image{'s' if len(art.images) != 1 else ''}"
    return Result(art.title, "article", stored, note)


def decode_html(body: bytes) -> str:
    m = re.search(rb'<meta[^>]+charset=["\']?([\w-]+)', body[:4096], re.I)
    for enc in ([m.group(1).decode("ascii", "ignore")] if m else []) + ["utf-8", "cp1252"]:
        try:
            return body.decode(enc)
        except (LookupError, UnicodeDecodeError):
            continue
    return body.decode("utf-8", "replace")


def glean_attachment(filename: str, data: bytes, delivery: Delivery) -> Result:
    ext = Path(filename).suffix.lower()
    stem = Path(filename).stem
    title = re.sub(r"[_]+", " ", stem).strip() or "Attachment"
    if ext == ".pdf" or data[:5] == b"%PDF-":
        return Result(title, "pdf", delivery.save(safe_filename(title, "pdf"), data))
    if ext == ".epub":
        return Result(title, "epub", delivery.save(safe_filename(title, "epub"), data))
    if ext in (".html", ".htm"):
        art = extract_article(decode_html(data), "")
        art.source = art.source or "Attachment"
        fetch_images(art)
        return Result(art.title, "article", delivery.save(safe_filename(art.title, "epub"), build_epub(art)))
    if ext in (".txt", ".md", ".markdown", ".text"):
        art = text_to_article(data.decode("utf-8", "replace"))
        return Result(art.title, "note", delivery.save(safe_filename(art.title, "epub"), build_epub(art)))
    raise GleanError(f"gleaner doesn't know what to do with {ext or 'that'} files yet (PDF, EPUB, HTML, TXT and MD work)")


def glean_text(text: str, delivery: Delivery) -> Result:
    art = text_to_article(text)
    return Result(art.title, "note", delivery.save(safe_filename(art.title, "epub"), build_epub(art)))


# --------------------------------------------------------------------------
# books: ebook files passed through untouched to their own folder
# --------------------------------------------------------------------------

BOOKS_FOLDER = "readings"                # Dropbox subfolder; Cyby puts these in documents/readings
BOOK_EXTS = (".epub", ".kepub", ".pdf", ".mobi", ".azw", ".azw3", ".fb2", ".djvu", ".djv",
             ".cbz", ".cbr", ".cb7", ".txt", ".rtf", ".docx", ".chm", ".htmlz")
BOOK_TYPES = {"application/epub+zip": ".epub", "application/pdf": ".pdf",
              "application/x-mobipocket-ebook": ".mobi", "application/vnd.amazon.ebook": ".azw",
              "application/x-fictionbook+xml": ".fb2", "image/vnd.djvu": ".djvu",
              "application/vnd.comicbook+zip": ".cbz", "application/x-cbz": ".cbz"}


# Files that travel with a book (e.g. from a Calibre library) but aren't the book:
# skipped quietly when they're posted alongside one.
BOOK_SIDECARS = (".opf", ".jpg", ".jpeg", ".png", ".gif", ".webp", ".ncx", ".db", ".json", ".xml", ".nfo")


def book_filename(filename: str) -> str:
    """The book's own filename, made safe for Kindle storage and KOReader's Dropbox
    download: plain ASCII, no date prefix (books aren't news)."""
    import unicodedata
    p = Path(filename)
    ext = "".join(p.suffixes[-1:]).lower()
    stem = unicodedata.normalize("NFKD", p.stem.translate(ASCII_SWAPS)).encode("ascii", "ignore").decode("ascii")
    stem = re.sub(r"[\\/:*?\"<>|\x00-\x1f]", "", stem)
    stem = re.sub(r"\s+", " ", stem.replace("_", " ")).strip(" .") or "Book"
    if len(stem) > 120:
        stem = stem[:120].rsplit(" ", 1)[0].rstrip(" ,;:-")
    return f"{stem}{ext}"


def book_title(stored: str) -> str:
    return Path(stored).stem


def check_book(name: str, data: bytes) -> str:
    """the file's extension if it's an ebook Cyby can open, else raise"""
    ext = Path(name).suffix.lower()
    if ext not in BOOK_EXTS:
        raise GleanError(f"{ext or 'that'} isn't an ebook format KOReader opens "
                         "(EPUB, PDF, MOBI, AZW3, FB2, DjVu, CBZ, TXT…)")
    if not data:
        raise GleanError("the file is empty")
    if ext == ".pdf" and not data[:1024].lstrip().startswith(b"%PDF"):
        raise GleanError("that doesn't look like a real PDF")
    if ext in (".epub", ".kepub", ".cbz", ".htmlz") and data[:2] != b"PK":
        raise GleanError(f"that doesn't look like a real {ext[1:].upper()} file")
    return ext


def glean_book(filename: str, data: bytes, delivery: Delivery) -> Result:
    name = book_filename(filename)
    check_book(name, data)
    stored = delivery.save(name, data, BOOKS_FOLDER)
    size = f"{len(data) / 1e6:.1f} MB" if len(data) >= 1e6 else f"{max(1, len(data) // 1000)} KB"
    return Result(book_title(stored), "book", stored, size)


def glean_book_url(url: str, delivery: Delivery) -> Result:
    url = url.rstrip(").,;>]")
    body, ctype, final_url = http_get(url, accept="application/epub+zip,application/pdf,*/*;q=0.8")
    name = Path(urllib.parse.unquote(urllib.parse.urlparse(final_url).path)).name
    if Path(name).suffix.lower() not in BOOK_EXTS:
        ext = BOOK_TYPES.get(ctype)
        if ext is None and body[:5] == b"%PDF-":
            ext = ".pdf"
        if ext is None:
            if ctype.startswith("text/html") or "html" in ctype:
                raise GleanError("that's a web page, not a book file. Post a direct download link "
                                 "(articles go in #gleanings)")
            raise GleanError(f"couldn't tell what kind of file that is ({ctype or 'unknown type'})")
        name = (Path(name).stem or "Book") + ext
    return glean_book(name, body, delivery)


# --------------------------------------------------------------------------
# sstacks: new free posts from a few chosen Substack publications
# --------------------------------------------------------------------------

SSTACKS_FOLDER = "sstacks"               # Dropbox subfolder; Cyby puts these in documents/sstacks
SSTACKS_STATE = "sstacks.json"           # in ~/.gleaner: subscriptions, cap, what's been sent
SSTACKS_CHECK_EVERY = 3 * 3600           # seconds between checks of every publication
SSTACKS_TICK = 15 * 60                   # how often the loop wakes to see if a check is due
SSTACKS_DEFAULT_CAP = 3                  # posts per 7 days
SSTACKS_MAX_TRIES = 3                    # a post that fails this often is let go
PAID_MARKERS = re.compile(r"(this post is for paid subscribers|keep reading with a \d+-day free trial|"
                          r"subscribe to keep reading|this post is for paying subscribers|"
                          r"upgrade to paid to read|paid subscribers only)", re.I)
SUBSTACK_SKIP_HOSTS = ("substack.com", "www.substack.com", "open.substack.com")


class SstacksError(GleanError):
    pass


def http_json(url: str):
    body, ctype, _ = http_get(url, accept="application/json")
    try:
        return json.loads(body.decode("utf-8", "replace"))
    except ValueError:
        raise SstacksError("that didn't answer like a Substack publication")


def substack_base(url: str) -> str:
    """Any Substack link (publication, post, or substack.com/@writer profile) ->
    the publication's address, e.g. https://kevinmunger.substack.com"""
    url = url.strip().rstrip(").,;>]")
    if "://" not in url:
        url = "https://" + url
    p = urllib.parse.urlparse(url)
    host = p.netloc.lower().split(":")[0]
    if host in SUBSTACK_SKIP_HOSTS:
        m = re.match(r"/@([A-Za-z0-9_.-]+)", p.path) or re.match(r"/profile/\d+-([A-Za-z0-9_.-]+)", p.path)
        if not m:
            raise SstacksError("post a link to the publication (name.substack.com) or the writer's "
                               "profile (substack.com/@name)")
        handle = m.group(1)
        try:
            prof = http_json(f"https://substack.com/api/v1/user/{handle}/public_profile")
            pubs = []
            if isinstance(prof.get("primaryPublication"), dict):
                pubs.append(prof["primaryPublication"])
            for pu in prof.get("publicationUsers") or []:
                if isinstance(pu, dict) and isinstance(pu.get("publication"), dict):
                    pubs.append(pu["publication"])
            for pub in pubs:
                if pub.get("custom_domain") and not pub.get("custom_domain_optional"):
                    return "https://" + pub["custom_domain"].lower()
                if pub.get("subdomain"):
                    return f"https://{pub['subdomain'].lower()}.substack.com"
        except GleanError:
            pass
        base = f"https://{handle.lower()}.substack.com"     # most writers' handle is their subdomain
        substack_posts(base, limit=1)
        return base
    return f"{p.scheme or 'https'}://{p.netloc.lower()}"


def _post_from_api(d: dict, base: str) -> dict:
    bylines = d.get("publishedBylines") or []
    return {
        "id": str(d.get("id") or d.get("slug")),
        "title": clean_text(d.get("title") or "Untitled"),
        "slug": d.get("slug") or "",
        "url": d.get("canonical_url") or f"{base}/p/{d.get('slug')}",
        "date": d.get("post_date") or "",
        "audience": d.get("audience") or "everyone",
        "type": d.get("type") or "newsletter",
        "author": clean_text(bylines[0].get("name", "")) if bylines and isinstance(bylines[0], dict) else "",
        "body_html": d.get("body_html") or "",
    }


def rss_date(text: str) -> str:
    """'Fri, 09 Oct 2026 10:00:00 GMT' -> '2026-10-09T10:00:00+00:00'"""
    from email.utils import parsedate_to_datetime
    try:
        return parsedate_to_datetime(text).isoformat()
    except (TypeError, ValueError):
        return text


def _posts_from_feed(body: bytes, base: str) -> tuple[str, list[dict]]:
    import xml.etree.ElementTree as ET
    try:
        root = ET.fromstring(body)
    except ET.ParseError:
        raise SstacksError("couldn't read that publication's feed")
    ns = {"content": "http://purl.org/rss/1.0/modules/content/", "dc": "http://purl.org/dc/elements/1.1/"}
    chan = root.find("channel")
    name = clean_text(chan.findtext("title", "")) if chan is not None else ""
    posts = []
    for it in root.iter("item"):
        link = (it.findtext("link") or "").strip()
        content = it.findtext("content:encoded", "", ns) or ""
        tail = re.sub(r"<[^>]+>", " ", content[-1500:])
        posts.append({
            "id": (it.findtext("guid") or link).strip(),
            "title": clean_text(it.findtext("title", "Untitled")),
            "slug": link.rstrip("/").rsplit("/", 1)[-1],
            "url": link,
            "date": rss_date(it.findtext("pubDate", "")),
            "audience": "only_paid" if PAID_MARKERS.search(tail) else "everyone",
            "type": "podcast" if it.find("enclosure") is not None and "audio" in (it.find("enclosure").get("type") or "") else "newsletter",
            "author": clean_text(it.findtext("dc:creator", "", ns)),
            "body_html": content,
        })
    return name, posts


def substack_posts(base: str, limit: int = 12) -> list[dict]:
    """Newest posts first. Substack's archive API, falling back to the RSS feed."""
    try:
        data = http_json(f"{base}/api/v1/archive?sort=new&limit={limit}")
        if isinstance(data, list):
            return [_post_from_api(d, base) for d in data if isinstance(d, dict)]
    except GleanError:
        pass
    body, _, _ = http_get(f"{base}/feed", accept="application/rss+xml,application/xml,text/xml")
    return _posts_from_feed(body, base)[1][:limit]


def substack_name(base: str) -> str:
    try:
        body, _, _ = http_get(f"{base}/feed", accept="application/rss+xml,application/xml,text/xml")
        name = _posts_from_feed(body, base)[0]
        if name:
            return name
    except GleanError:
        pass
    return urllib.parse.urlparse(base).netloc.removesuffix(".substack.com")


def is_paid(post: dict) -> bool:
    if post.get("audience") not in (None, "", "everyone"):
        return True
    return bool(PAID_MARKERS.search(re.sub(r"<[^>]+>", " ", (post.get("body_html") or "")[-1500:])))


def glean_sstack(base: str, pub_name: str, post: dict, delivery: Delivery) -> Result:
    """One Substack post -> a clean EPUB in the sstacks folder."""
    body_html = ""
    if post.get("slug"):
        try:
            full = http_json(f"{base}/api/v1/posts/{post['slug']}")
            if isinstance(full, dict):
                if full.get("audience") not in (None, "", "everyone"):
                    raise SstacksError("it's for paid subscribers")
                body_html = full.get("body_html") or ""
                post = {**post, **{k: v for k, v in _post_from_api(full, base).items() if v and k != "body_html"}}
        except SstacksError:
            raise
        except GleanError:
            pass
    body_html = body_html or post.get("body_html") or ""
    if body_html:
        page = (f"<html><head><meta charset='utf-8'><title>{html.escape(post['title'])}</title></head>"
                f"<body><article><h1>{html.escape(post['title'])}</h1>{body_html}</article></body></html>")
        art = extract_article(page, post["url"])
    else:                                 # no body from the API or feed: read the web page
        page_bytes, _, final_url = http_get(post["url"], accept="text/html")
        art = extract_article(decode_html(page_bytes), final_url)
    art.title = post["title"]
    art.author = post.get("author") or art.author
    art.source = pub_name
    art.url = post["url"]
    art.date = post.get("date") or art.date
    if is_paid({"body_html": art.html_body}):
        raise SstacksError("it's for paid subscribers")
    fetch_images(art)
    stored = delivery.save(safe_filename(art.title, "epub"), build_epub(art), SSTACKS_FOLDER)
    words = len(re.sub(r"<[^>]+>", " ", art.html_body).split())
    return Result(art.title, "article", stored, f"{words:,} words, about {max(1, round(words / 230))} min")


class Sstacks:
    """Subscriptions and the weekly cap, kept in ~/.gleaner/sstacks.json."""

    def __init__(self, path: Path):
        self.path = path
        self.data = {"subs": {}, "cap": SSTACKS_DEFAULT_CAP, "sent": [], "queue": [], "last_check": 0}
        if path.exists():
            try:
                self.data.update(json.loads(path.read_text()))
            except ValueError:
                log.warning("couldn't read %s; starting afresh", path)

    def save(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".part")
        tmp.write_text(json.dumps(self.data, indent=1))
        tmp.replace(self.path)

    @property
    def subs(self) -> dict:
        return self.data["subs"]

    @property
    def cap(self) -> int | None:
        return self.data.get("cap")

    def sent_this_week(self, now: float) -> int:
        self.data["sent"] = [t for t in self.data["sent"] if now - t < 7 * 86400]
        return len(self.data["sent"])

    def find(self, query: str) -> str | None:
        q = query.strip().lower()
        if q.isdigit() and 0 < int(q) <= len(self.subs):
            return list(self.subs)[int(q) - 1]
        for base, s in self.subs.items():
            if q in (s.get("name", "").lower(), base.lower()) or q in base.lower() or q in s.get("name", "").lower():
                return base
        return None


SSTACKS_HELP = """**gleaner** brings new *free* posts from a few chosen Substack writers to Cyby.
• post a **Substack link** (name.substack.com, or substack.com/@writer) → subscribe
• `!list` who you're subscribed to · `!unsubscribe name` stop one
• `!cap 3` at most 3 posts a week · `!cap` see this week's count · `!cap off` no limit
• `!check` look for new posts now (gleaner also checks every few hours)
Only posts published after you subscribe. Paid-only posts are skipped with a note.
Over the cap, posts wait for next week, but never more than a week's worth.
They arrive on Cyby in **documents/sstacks**."""


# --------------------------------------------------------------------------
# sleep screens
# --------------------------------------------------------------------------

SCREEN_W, SCREEN_H = 758, 1024           # Paperwhite 2, portrait
SCREENS_FOLDER = "screensavers"          # Dropbox subfolder Cyby syncs from
IMAGE_EXTS = (".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp", ".tif", ".tiff", ".heic")


SCREEN_PPI = 212                         # Paperwhite 2 pixel density
MARGIN_MM = 5
MARGIN = int(-(-MARGIN_MM * SCREEN_PPI // 25.4))    # at least 5 mm of white on every side: 42 px
CENTRE_CHANCE = 0.2                      # 1 in 5 images is centred; the rest sit towards a corner
EDGE_PULL = 0.3                          # how far in from the margin a corner image may drift (share of spare room)


def make_screensaver(data: bytes, centred: bool = False, seed: int | None = None) -> bytes:
    """Place an image on a white 758x1024 page tuned for e-ink.
    Never cropped and never enlarged: kept at its own size, or scaled down to
    fit inside a 5 mm white margin. Most images sit towards a corner (a
    random side and end, stopping at the margin); about 1 in 5 is centred.
    The choice is fixed per post, so an image always appears in the same place."""
    import random
    from PIL import ImageFilter, ImageOps
    try:
        img = Image.open(io.BytesIO(data))
        img.load()
    except Exception:
        raise GleanError("that doesn't look like an image gleaner can read (JPEG, PNG, GIF and WebP work)")
    if getattr(img, "is_animated", False):
        img.seek(0)
    img = ImageOps.exif_transpose(img)                       # respect phone-photo rotation
    if img.mode in ("RGBA", "LA", "P"):
        img = img.convert("RGBA")
        backdrop = Image.new("RGBA", img.size, (255, 255, 255, 255))
        img = Image.alpha_composite(backdrop, img)
    img = img.convert("L")
    if min(img.size) < 48:
        raise GleanError(f"that image is tiny ({img.width}×{img.height}), probably an icon")
    img = ImageOps.autocontrast(img, cutoff=0.5)
    box_w, box_h = SCREEN_W - 2 * MARGIN, SCREEN_H - 2 * MARGIN
    if img.width > box_w or img.height > box_h:              # shrink only, never enlarge
        img = ImageOps.contain(img, (box_w, box_h), Image.LANCZOS)
        img = img.filter(ImageFilter.UnsharpMask(radius=1.0, percent=50, threshold=2))
    spare_x, spare_y = box_w - img.width, box_h - img.height
    rng = random.Random(seed)
    if centred or rng.random() < CENTRE_CHANCE:
        x, y = MARGIN + spare_x // 2, MARGIN + spare_y // 2
    else:
        # Favour the edges: pick a side (left/right) and an end (top/bottom),
        # then sit close to that corner, never closer than the margin.
        def near_edge(spare: int) -> int:
            offset = int(spare * EDGE_PULL * rng.random() ** 2)   # mostly hard against the edge
            return offset if rng.random() < 0.5 else spare - offset

        x, y = MARGIN + near_edge(spare_x), MARGIN + near_edge(spare_y)
    canvas = Image.new("L", (SCREEN_W, SCREEN_H), 255)
    canvas.paste(img, (x, y))
    img = canvas
    # Dither to the 16 greys the screen can show, so gradients don't band.
    palette = Image.new("P", (1, 1))
    greys = [v for level in range(16) for v in (level * 17,) * 3]
    palette.putpalette(greys + [0] * (768 - len(greys)))
    img = img.convert("RGB").quantize(palette=palette, dither=Image.Dither.FLOYDSTEINBERG).convert("L")
    out = io.BytesIO()
    img.save(out, "PNG", optimize=True)
    return out.getvalue()


def screensaver_name(message_id: int, index: int, hint: str) -> str:
    """'<message id>-<n> <name>.png' - the id lets gleaner find it again if the post is deleted."""
    stem = Path(hint).stem if hint else "image"
    stem = safe_filename(stem, "png")[11:-4][:40].strip() or "image"   # drop the date prefix
    return f"{message_id}-{index} {stem}.png"


def glean_screensaver(message_id: int, index: int, data: bytes, hint: str, centred: bool, delivery: Delivery) -> Result:
    png = make_screensaver(data, centred, seed=message_id * 100 + index)
    stored = delivery.save(screensaver_name(message_id, index, hint), png, SCREENS_FOLDER)
    return Result(Path(hint).stem if hint else "image", "screen", stored)


def glean_screensaver_url(message_id: int, index: int, url: str, centred: bool, delivery: Delivery) -> Result:
    body, ctype, final_url = http_get(url, accept="image/*")
    if ctype and not ctype.startswith("image/") and not urllib.parse.urlparse(final_url).path.lower().endswith(IMAGE_EXTS):
        raise GleanError("that link is a web page, not an image. Post the image itself, or a direct link to it")
    name = Path(urllib.parse.unquote(urllib.parse.urlparse(final_url).path)).name
    return glean_screensaver(message_id, index, body, name, centred, delivery)


# --------------------------------------------------------------------------
# ctx.fm: links posted in #listening go into the ctx queue
# --------------------------------------------------------------------------

CTX_POLL_EVERY = 3        # seconds between checks on a url-add job
CTX_POLL_FOR = 240        # give up waiting (ctx keeps working) after this long


class CtxError(GleanError):
    pass


class Ctx:
    """The few calls gleaner needs from the ctx REST API (personal API key)."""

    def __init__(self, settings: Settings):
        self.key = settings.ctx_api_key
        self.base = settings.ctx_base

    @property
    def ready(self) -> bool:
        return bool(self.key)

    def _call(self, method: str, path: str, body: dict | None = None, retry: bool = True) -> dict:
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(self.base + path, data=data, method=method, headers={
            "Authorization": f"Bearer {self.key}",
            "Accept": "application/json",
            "User-Agent": f"gleaner/{__version__}",
            **({"Content-Type": "application/json"} if data else {}),
        })
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                return json.load(r)
        except urllib.error.HTTPError as e:
            detail = ""
            try:
                payload = json.load(e)
                detail = payload.get("detail") or "; ".join(
                    f"{k}: {v[0] if isinstance(v, list) else v}" for k, v in payload.items())
            except Exception:
                pass
            if e.code == 429:
                wait = int(e.headers.get("Retry-After") or 0)
                if retry and 0 < wait <= 60:
                    import time
                    time.sleep(wait)
                    return self._call(method, path, body, retry=False)
                raise CtxError(f"ctx.fm says slow down (60 links an hour); try again in {max(wait, 1) // 60 or 1} min")
            if e.code == 401:
                raise CtxError("ctx.fm didn't accept the API key; check CTX_API_KEY in ~/.gleaner/gleaner.env")
            if e.code == 400:
                raise CtxError(f"ctx.fm couldn't use that link ({detail or 'bad request'})")
            raise CtxError(f"ctx.fm returned an error (HTTP {e.code}{': ' + detail if detail else ''})")
        except urllib.error.URLError as e:
            raise CtxError(f"couldn't reach ctx.fm ({e.reason})")

    def whoami(self) -> str:
        p = self._call("GET", "/api/profile/")
        return p.get("username") or p.get("display_name") or "your account"

    def add_url(self, url: str, target: str = "queue") -> dict:
        """Ask ctx to add a release by URL, then wait for it to be identified."""
        import time
        job = self._call("POST", "/api/url-add/", {"url": url, "target_status": target})
        deadline = time.monotonic() + CTX_POLL_FOR
        while job.get("status") in ("PENDING", "RUNNING") and time.monotonic() < deadline:
            time.sleep(CTX_POLL_EVERY)
            job = self._call("GET", f"/api/url-add/{job['id']}/")
        return job


def describe_release(obj: dict | None) -> str:
    if not obj:
        return "that release"
    name = obj.get("display_name") or "Untitled"
    artists = ", ".join(a.get("display_name", "") for a in obj.get("artists") or [] if a.get("display_name"))
    bits = [f"**{name}**"]
    if artists:
        bits.append(f"by {artists}")
    year = obj.get("year")
    kind = (obj.get("subtype") or obj.get("primary_type") or "").replace("_", " ").lower()
    tail = ", ".join(x for x in (kind, str(year) if year else "") if x)
    return " ".join(bits) + (f" ({tail})" if tail else "")


def listen_to(ctx: Ctx, url: str, target: str) -> str:
    """One line for the reply, or raise CtxError."""
    job = ctx.add_url(url, target)
    status = job.get("status")
    if status == "COMPLETED":
        where = "collection" if target == "collection" else "queue"
        if job.get("library_entry_was_existing"):
            return f"🎵 {describe_release(job.get('media_object'))}, already in your library"
        return f"🎵 {describe_release(job.get('media_object'))} → added to your {where}"
    if status == "FAILED":
        why = job.get("error_message") or (job.get("error_code") or "unknown reason").replace("_", " ").lower()
        raise CtxError(f"ctx.fm couldn't add it: {why}")
    return "🕒 ctx.fm is still working on that one; it will land in your queue when it's done"


def wants_collection(text: str) -> bool:
    return bool(re.search(r"\bcollection\b", text or "", re.I))


# --------------------------------------------------------------------------
# Discord
# --------------------------------------------------------------------------

HELP = """**gleaner** gathers things for Cyby. In this channel, post:
• a **link** to an article → cleaned up and bound as an EPUB
• a **link to a PDF**, or an attached **PDF/EPUB** → passed through as-is
• an attached **.txt / .md / .html**, or a **block of text** → bound as an EPUB

Cyby collects them by itself (or Tools → Gleanings → Sync now).
Commands: `!recent` latest deliveries · `!ping` am I awake · `!help` this message"""

SCREENS_HELP = """**gleaner** makes Cyby's sleep screens from this channel. Post:
• **images** (attached, or a direct link to an image) → greyscale, never cropped, at their own size
  (or shrunk to fit), placed towards a corner of a white page (some centred), with at least 5 mm of margin
• add the word **centre** to always place it in the middle

**Delete a post** to take its image out of the rotation.
Commands: `!count` how many are in rotation · `!ping` · `!help`"""


LISTEN_HELP = """**gleaner** passes music to ctx.fm from this channel. Post:
• a **link** to a release (Bandcamp, Apple Music, Spotify, YouTube… whatever ctx.fm can read) → added to your ctx **queue**
• add the word **collection** to put it straight into your collection instead

Commands: `!ctx` check the ctx.fm connection · `!ping` · `!help`"""


BOOKS_HELP = """**gleaner** carries ebooks to Cyby from this channel. Post:
• an attached **ebook** (EPUB, PDF, MOBI, AZW3, FB2, DjVu, CBZ, TXT…) → passed through untouched
• a **direct download link** to one → fetched (up to 60 MB) and passed through
Cyby files them in **documents/readings** on its next sync.

Too big for Discord? Post a link instead, or drop the file into Dropbox → Apps → cyby → readings.
Commands: `!recent` latest books · `!ping` · `!help`"""


def wants_centre(text: str) -> bool:
    return bool(re.search(r"\bcent(re|er|red|ered)\b", text or "", re.I))


class Gleaner(discord.Client):
    def __init__(self, settings: Settings):
        intents = discord.Intents.default()
        intents.message_content = True
        super().__init__(intents=intents)
        self.settings = settings
        self.delivery = Delivery(settings)
        self.ctx = Ctx(settings)
        self.in_flight: set[int] = set()        # message ids being worked on right now
        self.catchup_lock = asyncio.Lock()
        self.sstacks = Sstacks(CONFIG_DIR / SSTACKS_STATE)
        self.sstacks_lock = asyncio.Lock()

    async def setup_hook(self):
        asyncio.create_task(self.sstacks_loop())

    async def on_ready(self):
        log.info("gleaner %s logged in as %s; watching %s; delivering to %s",
                 __version__, self.user, ", ".join(f"#{c}" for c in self.channel_names()),
                 self.delivery.describe())
        names = {c.name for g in self.guilds for c in g.text_channels}
        for wanted in self.channel_names():
            if wanted not in names:
                log.warning("no channel called #%s found in %d server(s)", wanted, len(self.guilds))
        await self.catch_up()

    def channel_names(self) -> tuple:
        names = (self.settings.channel_name, self.settings.screens_channel, self.settings.books_channel,
                 self.settings.sstacks_channel)
        return names + (self.settings.listen_channel,) if self.ctx.ready else names

    def kind_of(self, channel) -> str | None:
        name = getattr(channel, "name", None)
        if name == self.settings.screens_channel:
            return "screens"
        if name == self.settings.listen_channel and self.ctx.ready:
            return "listen"
        if name == self.settings.books_channel:
            return "books"
        if name == self.settings.sstacks_channel:
            return "sstacks"
        if name == self.settings.channel_name:
            return "gleanings"
        return None

    def is_screens(self, channel) -> bool:
        return self.kind_of(channel) == "screens"

    async def on_raw_message_delete(self, payload: discord.RawMessageDeleteEvent):
        # A post deleted from #screensavers takes its image out of the rotation.
        channel = self.get_channel(payload.channel_id)
        if not self.is_screens(channel):
            return
        gone = await asyncio.to_thread(self.delivery.delete_prefix, f"{payload.message_id}-", SCREENS_FOLDER)
        if gone:
            log.info("removed %d sleep screen(s) for deleted post %s", gone, payload.message_id)
            left = await asyncio.to_thread(self.delivery.count, SCREENS_FOLDER)
            try:
                await channel.send(f"🗑 Removed {gone} image{'s' if gone != 1 else ''} from Cyby's sleep screens "
                                   f"({left} left).", delete_after=15)
            except discord.HTTPException:
                pass

    async def on_resumed(self):
        # Back from a short drop-out (e.g. the Mac woke up). Discord usually replays
        # what was missed, but check anyway; already-handled posts are skipped.
        await self.catch_up()

    async def catch_up(self):
        """Process posts made while gleaner was offline: anything recent in the
        channel that gleaner hasn't marked ✅ / ⚠️ / ❌."""
        if self.catchup_lock.locked():
            return
        async with self.catchup_lock:
            since = discord.utils.utcnow() - dt.timedelta(days=CATCHUP_DAYS)
            found = 0
            for channel in self.watched_channels():
                try:
                    async for message in channel.history(limit=CATCHUP_LIMIT, after=since, oldest_first=True):
                        if message.author.bot or (message.content or "").strip().startswith("!"):
                            continue
                        if already_handled(message) or message.id in self.in_flight:
                            continue
                        if not message_jobs(message, self.kind_of(channel)):
                            continue
                        found += 1
                        log.info("catching up on a post from %s", message.created_at.strftime("%d %b %H:%M"))
                        await self.handle(message, catching_up=True)
                except discord.Forbidden:
                    log.warning("can't read the history of #%s (needs Read Message History)", channel.name)
            if found:
                log.info("caught up on %d post%s made while offline", found, "" if found == 1 else "s")

    def watched_channels(self):
        wanted = self.channel_names()
        return [c for g in self.guilds for c in g.text_channels if c.name in wanted]

    async def on_message(self, message: discord.Message):
        if message.author.bot or not isinstance(message.channel, discord.TextChannel):
            return
        if self.kind_of(message.channel) is None:
            return
        await self.handle(message)

    async def handle(self, message: discord.Message, catching_up: bool = False):
        content = (message.content or "").strip()
        command = content.lower()
        kind = self.kind_of(message.channel)
        if kind == "sstacks" and command != "!ping":
            await self.handle_sstacks(message, content, command, catching_up)
            return
        if command in ("!help", "!gleaner"):
            text = {"screens": SCREENS_HELP, "listen": LISTEN_HELP, "books": BOOKS_HELP}.get(kind, HELP)
            await message.reply(text, mention_author=False)
            return
        if command == "!ctx":
            try:
                who = await asyncio.to_thread(self.ctx.whoami)
                await message.reply(f"🎵 Connected to ctx.fm as **{who}**.", mention_author=False)
            except GleanError as e:
                await message.reply(f"❌ {e}", mention_author=False)
            return
        if command == "!count":
            n = await asyncio.to_thread(self.delivery.count, SCREENS_FOLDER)
            await message.reply(f"🖼 {n} image{'s' if n != 1 else ''} in Cyby's sleep-screen rotation.",
                                mention_author=False)
            return
        if command == "!ping":
            await message.reply(f"🌾 awake. Delivering to `{self.delivery.describe()}`", mention_author=False)
            return
        if command == "!recent":
            folder = BOOKS_FOLDER if kind == "books" else ""
            names = await asyncio.to_thread(self.delivery.recent, 8, folder)
            text = "\n".join(f"• {n}" for n in names) if names else "Nothing delivered yet."
            label = "Recent books" if kind == "books" else "Recent gleanings"
            await message.reply(f"**{label}**\n{text}", mention_author=False)
            return
        if content.startswith("!"):
            return

        jobs = message_jobs(message, kind)
        if not jobs or message.id in self.in_flight:
            return                   # a short chat line, or already being worked on
        self.in_flight.add(message.id)
        try:
            await self.run_jobs(message, jobs, catching_up)
        finally:
            self.in_flight.discard(message.id)

    # ---- #sstacks -------------------------------------------------------

    async def handle_sstacks(self, message, content: str, command: str, catching_up: bool):
        st = self.sstacks
        reply = lambda text: message.reply(text[:1990], mention_author=False, suppress_embeds=True)
        if command in ("!help", "!gleaner"):
            await reply(SSTACKS_HELP)
        elif command == "!list":
            if not st.subs:
                await reply("No subscriptions yet. Post a Substack link to add one.")
            else:
                rows = [f"{i}. **{s['name']}** <{base}>" for i, (base, s) in enumerate(st.subs.items(), 1)]
                await reply("**Subscribed**\n" + "\n".join(rows) + "\n" + self.cap_line())
        elif command.startswith(("!unsubscribe", "!unsub")):
            query = content.split(maxsplit=1)[1] if len(content.split()) > 1 else ""
            async with self.sstacks_lock:
                base = st.find(query) if query else None
                if not base:
                    await reply("Which one? `!unsubscribe name` (see `!list`).")
                    return
                name = st.subs.pop(base)["name"]
                st.data["queue"] = [q for q in st.data["queue"] if q["base"] != base]
                st.save()
            await reply(f"👋 Unsubscribed from **{name}**.")
        elif command.startswith("!cap"):
            arg = command[4:].strip()
            if arg:
                if arg in ("off", "none", "0"):
                    cap = None
                elif arg.isdigit():
                    cap = int(arg)
                else:
                    await reply("Use `!cap 3`, `!cap off`, or just `!cap` to see it.")
                    return
                async with self.sstacks_lock:
                    st.data["cap"] = cap
                    dropped = self.trim_queue()
                    st.save()
                extra = "".join(f"\n⏭ Let go of **{t}** (more than a week's worth waiting)" for t in dropped)
                await reply(("📏 No weekly limit now." if cap is None else f"📏 Cap set: at most {cap} a week.") + extra)
            else:
                await reply(self.cap_line())
        elif command == "!check":
            await safe_react(message, "⏳")
            notes = await self.check_sstacks(manual=True)
            await safe_unreact(message, "⏳")
            await reply("\n".join(notes) if notes else "Nothing new. " + self.cap_line())
        elif command == "!recent":
            names = await asyncio.to_thread(self.delivery.recent, 8, SSTACKS_FOLDER)
            await reply("**Recent sstacks**\n" + ("\n".join(f"• {n}" for n in names) or "Nothing delivered yet."))
        elif content.startswith("!"):
            return
        else:
            urls = [u for kind, u in message_jobs(message, "sstacks")]
            if urls and message.id not in self.in_flight:
                self.in_flight.add(message.id)
                try:
                    await self.subscribe(message, urls, catching_up)
                finally:
                    self.in_flight.discard(message.id)

    def cap_line(self) -> str:
        st = self.sstacks
        sent, waiting = st.sent_this_week(time.time()), len(st.data["queue"])
        cap = "no weekly limit" if st.cap is None else f"cap {st.cap} a week"
        return f"_{sent} sent in the last 7 days · {waiting} waiting · {cap}_"

    def trim_queue(self) -> list[str]:
        """never more than a week's worth waiting: drop the oldest"""
        q, cap, dropped = self.sstacks.data["queue"], self.sstacks.cap, []
        while cap is not None and len(q) > cap:
            dropped.append(q.pop(0)["post"]["title"])
        return dropped

    async def subscribe(self, message, urls: list[str], catching_up: bool):
        st = self.sstacks
        await safe_react(message, "⏳")
        lines, failed = (["_Picked up after being offline._"] if catching_up else []), 0
        for url in dict.fromkeys(urls):
            try:
                base = await asyncio.to_thread(substack_base, url)
                if base in st.subs:
                    lines.append(f"Already subscribed to **{st.subs[base]['name']}**.")
                    continue
                posts = await asyncio.to_thread(substack_posts, base)
                name = await asyncio.to_thread(substack_name, base)
                async with self.sstacks_lock:
                    st.subs[base] = {"name": name, "added": time.time(), "seen": [p["id"] for p in posts]}
                    st.save()
                letters = [p for p in posts if p.get("type") in (None, "", "newsletter")]
                latest = f" (latest so far: *{letters[0]['title']}*)" if letters else ""
                lines.append(f"📬 Subscribed to **{name}** <{base}>. New free posts from now on{latest}.")
                log.info("subscribed to %s (%s)", name, base)
            except GleanError as e:
                failed += 1
                lines.append(f"❌ <{url}>: {e}")
        if failed < len(urls):
            lines.append(self.cap_line())
        await safe_unreact(message, "⏳")
        await safe_react(message, "✅" if failed == 0 else ("⚠️" if failed < len(urls) else "❌"))
        await message.reply("\n".join(lines)[:1990], mention_author=False, suppress_embeds=True)

    async def check_sstacks(self, manual: bool = False) -> list[str]:
        """Look for new posts, queue the free ones, deliver what the cap allows.
        Returns the notes to post in the channel."""
        st, notes, delivered = self.sstacks, [], 0
        async with self.sstacks_lock:
            for base, sub in list(st.subs.items()):
                try:
                    posts = await asyncio.to_thread(substack_posts, base)
                except GleanError as e:
                    log.warning("couldn't check %s: %s", base, e)
                    if manual:
                        notes.append(f"⚠️ Couldn't check **{sub['name']}**: {e}")
                    continue
                seen = set(sub.get("seen", []))
                for p in reversed(posts):                      # oldest first
                    if p["id"] in seen:
                        continue
                    sub.setdefault("seen", []).append(p["id"])
                    if p.get("type") not in (None, "", "newsletter"):
                        continue                               # podcasts, threads
                    if is_paid(p):
                        notes.append(f"🔒 Skipped a paid post from **{sub['name']}**: {p['title']}")
                        continue
                    st.data["queue"].append({"base": base, "tries": 0, "post": {
                        k: p.get(k, "") for k in ("id", "title", "slug", "url", "date", "author", "audience", "type")}})
                sub["seen"] = sub.get("seen", [])[-300:]
            q = st.data["queue"]
            while q and (st.cap is None or st.sent_this_week(time.time()) < st.cap):
                item = q[0]
                sub = st.subs.get(item["base"])
                if sub is None:
                    q.pop(0)
                    continue
                try:
                    res = await asyncio.to_thread(glean_sstack, item["base"], sub["name"], item["post"], self.delivery)
                    q.pop(0)
                    st.data["sent"].append(time.time())
                    delivered += 1
                    notes.append(f"📰 **{res.title}** · {sub['name']} ({res.note})")
                    log.info("sstacks delivered %s -> %s", item["post"]["url"], res.stored_as)
                except SstacksError:
                    q.pop(0)
                    notes.append(f"🔒 Skipped a paid post from **{sub['name']}**: {item['post']['title']}")
                except Exception as e:
                    item["tries"] = item.get("tries", 0) + 1
                    log.warning("sstacks couldn't fetch %s (try %d): %s", item["post"]["url"], item["tries"], e)
                    if item["tries"] >= SSTACKS_MAX_TRIES:
                        q.pop(0)
                        notes.append(f"❌ Couldn't fetch **{item['post']['title']}** ({e}); letting it go")
                    else:
                        break                                  # try again at the next check
            notes += [f"⏭ Let go of **{t}** (more than a week's worth waiting)" for t in self.trim_queue()]
            if q and st.cap is not None and st.sent_this_week(time.time()) >= st.cap:
                notes.append(f"_{len(q)} waiting for next week (cap {st.cap})._")
            st.data["last_check"] = time.time()
            st.save()
        if delivered:
            notes.append("_On its way to Cyby's sstacks, it'll arrive on the next sync._")
        return notes

    async def sstacks_loop(self):
        await self.wait_until_ready()
        await asyncio.sleep(30)
        while not self.is_closed():
            try:
                st = self.sstacks
                if st.subs and time.time() - st.data.get("last_check", 0) >= SSTACKS_CHECK_EVERY:
                    notes = await self.check_sstacks()
                    if notes:
                        for c in self.watched_channels():
                            if c.name == self.settings.sstacks_channel:
                                await c.send("\n".join(notes)[:1990], suppress_embeds=True)
                                break
            except Exception:
                log.exception("sstacks check failed")
            await asyncio.sleep(SSTACKS_TICK)

    async def run_jobs(self, message: discord.Message, jobs: list, catching_up: bool):
        await safe_react(message, "⏳")
        lines, failed = [], 0
        if catching_up:
            lines.append("_Picked up after being offline._")
        centred = wants_centre(message.content)
        target = "collection" if wants_collection(message.content) else "queue"
        skipped = [item for kind, item in jobs if kind == "skipped"]
        jobs = [(kind, item) for kind, item in jobs if kind != "skipped"]
        for index, (kind, item) in enumerate(jobs, 1):
            try:
                if kind == "listen":
                    line = await asyncio.to_thread(listen_to, self.ctx, item, target)
                    lines.append(line)
                    log.info("ctx.fm %s: %s", target, item)
                    continue
                if kind == "image":
                    data = await item.read()
                    res = await asyncio.to_thread(glean_screensaver, message.id, index, data,
                                                  item.filename, centred, self.delivery)
                elif kind == "image_url":
                    res = await asyncio.to_thread(glean_screensaver_url, message.id, index, item, centred, self.delivery)
                elif kind == "book":
                    data = await item.read()
                    res = await asyncio.to_thread(glean_book, item.filename, data, self.delivery)
                elif kind == "book_url":
                    res = await asyncio.to_thread(glean_book_url, item, self.delivery)
                elif kind == "url":
                    res = await asyncio.to_thread(glean_url, item, self.delivery)
                elif kind == "attachment":
                    data = await item.read()
                    res = await asyncio.to_thread(glean_attachment, item.filename, data, self.delivery)
                else:
                    res = await asyncio.to_thread(glean_text, item, self.delivery)
                icon = {"article": "📰", "pdf": "📄", "epub": "📘", "note": "📝", "screen": "🖼", "book": "📚"}[res.kind]
                extra = f" ({res.note})" if res.note else ""
                lines.append(f"{icon} **{res.title}**{extra}")
                log.info("delivered %s -> %s", getattr(item, "filename", item), res.stored_as)
            except GleanError as e:
                failed += 1
                linky = kind in ("url", "image_url", "listen", "book_url")
                label = item if linky else getattr(item, "filename", "that text")
                lines.append(f"❌ <{label}>: {e}" if linky else f"❌ {label}: {e}")
            except Exception as e:
                failed += 1
                log.exception("unexpected failure on %r", item)
                lines.append(f"❌ something went wrong ({type(e).__name__}: {e})")

        for names in skipped:
            lines.append(f"_Left out {len(names)} extra file{'s' if len(names) != 1 else ''} "
                         f"that came with the book (cover/details): {', '.join(names)}_")
        await safe_unreact(message, "⏳")
        await safe_react(message, "✅" if failed == 0 else ("⚠️" if failed < len(jobs) else "❌"))
        if failed < len(jobs) and self.kind_of(message.channel) != "listen":
            if self.is_screens(message.channel):
                n = await asyncio.to_thread(self.delivery.count, SCREENS_FOLDER)
                lines.append(f"_Added to Cyby's sleep screens ({n} in rotation)._")
            elif self.kind_of(message.channel) == "books":
                lines.append("_On its way to Cyby's readings, it'll arrive on the next sync._")
            else:
                lines.append("_Ready for Cyby, it'll collect this on its next sync._")
        await message.reply("\n".join(lines)[:1990], mention_author=False, suppress_embeds=True)


DONE_MARKS = ("✅", "⚠️", "❌")


def already_handled(message: discord.Message) -> bool:
    """True if gleaner has finished with this post. A ⏳ left on its own (the
    Mac slept mid-job) doesn't count, so that post is tried again."""
    return any(r.me and str(r.emoji) in DONE_MARKS for r in message.reactions)


def message_jobs(message: discord.Message, kind: str | None = "gleanings") -> list:
    content = (message.content or "").strip()
    jobs = []
    urls = (u.rstrip(").,;:!?>]'\"") for u in URL_RE.findall(content))
    if kind == "listen":
        return [("listen", u) for u in dict.fromkeys(urls)]
    if kind == "sstacks":
        return [("subscribe", u) for u in dict.fromkeys(urls)]
    if kind == "books":
        for url in dict.fromkeys(urls):
            jobs.append(("book_url", url))
        books = [a for a in message.attachments if Path(a.filename).suffix.lower() in BOOK_EXTS]
        extras = [a for a in message.attachments if a not in books]
        if (books or jobs) and all(Path(a.filename).suffix.lower() in BOOK_SIDECARS for a in extras):
            jobs += [("book", a) for a in books]
            if extras:
                jobs.append(("skipped", [a.filename for a in extras]))
        else:
            jobs += [("book", a) for a in message.attachments]
        return jobs
    if kind == "screens":
        for url in dict.fromkeys(urls):
            jobs.append(("image_url", url))
        for att in message.attachments:
            is_image = (att.content_type or "").startswith("image/") or att.filename.lower().endswith(IMAGE_EXTS)
            if is_image:
                jobs.append(("image", att))
        return jobs
    for url in dict.fromkeys(urls):                            # unique, in order
        jobs.append(("url", url))
    for att in message.attachments:
        jobs.append(("attachment", att))
    if not jobs and len(content.split()) >= MIN_TEXT_WORDS:
        jobs.append(("text", content))
    return jobs


async def safe_react(message, emoji):
    try:
        await message.add_reaction(emoji)
    except discord.HTTPException:
        pass


async def safe_unreact(message, emoji):
    try:
        await message.remove_reaction(emoji, message.guild.me)
    except (discord.HTTPException, AttributeError):
        pass


# --------------------------------------------------------------------------
# entry points
# --------------------------------------------------------------------------

def run_test(args: list[str]) -> None:
    """Convert without Discord:  python gleaner.py --test <url|file|"text"> [out_dir]"""
    target = args[0]
    out = Path(args[1]) if len(args) > 1 else Path.cwd() / "gleaner-test"
    s = Settings(discord_token="test", output_dir=out)
    d = Delivery(s)
    if URL_RE.fullmatch(target):
        res = glean_url(target, d)
    elif Path(target).exists():
        res = glean_attachment(Path(target).name, Path(target).read_bytes(), d)
    else:
        res = glean_text(target, d)
    print(f"{res.kind}: {res.title} -> {out / res.stored_as}" + (f" [{res.note}]" if res.note else ""))


def run_sstack_test(args: list[str]) -> None:
    """Try a Substack without Discord:  python gleaner.py --sstack <substack link> [out_dir]
    Shows the latest posts and converts the newest free one."""
    out = Path(args[1]) if len(args) > 1 else Path.cwd() / "gleaner-test"
    base = substack_base(args[0])
    name = substack_name(base)
    posts = substack_posts(base)
    print(f"{name}  <{base}>")
    for p in posts[:6]:
        print(f"  {'paid' if is_paid(p) else 'free'}  {p.get('type')}  {p['date'][:10]}  {p['title']}")
    free = [p for p in posts if not is_paid(p) and p.get("type") in (None, "", "newsletter")]
    if free:
        res = glean_sstack(base, name, free[0], Delivery(Settings(discord_token="test", output_dir=out)))
        print(f"converted: {res.title} -> {out / SSTACKS_FOLDER / res.stored_as} [{res.note}]")


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    logging.getLogger("discord").setLevel(logging.WARNING)
    logging.getLogger("trafilatura").setLevel(logging.ERROR)
    if len(sys.argv) > 1 and sys.argv[1] == "--test":
        run_test(sys.argv[2:])
        return
    if len(sys.argv) > 1 and sys.argv[1] == "--sstack":
        run_sstack_test(sys.argv[2:])
        return
    settings = Settings.load()
    try:
        Gleaner(settings).run(settings.discord_token, log_handler=None)
    except discord.LoginFailure:
        sys.exit("❌ Discord rejected the token. Reset it on the Bot page of the developer portal, "
                 "then delete ~/.gleaner/gleaner.env and run setup.sh again.")
    except discord.PrivilegedIntentsRequired:
        sys.exit("❌ Message Content Intent is switched off. Turn it on (developer portal → gleaner → Bot → "
                 "Privileged Gateway Intents), save, then start gleaner again.")


if __name__ == "__main__":
    main()
