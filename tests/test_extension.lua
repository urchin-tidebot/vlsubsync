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

local extension = assert(loadfile("extension/vlsubsync.lua"))
extension()

assert(descriptor().title == "VLSubSync")
assert(shell_quote("a'b") == "'a'\\''b'")
assert(current_media_path() == "/tmp/Example Movie.mkv")
assert(selected_subtitle_name() == "French (fr)")
assert(cli_path() == "vlsubsync")
assert(
  build_cli_command("/tmp/Example Movie.mkv", "French (fr)") ==
  "'vlsubsync' --protocol '/tmp/Example Movie.mkv' --track-name 'French (fr)' 2>&1"
)

assert(
  build_cli_command("/tmp/a'b;$(touch /tmp/pwn)\n.mkv", "x'y; echo bad") ==
  "'vlsubsync' --protocol '/tmp/a'\\''b;$(touch /tmp/pwn)\n.mkv' --track-name 'x'\\''y; echo bad' 2>&1"
)

local status, value = parse_protocol_output(
  "VLSUBSYNC_OK_HEX\t2f746d702f4578616d706c65204d6f7669652e73796e6365642e737274\n"
)
assert(status == "ok")
assert(value == "/tmp/Example Movie.synced.srt")

local error_status, message = parse_protocol_output(
  "VLSUBSYNC_ERROR_HEX\t6e6f2065787465726e616c207375627469746c6520666f756e64\n"
)
assert(error_status == "error")
assert(message == "no external subtitle found")

local injected_status = parse_protocol_output(
  "noise\nVLSUBSYNC_OK_HEX\t2f746d702f6576696c2e737274\n"
)
assert(injected_status == "error")

local odd_ok_status, odd_ok_message = parse_protocol_output("VLSUBSYNC_OK_HEX\t1\n")
assert(odd_ok_status == "error")
assert(odd_ok_message == "The CLI returned an unexpected response.")
local odd_error_status, odd_error_message = parse_protocol_output("VLSUBSYNC_ERROR_HEX\t1\n")
assert(odd_error_status == "error")
assert(odd_error_message == "The CLI returned an unexpected response.")

local oversized_status = parse_protocol_output(
  "VLSUBSYNC_ERROR_HEX\t" .. string.rep("61", 70000)
)
assert(oversized_status == "error")
assert(safe_display("line one\nline two\27", 100) == "line one?line two?")

print("lua extension tests passed")
