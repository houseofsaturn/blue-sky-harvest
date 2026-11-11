-- Shows "cyby" instead of "KOReader" in the title bar of KOReader's home screen
-- (the file browser). Copy to koreader/patches/ on the Kindle and restart KOReader.
-- To use a different name, change the text between the quotes.
local FileManager = require("apps/filemanager/filemanager")
FileManager.title = "cyby"
