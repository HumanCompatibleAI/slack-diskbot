import os
from typing import List, NamedTuple

import bitmath
import socket
from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError


class Partition(NamedTuple):
    device: str
    mountpoint: str
    fstype: str
    total_bytes: bitmath.Byte
    used_bytes: bitmath.Byte
    free_bytes: bitmath.Byte

    def proportion_free(self) -> float:
        if self.total_bytes == 0:
            return float('nan')
        return self.free_bytes / self.total_bytes

    def report_str(self) -> str:
        free_bytes_str = self.free_bytes.best_prefix().format("{value:.2f} {unit}")
        total_bytes_str = self.total_bytes.best_prefix().format("{value:.2f} {unit}")
        return (
            f"{free_bytes_str} / {total_bytes_str} free space remaining on "
            f"(device={self.device}, mountpoint={self.mountpoint})"
        )


def disk_partitions(include_virtual_devices: bool = False) -> List[Partition]:
    """Reads system partitions and returns them as a list of Partition.

    Based off of https://stackoverflow.com/a/6397492/1091722.
    """
    phydevs = []
    f = open("/proc/filesystems", "r")
    for line in f:
        if not line.startswith("nodev"):
            phydevs.append(line.strip())

    result = []
    f = open('/etc/mtab', "r")
    for line in f:
        if not include_virtual_devices and line.startswith('none'):
            continue
        fields = line.split()
        device = fields[0]
        mountpoint = fields[1]
        fstype = fields[2]
        if not include_virtual_devices and fstype not in phydevs:
            continue
        if device == 'none':
            device = ''

        st = os.statvfs(mountpoint)
        free = (st.f_bavail * st.f_frsize)
        total = (st.f_blocks * st.f_frsize)
        used = (st.f_blocks - st.f_bfree) * st.f_frsize
        # NB: the percentage is -5% than what shown by df due to
        # reserved blocks that we are currently not considering:
        # http://goo.gl/sWGbH
        part = Partition(
            device,
            mountpoint,
            fstype,
            bitmath.Byte(total),
            bitmath.Byte(used),
            bitmath.Byte(free),
        )
        result.append(part)
    return result


def select_disk_partitions() -> List[Partition]:
    """Returns a list of Partition representing the disks that we care to monitor."""
    result = []
    for p in disk_partitions():
        if len(p.mountpoint) > 0 and not p.mountpoint.startswith("/snap") and not p.mountpoint.startswith("/boot"):
            result.append(p)
    return result


def slack_print(msg, token, channel="#slack-bot-playground") -> None:
    # This default token allows write access to any public CHAI channel.
    # Not great if we leak it, but also can't do any harm other than spamming
    # messages at rate-limited 1 message / second.
    client = WebClient(token=token)

    try:
        client.chat_postMessage(
            channel=channel,
            text=msg,
            username="Human-Compatible Disk Alert Bot",
            icon_emoji=":chai:",
        )
    except SlackApiError as e:
        # You will get a SlackApiError if "ok" is False
        assert e.response["ok"] is False
        assert e.response["error"]  # str like 'invalid_auth', 'channel_not_found'
        print(f"Got an error: {e.response['error']}")


MINIMAL_BYTES = bitmath.GB(1000)


def main(minimal_bytes=MINIMAL_BYTES):
    token = os.environ.get('SLACK_BOT_TOKEN')
    if token is None:
        print("Unable to print to Slack because SLACK_BOT_TOKEN env var not set")
        exit(1)

    for part in select_disk_partitions():
        hostname = socket.gethostname()
        if part.free_bytes < minimal_bytes:
            msg = (
                ":robot_face: :hourglass_flowing_sand: :warning: "
                f"WARNING: Low disk space on `{hostname} ({part.device})` "
                f"(threshold: <={MINIMAL_BYTES}).\n"
                f"`{part.report_str()}`"
            )
            print(msg)
            slack_print(msg, token)


if __name__ == '__main__':
    main()
