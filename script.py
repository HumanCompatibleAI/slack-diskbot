import argparse
import os
import socket
from typing import List, NamedTuple

import bitmath
import bitmath.integrations
import slack_sdk
import slack_sdk.errors


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
    client = slack_sdk.WebClient(token=token)

    try:
        client.chat_postMessage(
            channel=channel,
            text=msg,
            username="Human-Compatible Disk Alert Bot",
            icon_emoji=":chai:",
        )
    except slack_sdk.errors.SlackApiError as e:
        # You will get a SlackApiError if "ok" is False
        assert e.response["ok"] is False
        assert e.response["error"]  # str like 'invalid_auth', 'channel_not_found'
        print(f"Got an error: {e.response['error']}")


def main(token: str, warning_threshold: bitmath.Bitmath, channel: str) -> None:
    token = token or os.environ.get('SLACK_BOT_TOKEN')
    if token is None:
        print("Unable to print to Slack because SLACK_BOT_TOKEN env var not set")
        exit(1)

    for part in select_disk_partitions():
        if part.free_bytes < warning_threshold:
            msg = (
                ":robot_face: :hourglass_flowing_sand: :warning: "
                f"WARNING: Low disk space on `{socket.getfqdn()} ({part.device})` "
                f"(threshold: <={warning_threshold}).\n"
                f"`{part.report_str()}`"
            )
            print(msg)
            slack_print(msg, token, channel)


def console_main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--threshold",
        type=bitmath.integrations.BitmathType,
        default="10GB",
        help="The disk space threshold (e.g. '10GB' or '5MB') that sets off a low disk "
             "space warning.")
    parser.add_argument(
        "--channel",
        type=str,
        help="Name of slack channel to post to (e.g. #compute)",
        default="#slack-bot-playground",
    )
    parser.add_argument(
        "--token",
        type=str,
        help="Slack token (can also be provided via SLACK_BOT_TOKEN env var)."
    )
    args = parser.parse_args()
    main(
        token=args.token, warning_threshold=args.threshold,
        channel=args.channel,
    )


if __name__ == '__main__':
    console_main()
