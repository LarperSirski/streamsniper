"""YouTube monitoring and recording engine, independent of the Qt interface."""
import json
import logging
import os
import re
import signal
import subprocess
import sys
import threading
import time
from pathlib import Path
from urllib.parse import quote

import feedparser
import requests

from config import (
    DATA_DIR, DISCORD_WEBHOOK, POLL_SECONDS, VIDEO_EXTENSIONS,
)
from database import connect, mark_seen
from recording_utils import (
    find_recording_file, recover_partial_recording, write_stream_metadata,
)


def yt_dlp_command(*args):
    command = [sys.executable]
    if getattr(sys, "frozen", False):
        command.append("--yt-dlp-worker")
    else:
        command.extend(("-m", "yt_dlp"))
    return [*command, *map(str, args)]


class Monitor:
    def __init__(self, event_callback):
        self.emit = event_callback
        self.stop_event = threading.Event()
        self.thread = None
        self.recording = set()
        self.active_recordings = {}
        self.live_streams = {}
        self.lock = threading.Lock()

    @property
    def running(self):
        return bool(self.thread and self.thread.is_alive() and not self.stop_event.is_set())

    def say(self, message):
        self.emit(message)

    def notify(self, message):
        if not DISCORD_WEBHOOK:
            return
        try:
            requests.post(DISCORD_WEBHOOK, json={"content": message[:1900]}, timeout=15).raise_for_status()
        except Exception:
            logging.exception("Discord notification failed")
            self.say("Discord notification failed. Check the local log for details.")

    @staticmethod
    def run_ytdlp(*args, timeout=None):
        return subprocess.run(
            yt_dlp_command(*args),
            capture_output=True, text=True, timeout=timeout,
        )

    @staticmethod
    def safe_name(value):
        cleaned = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", value or "recording")
        return cleaned.strip(" .")[:100] or "recording"

    @staticmethod
    def resolve_channel(url):
        try:
            result = Monitor.run_ytdlp(
                "--flat-playlist", "--playlist-items", "1", "--dump-single-json",
                url, timeout=45,
            )
            if result.returncode == 0 and result.stdout.strip():
                payload = json.loads(result.stdout.splitlines()[-1])
                return payload.get("channel_id") or payload.get("id")
        except Exception:
            logging.exception("Channel resolve failed: %s", url)
        return None

    def channels(self):
        with connect() as con:
            return con.execute(
                "SELECT url, label, auto_record FROM channels WHERE enabled=1"
            ).fetchall()

    def live_streams_snapshot(self):
        with self.lock:
            return [dict(stream) for stream in self.live_streams.values()]

    def active_recordings_snapshot(self):
        with self.lock:
            return [
                {key: value for key, value in recording.items() if key != "process"}
                for recording in self.active_recordings.values()
            ]

    def start_recording(self, video_id, title, link, label, duration_seconds=None):
        if duration_seconds is not None and duration_seconds <= 0:
            return False
        with self.lock:
            if video_id in self.recording:
                return False
            self.recording.add(video_id)
            self.active_recordings[video_id] = {
                "video_id": video_id,
                "title": title,
                "link": link,
                "channel": label,
                "duration_seconds": duration_seconds,
                "started_at": time.time(),
                "stop_requested": False,
                "stop_reason": None,
                "process": None,
            }

        threading.Thread(
            target=self.record,
            args=(video_id, title, link, label, duration_seconds),
            daemon=True,
            name=f"StreamSniperRecording-{video_id}",
        ).start()
        return True

    def stop_recording(self, video_id):
        with self.lock:
            recording = self.active_recordings.get(video_id)
            if not recording:
                return False
            recording["stop_requested"] = True
            recording["stop_reason"] = "manual"
        self.say(f"Stopping recording: {recording['channel']} — {recording['title']}")
        return True

    def _set_live_stream(self, url, label, video_id, title, link):
        with self.lock:
            self.live_streams[video_id] = {
                "channel_url": url,
                "channel": label,
                "video_id": video_id,
                "title": title,
                "link": link,
            }

    def _clear_live_streams_for_channel(self, url):
        with self.lock:
            stale_ids = [
                video_id for video_id, stream in self.live_streams.items()
                if stream["channel_url"] == url
            ]
            for video_id in stale_ids:
                self.live_streams.pop(video_id, None)

    @staticmethod
    def _request_process_stop(process):
        if process.poll() is not None:
            return
        try:
            if os.name == "nt":
                process.send_signal(signal.CTRL_BREAK_EVENT)
            else:
                process.terminate()
        except (OSError, AttributeError, ValueError):
            try:
                process.terminate()
            except OSError:
                logging.exception("Could not stop yt-dlp process")

    @staticmethod
    def _force_stop_process_tree(process):
        if process.poll() is not None:
            return
        if os.name == "nt":
            subprocess.run(
                ["taskkill", "/PID", str(process.pid), "/T", "/F"],
                capture_output=True,
                check=False,
            )
        else:
            process.kill()

    def start(self):
        if self.thread and self.thread.is_alive():
            return
        self.stop_event.clear()
        self.thread = threading.Thread(target=self.loop, daemon=True, name="StreamSniperMonitor")
        self.thread.start()
        self.say("Monitoring started.")

    def stop(self):
        if self.thread and self.thread.is_alive():
            self.stop_event.set()
            self.say("Stopping monitor. Active recordings may finish first.")

    def loop(self):
        self.notify("🟢 **StreamSniper is online.** Monitoring enabled channels.")
        while not self.stop_event.is_set():
            for url, label, auto_record in self.channels():
                if self.stop_event.is_set():
                    break
                try:
                    self.check_uploads(url, label)
                    live = self.check_live(url)
                    if live:
                        video_id, title, link = live
                        with self.lock:
                            newly_live = video_id not in self.live_streams
                        self._set_live_stream(url, label, video_id, title, link)
                        if newly_live:
                            self.say(f"LIVE: {label} — {title}")
                            self.notify(f"🔴 **LIVE: {label}**\n**{title}**\n{link}")
                        if auto_record:
                            self.start_recording(video_id, title, link, label)
                    else:
                        self._clear_live_streams_for_channel(url)
                except Exception as exc:
                    self.say(f"Check failed for {label}: {exc}")
                    logging.exception("Channel check failed")
            self.stop_event.wait(POLL_SECONDS)
        self.say("Monitoring stopped.")

    def check_uploads(self, url, label):
        channel_id = self.resolve_channel(url)
        if not channel_id:
            return
        feed = feedparser.parse(
            f"https://www.youtube.com/feeds/videos.xml?channel_id={quote(channel_id)}"
        )
        for entry in feed.entries:
            video_id = entry.get("yt_videoid") or entry.get("id", "").split(":")[-1]
            title = entry.get("title", "New upload")
            if video_id and mark_seen(video_id, url, title, "upload"):
                link = f"https://www.youtube.com/watch?v={video_id}"
                self.say(f"NEW UPLOAD: {label} — {title}")
                self.notify(f"📹 **New upload: {label}**\n**{title}**\n{link}")

    def check_live(self, url):
        target = url.rstrip("/") + "/live"
        try:
            result = self.run_ytdlp(
                "--skip-download", "--no-warnings", "--dump-single-json", target,
                timeout=55,
            )
            if result.returncode != 0 or not result.stdout.strip():
                return None
            data = json.loads(result.stdout.splitlines()[-1])
            if data.get("is_live") or data.get("live_status") == "is_live":
                return (
                    data.get("id"), data.get("title") or "Live stream",
                    data.get("webpage_url") or target,
                )
        except subprocess.TimeoutExpired:
            self.say(f"Live check timed out: {url}")
        return None

    def record(self, video_id, title, link, label, duration_seconds=None):
        try:
            channel_folder = DATA_DIR / self.safe_name(label)
            folder = channel_folder / f"{self.safe_name(title)[:70]}_{video_id}"
            folder.mkdir(parents=True, exist_ok=True)
            with self.lock:
                recording = self.active_recordings.get(video_id)
                if recording is None:
                    self.recording.add(video_id)
                    recording = {
                        "video_id": video_id,
                        "title": title,
                        "link": link,
                        "channel": label,
                        "duration_seconds": duration_seconds,
                        "started_at": time.time(),
                        "stop_requested": False,
                        "stop_reason": None,
                        "process": None,
                    }
                    self.active_recordings[video_id] = recording
                recording["output_folder"] = str(folder)
            output_template = str(folder / "%(title).100B_%(id)s.%(ext)s")
            self.say(f"Recording started: {title}")
            self.notify(f"⏺️ **Recording started: {label}**\n{title}")
            command = yt_dlp_command(
                "--newline", "--retries", "10",
                "--fragment-retries", "10", "--retry-sleep", "5", "--write-info-json",
                "--write-thumbnail", "-o", output_template, link,
            )
            process_options = {}
            if os.name == "nt":
                process_options["creationflags"] = getattr(
                    subprocess, "CREATE_NEW_PROCESS_GROUP", 0
                )
            process = subprocess.Popen(command, **process_options)
            with self.lock:
                recording["process"] = process

            if recording["stop_requested"]:
                self._request_process_stop(process)
            stop_signal_sent_at = time.monotonic() if recording["stop_requested"] else None
            force_stop_sent = False
            duration_deadline = (
                time.monotonic() + duration_seconds if duration_seconds else None
            )
            partial_announced = False
            while process.poll() is None:
                if not partial_announced and list(folder.glob(f"*{video_id}*.part")):
                    self.say(f"Recording file active: {label} — {title}")
                    partial_announced = True
                with self.lock:
                    stop_requested = recording["stop_requested"]
                if duration_deadline and time.monotonic() >= duration_deadline:
                    with self.lock:
                        recording["stop_requested"] = True
                        recording["stop_reason"] = "duration"
                    stop_requested = True
                if stop_requested and stop_signal_sent_at is None:
                    self._request_process_stop(process)
                    stop_signal_sent_at = time.monotonic()
                elif (
                    stop_signal_sent_at
                    and not force_stop_sent
                    and time.monotonic() - stop_signal_sent_at > 10
                ):
                    self._force_stop_process_tree(process)
                    force_stop_sent = True
                time.sleep(0.5)

            stopped_by_user = recording["stop_requested"]
            if process.returncode == 0 or stopped_by_user:
                write_stream_metadata(folder, video_id, title)
                saved = find_recording_file(folder, video_id, VIDEO_EXTENSIONS)
                if saved:
                    status = "Recording section saved" if stopped_by_user else "Recording complete"
                    self.say(f"{status}: {saved}")
                    self.notify(f"✅ **Recording complete: {label}**\n{title}\nLocal: `{saved.name}`")
                else:
                    partials = list(folder.glob(f"*{video_id}*.part"))
                    if partials:
                        try:
                            saved = recover_partial_recording(partials[0])
                            self.say(f"Recording section saved: {saved}")
                            self.notify(f"✅ **Recording section saved: {label}**\n{title}\nLocal: `{saved.name}`")
                        except Exception as exc:
                            logging.exception("Partial stream recovery failed")
                            self.say(f"Recording stopped, but could not finalize its partial file: {exc}")
                    elif stopped_by_user:
                        self.say("Recording stopped before a playable video was finalized.")
            else:
                self.say(f"Recording ended with yt-dlp exit code {process.returncode}: {title}")
                self.notify(f"⚠️ Recording issue: **{label}** — {title} (exit {process.returncode})")
        except Exception as exc:
            self.say(f"Recording failed: {title} — {exc}")
            logging.exception("Recording failed")
            self.notify(f"❌ **Recording failed: {label}**\n{title}\n{exc}")
        finally:
            with self.lock:
                self.recording.discard(video_id)
                self.active_recordings.pop(video_id, None)
