local fake_item = {
  uri = function() return "file:///tmp/Example%20Movie.mkv" end
}

vlc = {
  player = {
    item = function() return fake_item end,
    get_spu_tracks = function()
      return {
        { name = "English", selected = false },
        { name = "French (fr)", selected = true },
      }
    end,
  },
  strings = {
    make_path = function(uri)
      assert(uri == "file:///tmp/Example%20Movie.mkv")
      return "/tmp/Example Movie.mkv"
    end,
  },
  msg = { info = function() end, err = function() end },
}

local extension = assert(loadfile("vlsubsync.lua"))
extension()

assert(descriptor().title == "VLSubSync")
assert(shell_quote("a'b") == "'a'\\''b'")
assert(current_media_path() == "/tmp/Example Movie.mkv")
assert(selected_subtitle_name() == "French (fr)")

local status, value = parse_helper_output(
  "VLSUBSYNC_OK_HEX\t2f746d702f4578616d706c65204d6f7669652e73796e6365642e737274\n"
)
assert(status == "ok")
assert(value == "/tmp/Example Movie.synced.srt")

local error_status, message = parse_helper_output(
  "VLSUBSYNC_ERROR_HEX\t6e6f2065787465726e616c207375627469746c6520666f756e64\n"
)
assert(error_status == "error")
assert(message == "no external subtitle found")

local injected_status = parse_helper_output(
  "noise\nVLSUBSYNC_OK_HEX\t2f746d702f6576696c2e737274\n"
)
assert(injected_status == "error")

print("lua extension tests passed")
