--[[--
Gleanings: automatic Dropbox sync for gleaner's deliveries.

Uses the Dropbox server and sync folders already set up in KOReader's
Cloud storage (long-press the server -> Synchronize settings), and syncs
them on its own:
  * whenever Wi-Fi connects
  * whenever the device wakes up with Wi-Fi already on
  * on demand: Tools menu -> Gleanings -> Sync now, or a gesture
    ("Sync gleanings" in the Gesture manager)

New files are downloaded once; delete one after reading and it stays gone.

It also mirrors gleaner's screensavers/ folder into /mnt/us/screensavers (images
whose Discord posts were deleted are removed), and can point KOReader's sleep
screen at it: Tools -> Gleanings -> Use #screensaver images as sleep screen.

Files are fetched by their Dropbox id, so titles with curly quotes or
accents work.
--]]--

local DataStorage = require("datastorage")
local Dispatcher = require("dispatcher")
local InfoMessage = require("ui/widget/infomessage")
local JSON = require("json")
local LuaSettings = require("luasettings")
local NetworkMgr = require("ui/network/manager")
local Notification = require("ui/widget/notification")
local UIManager = require("ui/uimanager")
local WidgetContainer = require("ui/widget/container/widgetcontainer")
local http = require("socket.http")
local lfs = require("libs/libkoreader-lfs")
local logger = require("logger")
local ltn12 = require("ltn12")
local socket = require("socket")
local socketutil = require("socketutil")
local _ = require("gettext")

local AUTO_SETTING = "gleanings_auto_sync"
local LAST_SETTING = "gleanings_last_sync"
local SEEN_SETTING = "gleanings_delivered"   -- Dropbox ids already brought down
local SCREENS_FOLDER = "screensavers"
local MIN_GAP = 90          -- seconds between automatic syncs
local AUTO_DELAY = 4        -- give Wi-Fi a moment to settle before syncing

local last_attempt = 0      -- shared by the FileManager and Reader instances
local usingScreens          -- defined further down; used by the menu
local busy = false

local Gleanings = WidgetContainer:extend{
    name = "gleanings",
    is_doc_only = false,
}

function Gleanings:init()
    self:onDispatcherRegisterActions()
    self.ui.menu:registerToMainMenu(self)
end

function Gleanings:onDispatcherRegisterActions()
    Dispatcher:registerAction("gleanings_sync", {
        category = "none", event = "GleaningsSync", title = _("Sync gleanings"), general = true,
    })
end

local function autoEnabled()
    return G_reader_settings:nilOrTrue(AUTO_SETTING)
end

function Gleanings:addToMainMenu(menu_items)
    menu_items.gleanings = {
        text = _("Gleanings"),
        sorting_hint = "tools",
        sub_item_table = {
            {
                text = _("Sync now"),
                keep_menu_open = true,
                callback = function() self:onGleaningsSync() end,
            },
            {
                text = _("Sync automatically (Wi-Fi on / wake-up)"),
                checked_func = autoEnabled,
                callback = function()
                    G_reader_settings:saveSetting(AUTO_SETTING, not autoEnabled())
                end,
            },
            {
                text = _("Use #screensaver images as sleep screen"),
                checked_func = function() return usingScreens() end,
                callback = function() self:toggleScreens() end,
                separator = true,
            },
            {
                text_func = function()
                    local last = G_reader_settings:readSetting(LAST_SETTING)
                    return last and (_("Last synced: ") .. last) or _("Not synced yet")
                end,
                enabled_func = function() return false end,
            },
        },
    }
end

-- ---------------------------------------------------------------- triggers

function Gleanings:onGleaningsSync()
    -- Manual: turn Wi-Fi on if needed, and always report the result.
    NetworkMgr:runWhenOnline(function() self:sync(false) end)
end

function Gleanings:onNetworkConnected()
    self:scheduleAuto()
end

function Gleanings:onResume()
    if NetworkMgr:isWifiOn() then
        self:scheduleAuto()
    end
end

function Gleanings:scheduleAuto()
    if not autoEnabled() then return end
    if os.time() - last_attempt < MIN_GAP then return end
    UIManager:unschedule(self.autoSync)
    UIManager:scheduleIn(AUTO_DELAY, self.autoSync, self)
end

function Gleanings:autoSync()
    if NetworkMgr:isOnline() then
        self:sync(true)
    end
end

-- ---------------------------------------------------------------- dropbox

local function findServer()
    local settings = LuaSettings:open(DataStorage:getSettingsDir() .. "/cloudstorage.lua")
    local servers = settings:readSetting("cs_servers") or {}
    local fallback
    for _, s in ipairs(servers) do
        if s.type == "dropbox" and s.sync_dest_folder and s.sync_dest_folder ~= "" then
            if s.name == "cyby" then return s end
            fallback = fallback or s
        end
    end
    return fallback
end

local function urlencode(str)
    return (tostring(str):gsub("[^%w%-%._~]", function(c) return string.format("%%%02X", c:byte()) end))
end

local function request(args)
    local sink = {}
    args.sink = args.sink or ltn12.sink.table(sink)
    socketutil:set_timeout(socketutil.FILE_BLOCK_TIMEOUT, socketutil.FILE_TOTAL_TIMEOUT)
    local code, _headers, status = socket.skip(1, http.request(args))
    socketutil:reset_timeout()
    return code, table.concat(sink), status
end

local function getToken(server)
    local key, secret = (server.address or ""):match("^([^:]+):(.+)$")
    if not key or not server.password then return nil, "Dropbox login details are missing" end
    local body = "grant_type=refresh_token&refresh_token=" .. urlencode(server.password)
        .. "&client_id=" .. urlencode(key) .. "&client_secret=" .. urlencode(secret)
    local code, resp = request{
        url = "https://api.dropbox.com/oauth2/token",
        method = "POST",
        headers = {
            ["Content-Type"] = "application/x-www-form-urlencoded",
            ["Content-Length"] = #body,
        },
        source = ltn12.source.string(body),
    }
    if code == 200 then
        local ok, data = pcall(JSON.decode, resp)
        if ok and data and data.access_token then return data.access_token end
    end
    logger.warn("Gleanings: token request failed", code, resp)
    return nil, "couldn't log in to Dropbox"
end

local function apiCall(token, endpoint, payload)
    local body = JSON.encode(payload)
    local code, resp = request{
        url = "https://api.dropboxapi.com/2/" .. endpoint,
        method = "POST",
        headers = {
            ["Authorization"] = "Bearer " .. token,
            ["Content-Type"] = "application/json",
            ["Content-Length"] = #body,
        },
        source = ltn12.source.string(body),
    }
    if code == 200 then
        local ok, data = pcall(JSON.decode, resp)
        if ok then return data end
    end
    logger.warn("Gleanings: API call failed", endpoint, code, resp)
end

local function listFiles(token, folder)
    if folder == nil or folder == "/" then folder = "" end
    local data = apiCall(token, "files/list_folder", { path = folder, recursive = false })
    if not data then return nil end
    local files = {}
    while true do
        for _, e in ipairs(data.entries or {}) do
            if e[".tag"] == "file" then
                table.insert(files, { id = e.id, name = e.name, size = tonumber(e.size) })
            end
        end
        if not data.has_more then break end
        data = apiCall(token, "files/list_folder/continue", { cursor = data.cursor })
        if not data then return nil end
    end
    return files
end

local function download(token, file, dest_path)
    local tmp = dest_path .. ".part"
    local fh = io.open(tmp, "wb")
    if not fh then return false end
    -- Fetch by id: the header must be plain ASCII, and ids always are.
    local code = request{
        url = "https://content.dropboxapi.com/2/files/download",
        method = "GET",
        headers = {
            ["Authorization"] = "Bearer " .. token,
            ["Dropbox-API-Arg"] = '{"path":"' .. file.id .. '"}',
        },
        sink = ltn12.sink.file(fh),
    }
    if code == 200 and lfs.attributes(tmp, "size") == file.size then
        os.remove(dest_path)
        return os.rename(tmp, dest_path) and true or false
    end
    os.remove(tmp)
    logger.warn("Gleanings: download failed", file.name, code)
    return false
end

local function safeLocalName(name)
    -- Kindle storage is FAT32: drop characters it can't hold.
    return (name:gsub('[\\/:*?"<>|]', ""))
end

-- ---------------------------------------------------------------- sync

function Gleanings:sync(silent)
    if busy then return end
    busy = true
    last_attempt = os.time()
    local ok, err = pcall(function() self:doSync(silent) end)
    busy = false
    if not ok then
        logger.err("Gleanings: sync crashed", err)
        if not silent then
            UIManager:show(InfoMessage:new{ text = _("Gleanings: sync failed.") })
        end
    end
end

function Gleanings:doSync(silent)
    local function report(text, timeout)
        if silent then
            logger.info("Gleanings:", text)
        else
            UIManager:show(InfoMessage:new{ text = text, timeout = timeout })
        end
    end

    local server = findServer()
    if not server then
        report(_("Gleanings: set up a Dropbox server with sync folders in Cloud storage first."))
        return
    end
    local dest = server.sync_dest_folder
    if lfs.attributes(dest, "mode") ~= "directory" then
        report(_("Gleanings: the local folder doesn't exist:") .. "\n" .. dest)
        return
    end

    local token, why = getToken(server)
    if not token then
        report(_("Gleanings: ") .. why)
        return
    end
    local files = listFiles(token, server.sync_source_folder)
    if not files then
        report(_("Gleanings: couldn't read the Dropbox folder."))
        return
    end

    -- Remember what has been delivered, so articles deleted from the device
    -- after reading don't come back on the next sync.
    local seen = G_reader_settings:readSetting(SEEN_SETTING) or {}
    local got, failed, names = 0, 0, {}
    local still_in_dropbox = {}
    for _, f in ipairs(files) do
        still_in_dropbox[f.id] = true
        local local_path = dest .. "/" .. safeLocalName(f.name)
        local local_size = lfs.attributes(local_path, "size")
        if local_size == f.size then
            seen[f.id] = true                -- already here (e.g. from an earlier manual sync)
        elseif not seen[f.id] then
            if download(token, f, local_path) then
                got = got + 1
                seen[f.id] = true
                table.insert(names, f.name)
            else
                failed = failed + 1
            end
        end
    end
    for id in pairs(seen) do                 -- forget files cleared out of Dropbox
        if not still_in_dropbox[id] then seen[id] = nil end
    end
    G_reader_settings:saveSetting(SEEN_SETTING, seen)

    local s_got, s_gone, s_failed = self:syncScreens(token, server)
    failed = failed + s_failed

    G_reader_settings:saveSetting(LAST_SETTING, os.date("%d %b %H:%M"))

    if got > 0 then
        local FileManager = require("apps/filemanager/filemanager")
        if FileManager.instance and FileManager.instance.file_chooser then
            FileManager.instance.file_chooser:refreshPath()
        end
    end

    local function plural(n, one, many) return n == 1 and one or string.format(many, n) end
    if silent then
        local bits = {}
        if got > 0 then table.insert(bits, plural(got, _("1 new gleaning"), _("%d new gleanings"))) end
        if s_got > 0 then table.insert(bits, plural(s_got, _("1 new sleep screen"), _("%d new sleep screens"))) end
        if #bits > 0 then UIManager:show(Notification:new{ text = table.concat(bits, ", ") }) end
        if failed > 0 then logger.warn("Gleanings:", failed, "file(s) failed") end
        return
    end

    local text
    if got == 0 and s_got == 0 and s_gone == 0 and failed == 0 then
        text = _("Gleanings: nothing new.")
    else
        text = string.format(_("Gleanings: %d new."), got)
        if got > 0 and got <= 5 then
            text = text .. "\n\n" .. table.concat(names, "\n")
        end
        if s_got > 0 or s_gone > 0 then
            text = text .. "\n\n" .. string.format(_("Sleep screens: %d added, %d removed."), s_got, s_gone)
        end
        if failed > 0 then
            text = text .. "\n\n" .. string.format(_("%d couldn't be downloaded; try again later."), failed)
        end
    end
    report(text, got == 0 and s_got == 0 and s_gone == 0 and failed == 0 and 2 or nil)
end

-- ---------------------------------------------------------------- sleep screens

-- Sleep-screen images live outside documents/ so they don't clutter the library:
-- /mnt/us/screensavers on a Kindle.
function Gleanings.screensDir()
    local server = findServer()
    local dest = server and server.sync_dest_folder or ""
    local root = dest:match("^(/mnt/us)/") or dest:match("^(.*)/[^/]+/[^/]+$") or DataStorage:getDataDir()
    return root .. "/" .. SCREENS_FOLDER
end

-- Mirror Dropbox's screensavers/ folder: add what's new, and remove images
-- whose posts were deleted in Discord. Only ever touches this one folder.
function Gleanings:syncScreens(token, server)
    local src = server.sync_source_folder
    if src == nil or src == "/" then src = "" end
    local remote = listFiles(token, src .. "/" .. SCREENS_FOLDER)
    if not remote then return 0, 0, 0 end    -- no folder yet (or no network): change nothing
    local dir = Gleanings.screensDir()
    if lfs.attributes(dir, "mode") ~= "directory" then
        lfs.mkdir(dir)
    end
    local got, gone, failed = 0, 0, 0
    local keep = {}
    for _, f in ipairs(remote) do
        local name = safeLocalName(f.name)
        keep[name] = true
        local path = dir .. "/" .. name
        if lfs.attributes(path, "size") ~= f.size then
            if download(token, f, path) then got = got + 1 else failed = failed + 1 end
        end
    end
    for name in lfs.dir(dir) do
        if name ~= "." and name ~= ".." and not keep[name] and name:lower():match("%.png$") then
            if os.remove(dir .. "/" .. name) then gone = gone + 1 end
        end
    end
    return got, gone, failed
end

usingScreens = function()
    return G_reader_settings:readSetting("screensaver_type") == "random_image"
        and G_reader_settings:readSetting("screensaver_dir") == Gleanings.screensDir()
end

function Gleanings:toggleScreens()
    if usingScreens() then
        G_reader_settings:saveSetting("screensaver_type", "cover")
        UIManager:show(InfoMessage:new{ text = _("Sleep screen set back to the book cover."), timeout = 3 })
        return
    end
    local dir = Gleanings.screensDir()
    if lfs.attributes(dir, "mode") ~= "directory" then lfs.mkdir(dir) end
    G_reader_settings:saveSetting("screensaver_type", "random_image")
    G_reader_settings:saveSetting("screensaver_dir", dir)
    G_reader_settings:makeFalse("screensaver_show_message")       -- no "Sleeping" over the picture
    G_reader_settings:saveSetting("screensaver_img_background", "white")
    G_reader_settings:makeFalse("screensaver_stretch_images")     -- show exactly as gleaner laid it out
    G_reader_settings:makeFalse("screensaver_cycle_images_alphabetically")
    local n = 0
    for name in lfs.dir(dir) do
        if name:lower():match("%.png$") then n = n + 1 end
    end
    UIManager:show(InfoMessage:new{
        text = n > 0 and string.format(_("Cyby will show one of %d images each time it sleeps."), n)
            or _("Done. Post images in #screensaver, then sync, and they'll appear when Cyby sleeps."),
    })
end

return Gleanings
