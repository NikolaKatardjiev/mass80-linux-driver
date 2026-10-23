#!/usr/bin/env python3
"""Mass80 screen protocol probe.

Logs everything the screen's ESP32 sends over CDC-ACM, survives
re-enumeration (the device disconnects on theme change / reboot), and can
optionally answer requests with candidate replies so we can observe how the
firmware reacts.

Usage:
    tools/probe.py [--log captures/probe.log] [--reply] [--quiet-debug]

While running, lines typed on stdin are sent verbatim (plus "\n") to the device.
"""
import argparse
import glob
import json
import os
import select
import sys
import time

import serial

VID, PID = "303a", "4003"


def find_port():
    for tty in glob.glob("/sys/class/tty/ttyACM*"):
        dev = os.path.realpath(os.path.join(tty, "device"))
        usb = os.path.dirname(dev)
        try:
            vid = open(os.path.join(usb, "idVendor")).read().strip()
            pid = open(os.path.join(usb, "idProduct")).read().strip()
        except OSError:
            continue
        if (vid, pid) == (VID, PID):
            return "/dev/" + os.path.basename(tty)
    return None


def candidate_reply(msg):
    """Best-guess replies; refined as the protocol is confirmed."""
    action = msg.get("action")
    if action == "get_time":
        t = time.localtime()
        off = -time.timezone if not t.tm_isdst else -time.altzone
        return {
            "action": "get_time",
            "time": time.strftime("%Y-%m-%d %H:%M:%S", t),
            "timezone": off // 60,
        }
    if action == "get_music_info":
        return {
            "action": "get_music_info",
            "title": "Linux probe",
            "artist": "mass80_driver",
            "progress": 30,
            "duration": 180,
            "state": "playing",
        }
    if action == "get_performance":
        return {
            "action": "get_performance",
            "cpu_usage": 42,
            "memory_usage": 55,
            "cpu_freq": 4200,
            "cpu_freq_full": 5000,
            "cpu_temp": 61,
            "net_upload": 100,
            "net_download": 2000,
        }
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--log", default="captures/probe.log")
    ap.add_argument("--reply", action="store_true", help="send candidate replies")
    ap.add_argument("--quiet-debug", action="store_true",
                    help="don't echo firmware debug lines to the terminal")
    args = ap.parse_args()

    log = open(args.log, "a", buffering=1)

    def emit(direction, text):
        stamp = time.strftime("%H:%M:%S")
        line = f"{stamp} {direction} {text}"
        log.write(line + "\n")
        if not (args.quiet_debug and direction == "DBG"):
            print(line, flush=True)

    while True:
        port = find_port()
        if not port:
            time.sleep(0.5)
            continue
        try:
            ser = serial.Serial(port, 115200, timeout=0)
            ser.dtr = True
            ser.rts = True
        except serial.SerialException as e:
            emit("ERR", f"open {port}: {e}")
            time.sleep(1)
            continue
        emit("SYS", f"connected {port}")
        buf = b""
        try:
            while True:
                r, _, _ = select.select([ser.fileno(), sys.stdin], [], [], 1.0)
                if sys.stdin in r:
                    out = sys.stdin.readline()
                    if out:
                        ser.write(out.rstrip("\n").encode() + b"\n")
                        emit("TX ", out.rstrip("\n"))
                if ser.fileno() in r:
                    data = ser.read(65536)
                    if not data:
                        raise serial.SerialException("EOF")
                    buf += data
                    while b"\n" in buf:
                        raw, buf = buf.split(b"\n", 1)
                        text = raw.decode("utf-8", "replace").strip()
                        if not text:
                            continue
                        if text.startswith("{"):
                            emit("RX ", text)
                            if args.reply:
                                try:
                                    reply = candidate_reply(json.loads(text))
                                except json.JSONDecodeError:
                                    reply = None
                                if reply:
                                    s = json.dumps(reply, ensure_ascii=False)
                                    ser.write(s.encode() + b"\n")
                                    emit("TX ", s)
                        else:
                            emit("DBG", text)
        except (serial.SerialException, OSError) as e:
            emit("SYS", f"disconnected: {e}")
            try:
                ser.close()
            except Exception:
                pass
            time.sleep(0.5)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        pass
