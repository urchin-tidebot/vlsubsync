-- VLSubSync: one-click synchronization of the current external subtitle.
-- SPDX-License-Identifier: MIT

local dialog = nil
local status_label = nil
local packaged_helper = nil

function descriptor()
  return {
    title = "VLSubSync",
    version = "0.1.0",
    author = "urchin-tidebot",
    shortdesc = "Resync current subtitles",
    description = "Align the current external subtitle with the playing media.",
    capabilities = { "menu", "input-listener" },
  }
end

function shell_quote(value)
  return "'" .. string.gsub(value, "'", "'\\''") .. "'"
end

function current_item()
  if vlc.player and vlc.player.item then
    return vlc.player.item()
  end
  if vlc.input and vlc.input.item then
    return vlc.input.item()
  end
  return nil
end

function current_media_path()
  local item = current_item()
  if not item then
    return nil, "No media is loaded."
  end

  local uri = item:uri()
  local path = vlc.strings.make_path(uri)
  if not path then
    return nil, "VLSubSync currently supports local media files only."
  end
  return path
end

function selected_subtitle_name()
  if not (vlc.player and vlc.player.get_spu_tracks) then
    return nil
  end
  for _, track in ipairs(vlc.player.get_spu_tracks()) do
    if track.selected then
      return track.name
    end
  end
  return nil
end

local function decode_hex(value)
  if string.len(value) % 2 ~= 0 or string.find(value, "[^0-9a-f]") then
    return nil
  end
  return string.gsub(value, "(%x%x)", function(byte)
    return string.char(tonumber(byte, 16))
  end)
end

function parse_helper_output(output)
  local line = output
  if string.sub(line, -2) == "\r\n" then
    line = string.sub(line, 1, -3)
  elseif string.sub(line, -1) == "\n" then
    line = string.sub(line, 1, -2)
  end

  local ok_hex = string.match(line, "^VLSUBSYNC_OK_HEX\t([0-9a-f]+)$")
  if ok_hex then
    return "ok", decode_hex(ok_hex)
  end
  local error_hex = string.match(line, "^VLSUBSYNC_ERROR_HEX\t([0-9a-f]+)$")
  if error_hex then
    return "error", decode_hex(error_hex)
  end
  return "error", "The helper returned an unexpected response."
end

local function helper_path()
  if packaged_helper then
    return packaged_helper
  end

  local configured = os.getenv("VLSUBSYNC_HELPER")
  if configured and configured ~= "" then
    return configured
  end

  if vlc.config and vlc.config.homedir then
    local installed = vlc.config.homedir() .. "/.local/bin/vlsubsync-helper"
    local file = io.open(installed, "r")
    if file then
      file:close()
      return installed
    end
  end
  return "vlsubsync-helper"
end

local function add_subtitle(path)
  if vlc.player and vlc.player.add_subtitle then
    return vlc.player.add_subtitle(path, true)
  end
  if vlc.input and vlc.input.add_subtitle then
    return vlc.input.add_subtitle(path)
  end
  return false
end

local function set_status(message)
  if status_label then
    status_label:set_text(message)
  end
  if dialog then
    dialog:update()
  end
end

function sync_current()
  local media, media_error = current_media_path()
  if not media then
    set_status("Error: " .. media_error)
    return
  end

  set_status("Analyzing audio; playback can continue…")
  local command = shell_quote(helper_path()) .. " " .. shell_quote(media)
  local track_name = selected_subtitle_name()
  if track_name then
    command = command .. " --track-name " .. shell_quote(track_name)
  end
  command = command .. " 2>&1"

  vlc.msg.info("[VLSubSync] Running helper for " .. media)
  local pipe = io.popen(command, "r")
  if not pipe then
    set_status("Error: could not start vlsubsync-helper.")
    return
  end
  local output = pipe:read("*a")
  pipe:close()

  local result, value = parse_helper_output(output)
  if result ~= "ok" then
    vlc.msg.err("[VLSubSync] " .. value)
    set_status("Error: " .. value)
    return
  end

  if add_subtitle(value) then
    set_status("Loaded corrected subtitle: " .. value)
    vlc.msg.info("[VLSubSync] Loaded " .. value)
  else
    set_status("Created corrected subtitle, but VLC could not load it: " .. value)
  end
end

function activate()
  dialog = vlc.dialog("VLSubSync")
  dialog:add_label(
    "Synchronize the most likely external subtitle beside the current media.",
    1, 1, 2, 1
  )
  dialog:add_button("Resync current subtitles", sync_current, 1, 2, 1, 1)
  status_label = dialog:add_label("Ready.", 1, 3, 2, 1)
  dialog:show()
end

function menu()
  return { "Open VLSubSync" }
end

function trigger_menu(_)
  if dialog then
    dialog:show()
  end
end

function input_changed()
  set_status("Ready for the current media.")
end

function deactivate()
  if dialog then
    dialog:delete()
    dialog = nil
    status_label = nil
  end
end

function close()
  vlc.deactivate()
end
