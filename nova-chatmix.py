#!/usr/bin/python3

# Licensed under the 0BSD

from signal import SIGINT, SIGTERM, signal
from subprocess import Popen, check_output

from hid import device
from hid import enumerate as hidenumerate

CMD_PACTL = "pactl"
CMD_PWLOOPBACK = "pw-loopback"


class SinkInfo:

    _COLUMN_COUNT = 5
    _COLUMN_INDEX__SINK_ID = 0
    _COLUMN_INDEX__NAME = 1
    _COLUMN_INDEX__PROTOCOL = 2
    _COLUMN_INDEX__AUDIO_METADATA = 3
    _COLUMN_INDEX__STATE = 4

    _METADATA_COLUMN_COUNT = 3
    _METADATA_INDEX__SAMPLE_FORMAT = 0
    _METADATA_INDEX__CHANNELS = 1
    _METADATA_INDEX__SAMPLE_RATE = 2

    def __init__(self, sink_id: int, name: str, protocol: str, sample_format: str, channels: str, sample_rate: str, state: str):
        self.sink_id = sink_id
        self.name = name
        self.protocol = protocol
        self.sample_format = sample_format

        try:
            self.channels = int(channels[:-2])
        except ValueError:
            raise Exception(f"Unable to parse channels for sink '{self.name}': '{channels}'")

        try:
            self.sample_rate = int(sample_rate[:-2])
        except ValueError:
            raise Exception(f"Unable to parse sample rate for '{self.name}': '{sample_rate}'")

        self.state = state

    @staticmethod
    def _split_columns(line: str, seperator: str, expected_column_count: int):
        columns = line.split(seperator)
        column_count = len(columns)
        if (expected_column_count != column_count):
            raise Exception(f"""Unable to parse columns from '{CMD_PACTL} {' '.join(SinkInfo.CMD_ARGUMENTS)}'
            {line}
            Expected column count: {expected_column_count}
            Received column count: {column_count}""")
        return columns

    @staticmethod
    def from_line(line: str):
        columns = SinkInfo._split_columns(line, "\t", SinkInfo._COLUMN_COUNT)
        metadata_columns = SinkInfo._split_columns(columns[SinkInfo._COLUMN_INDEX__AUDIO_METADATA], " ", SinkInfo._METADATA_COLUMN_COUNT)
        return SinkInfo(columns[SinkInfo._COLUMN_INDEX__SINK_ID]
            , columns[SinkInfo._COLUMN_INDEX__NAME]
            , columns[SinkInfo._COLUMN_INDEX__PROTOCOL]
            , metadata_columns[SinkInfo._METADATA_INDEX__SAMPLE_FORMAT]
            , metadata_columns[SinkInfo._METADATA_INDEX__CHANNELS]
            , metadata_columns[SinkInfo._METADATA_INDEX__SAMPLE_RATE]
            , columns[SinkInfo._COLUMN_INDEX__STATE]
        )

    @staticmethod
    def ResolveList():
        output_lines = check_output([CMD_PACTL, "list", "short", "sinks"]).decode().split("\n")
        return [SinkInfo.from_line(line) for line in output_lines if line is not None and len(line) > 0]


class ChatMix:
    # Create virtual pipewire sinks
    def __init__(self, output_sink: SinkInfo, main_sink: str, chat_sink: str):
        self.main_sink = main_sink
        self.chat_sink = chat_sink
        self.main_sink_process = self._create_virtual_sink(main_sink, output_sink)
        self.chat_sink_process = self._create_virtual_sink(chat_sink, output_sink)

    def set_main_volume(self, volume: int):
        self._set_volume(self.main_sink, volume)

    def set_chat_volume(self, volume: int):
        self._set_volume(self.chat_sink, volume)

    def set_volumes(self, main_volume: int, chat_volume: int):
        self.set_main_volume(main_volume)
        self.set_chat_volume(chat_volume)

    def close(self):
        self.main_sink_process.terminate()
        self.chat_sink_process.terminate()

    def _create_virtual_sink(self, name: str, output_sink: SinkInfo) -> Popen:
        audio_prop_list = [
            f"audio.format={output_sink.sample_format}",
            f"audio.rate={output_sink.sample_rate}",
            f"audio.channels={output_sink.channels}"
        ]
        audio_props = ','.join(audio_prop_list)

        return Popen(
            [
                CMD_PWLOOPBACK,
                "-P",
                output_sink.name,
                f"--capture-props=media.class=Audio/Sink,{audio_props}",
                "-n",
                name,
            ]
        )

    def _set_volume(self, sink: str, volume: int):
        Popen([CMD_PACTL, "set-sink-volume", f"input.{sink}", f"{volume}%"])


class NovaProWireless:
    # USB VendorID
    VID = 0x1038
    # USB ProductIDs for Acrtis Nova Pro Wireless & Wired
    PID_LIST = [0x12E0, 0x12E5, 0x12CB, 0x12CD]

    # bInterfaceNumber
    INTERFACE = 0x4

    # HID Message length
    MSGLEN = 63

    # Message read timeout
    READ_TIMEOUT = 1000

    # First byte controls data direction.
    TX = 0x6  # To base station.
    RX = 0x7  # From base station.

    # Second Byte
    # This is a very limited list of options, you can control way more. I just haven't implemented those options (yet)
    ## As far as I know, this only controls the icon.
    OPT_SONAR_ICON = 0x8D
    ## Enabling this option enables the ability to switch between volume and ChatMix.
    OPT_CHATMIX_ENABLE = 0x49
    ## Volume controls, 1 byte
    OPT_VOLUME = 0x25
    ## ChatMix controls, 2 bytes show and control game and chat volume.
    OPT_CHATMIX = 0x45
    ## EQ controls, 2 bytes show and control which band and what value.
    OPT_EQ = 0x31
    ## EQ preset controls, 1 byte sets and shows enabled preset. Preset 4 is the custom preset required for OPT_EQ.
    OPT_EQ_PRESET = 0x2E

    # PipeWire Names
    ## String used to automatically select output sink
    PW_OUTPUT_SINK_AUTODETECT = "SteelSeries_Arctis_Nova_Pro"
    ## Names of virtual sound devices
    PW_GAME_SINK = "NovaGame"
    PW_CHAT_SINK = "NovaChat"

    # Keeps track of enabled features for when close() is called
    CHATMIX_CONTROLS_ENABLED = False
    SONAR_ICON_ENABLED = False

    # Stops processes when program exits
    CLOSE = False

    # Device not found error string
    ERR_NOTFOUND = "Device not found"

    @staticmethod
    def ResolveHidDevPath():
        for pid in NovaProWireless.PID_LIST:
            for hiddev in hidenumerate(NovaProWireless.VID, pid):
                if hiddev["interface_number"] == NovaProWireless.INTERFACE:
                    return hiddev["path"]
        raise DeviceNotFoundException

    # Selects correct device, and makes sure we can control it
    def __init__(self, output_sink=None):
        # Find HID device path
        devpath = NovaProWireless.ResolveHidDevPath()

        # Try to automatically detect output sink, this is skipped if output_sink is given
        if not output_sink:
            sinks = SinkInfo.ResolveList()
            for sink in sinks:
                if self.PW_OUTPUT_SINK_AUTODETECT in sink.name:
                    output_sink = sink

        self.dev = device()
        self.dev.open_path(devpath)
        self.dev.set_nonblocking(True)
        self.output_sink = output_sink

    # Enables/Disables chatmix controls
    def set_chatmix_controls(self, state: bool):
        assert self.dev, self.ERR_NOTFOUND
        self.dev.write(
            self._create_msgdata((self.TX, self.OPT_CHATMIX_ENABLE, int(state))),
        )
        self.CHATMIX_CONTROLS_ENABLED = state

    # Enables/Disables Sonar Icon
    def set_sonar_icon(self, state: bool):
        assert self.dev, self.ERR_NOTFOUND
        self.dev.write(
            self._create_msgdata((self.TX, self.OPT_SONAR_ICON, int(state))),
        )
        self.SONAR_ICON_ENABLED = state

    # Sets Volume
    def set_volume(self, attenuation: int):
        assert self.dev, self.ERR_NOTFOUND
        self.dev.write(
            self._create_msgdata((self.TX, self.OPT_VOLUME, attenuation)),
        )

    # Sets EQ preset
    def set_eq_preset(self, preset: int):
        assert self.dev, self.ERR_NOTFOUND
        self.dev.write(
            self._create_msgdata((self.TX, self.OPT_EQ_PRESET, preset)),
        )

    # ChatMix implementation
    # Continuously read from base station and ignore everything but ChatMix messages (OPT_CHATMIX)
    def chatmix_volume_control(self, chatmix: ChatMix):
        assert self.dev, self.ERR_NOTFOUND
        while not self.CLOSE:
            try:
                msg = self.dev.read(self.MSGLEN, self.READ_TIMEOUT)
                if not msg or msg[1] is not self.OPT_CHATMIX:
                    continue

                # 4th and 5th byte contain ChatMix data
                gamevol = msg[2]
                chatvol = msg[3]

                # Actually change volume. Everytime you turn the dial, both volumes are set to the correct level
                chatmix.set_volumes(gamevol, chatvol)
            except OSError:
                print("Device was probably disconnected, exiting.")
                self.CLOSE = True
        # Remove virtual sinks on exit
        chatmix.close()

    # Prints output from base station. `debug` argument enables raw output.
    def print_output(self, debug: bool = False):
        assert self.dev
        while not self.CLOSE:
            msg = self.dev.read(self.MSGLEN, self.READ_TIMEOUT)
            if debug:
                print(msg)
            match msg[1]:
                case self.OPT_VOLUME:
                    print(f"Volume: -{msg[2]}")
                case self.OPT_CHATMIX:
                    print(f"Game Volume: {msg[2]} - Chat Volume: {msg[3]}")
                case self.OPT_EQ:
                    print(f"EQ: Bar: {msg[2]} - Value: {(msg[3] - 20) / 2}")
                case self.OPT_EQ_PRESET:
                    print(f"EQ Preset: {msg[2]}")
                case _:
                    print("Unknown Message")

    # Terminates processes and disables features
    def close(self, signum, frame):
        self.CLOSE = True
        if self.CHATMIX_CONTROLS_ENABLED:
            self.set_chatmix_controls(False)
        if self.SONAR_ICON_ENABLED:
            self.set_sonar_icon(False)

    # Takes a tuple of ints and turns it into bytes with the correct length padded with zeroes
    def _create_msgdata(self, data: tuple[int, ...]) -> bytes:
        return bytes(data).ljust(self.MSGLEN, b"\0")


class DeviceNotFoundException(Exception):
    pass


# When run directly, just start the ChatMix implementation. (And activate the icon, just for fun)
if __name__ == "__main__":
    try:
        nova = NovaProWireless()
        nova.set_sonar_icon(state=True)
        nova.set_chatmix_controls(state=True)

        signal(SIGINT, nova.close)
        signal(SIGTERM, nova.close)

        assert nova.output_sink, "Output sink not set"
        chatmix = ChatMix(
            output_sink=nova.output_sink,
            main_sink=nova.PW_GAME_SINK,
            chat_sink=nova.PW_CHAT_SINK,
        )

        nova.chatmix_volume_control(chatmix=chatmix)
    except DeviceNotFoundException:
        print("Device not found, exiting.")
