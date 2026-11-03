"""StreamSniper PySide6 desktop interface."""
from __future__ import annotations

import logging
import os
import queue
import json
import subprocess
import threading
import time
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import Qt, QTimer, Signal, QObject, QPropertyAnimation, QEasingCurve, QSize, QSettings
from dotenv import set_key
from PySide6.QtGui import QColor, QIcon, QPixmap
from PySide6.QtWidgets import QGraphicsOpacityEffect
from PySide6.QtWidgets import (
    QAbstractItemView, QApplication, QFileDialog, QFrame, QHBoxLayout,
    QDialog, QDialogButtonBox, QHeaderView, QLabel, QLineEdit, QMainWindow,
    QMessageBox, QPushButton,
    QListWidget, QListWidgetItem, QSplitter, QStackedWidget,
    QTableWidget, QTableWidgetItem, QTextEdit, QVBoxLayout, QWidget, QProgressBar,
    QInputDialog, QComboBox, QCheckBox, QGridLayout,
)

from config import (
    APP_ICON_PATH, CONFIG_PATH, DATA_DIR, DISCORD_WEBHOOK, LOG_PATH, POLL_SECONDS,
    VIDEO_EXTENSIONS,
)
from database import (
    add_channel, dashboard_counts, list_channels, remove_channel,
    set_channel_auto_record, toggle_channel,
)
from monitor import Monitor, yt_dlp_command
from recording_utils import recover_partial_recording
from ui.theme import log_badge_colors, theme_colors
from upload_service import (
    build_prefixed_title, connect_youtube, disconnect_youtube, has_youtube_connection,
    upload_to_youtube,
)


class EventBus(QObject):
    message = Signal(str)
    recovery_finished = Signal(str, str)
    upload_progress = Signal(int, str)
    upload_finished = Signal(bool, str)
    youtube_auth_finished = Signal(bool, str)


class StatCard(QFrame):
    def __init__(self, label: str, value: str = "—"):
        super().__init__()
        self.setObjectName("card")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(17, 15, 17, 15)
        layout.setSpacing(7)
        caption = QLabel(label.upper())
        caption.setObjectName("cardLabel")
        self.value = QLabel(value)
        self.value.setObjectName("cardValue")
        layout.addWidget(caption)
        layout.addWidget(self.value)


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("StreamSniper")
        self.setWindowIcon(QIcon(str(APP_ICON_PATH)))
        self.resize(1280, 820)
        self.setMinimumSize(1020, 680)
        self.bus = EventBus()
        self.bus.message.connect(self.add_log)
        self.bus.recovery_finished.connect(self.finish_partial_recovery)
        self.bus.upload_progress.connect(self.update_upload_progress)
        self.bus.upload_finished.connect(self.finish_upload)
        self.bus.youtube_auth_finished.connect(self.finish_youtube_connection)
        self.monitor = Monitor(self.bus.message.emit)
        self.upload_settings = QSettings("StreamSniper", "StreamSniper")
        self.upload_thread = None
        self.youtube_auth_thread = None
        self._native_icon_handles = []
        self.log_rows: list[tuple[str, str, str]] = []
        self._build_shell()
        self._build_pages()
        self._connect_signals()
        self.refresh_all()
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.refresh_all)
        self.timer.start(3000)
        self.log_timer = QTimer(self)
        self.log_timer.timeout.connect(self.load_existing_log_once)
        self.log_timer.setSingleShot(True)
        self.log_timer.start(250)
        self.check_dependencies()

    # ------------------------------------------------------------------
    # Main layout and navigation
    # ------------------------------------------------------------------
    def _build_shell(self):
        root = QWidget()
        root.setObjectName("root")
        self.setCentralWidget(root)
        outer = QHBoxLayout(root)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        self.sidebar = QFrame()
        self.sidebar.setObjectName("sidebar")
        self.sidebar.setFixedWidth(226)
        side = QVBoxLayout(self.sidebar)
        side.setContentsMargins(16, 24, 16, 18)
        side.setSpacing(8)

        brand = QLabel("STREAMSNIPER")
        brand.setObjectName("brand")
        brand_sub = QLabel("YOUTUBE STREAM MONITOR")
        brand_sub.setObjectName("brandAccent")
        side.addWidget(brand)
        side.addWidget(brand_sub)
        side.addSpacing(28)

        self.nav_buttons = {}
        for key, label in [
            ("dashboard", "◫   Overview"),
            ("channels", "◎   Channels"),
            ("recordings", "▣   Recorded streams"),
            ("activity", "≋   Activity logs"),
            ("settings", "⚙   Settings"),
            ("upload", "↑   Upload"),
        ]:
            button = QPushButton(label)
            button.setObjectName("navButton")
            button.setProperty("active", key == "dashboard")
            button.setCursor(Qt.PointingHandCursor)
            button.clicked.connect(lambda checked=False, page=key: self.show_page(page))
            side.addWidget(button)
            self.nav_buttons[key] = button

        side.addStretch(1)
        self.sidebar_status = QLabel("●  STOPPED")
        self.sidebar_status.setObjectName("sidebarStatus")
        self.sidebar_status.setProperty("state", "stopped")
        side.addWidget(self.sidebar_status)
        version = QLabel("StreamSniper")
        version.setObjectName("versionLabel")
        side.addWidget(version)
        outer.addWidget(self.sidebar)

        content = QWidget()
        self.content_layout = QVBoxLayout(content)
        self.content_layout.setContentsMargins(28, 24, 28, 24)
        self.content_layout.setSpacing(18)
        self.page_stack = QStackedWidget()
        self.content_layout.addWidget(self.page_stack)
        beta_note = QLabel(
            "This app is purely made with the help of AI by @wSirski (Youtube)"
            "just purely vibecoded. (BETA VERSION btw 🥀)"
        )
        beta_note.setObjectName("betaNote")
        beta_note.setAlignment(Qt.AlignRight)
        beta_note.setWordWrap(True)
        self.content_layout.addWidget(beta_note)
        outer.addWidget(content, 1)

    def _page_header(self, title: str, subtitle: str):
        wrapper = QWidget()
        layout = QVBoxLayout(wrapper)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(5)
        title_label = QLabel(title)
        title_label.setObjectName("pageTitle")
        subtitle_label = QLabel(subtitle)
        subtitle_label.setObjectName("muted")
        layout.addWidget(title_label)
        layout.addWidget(subtitle_label)
        return wrapper

    def _build_pages(self):
        # Overview page
        self.dashboard_page = QWidget()
        dash = QVBoxLayout(self.dashboard_page)
        dash.setContentsMargins(0, 0, 0, 0)
        dash.setSpacing(18)
        dash.addWidget(self._page_header("Good to see you.", "Your YouTube monitoring activity at a glance."))

        stats = QGridLayout()
        stats.setSpacing(12)
        self.cards = {
            "channels": StatCard("Total channels"),
            "enabled": StatCard("Monitoring enabled"),
            "uploads": StatCard("Uploads detected"),
            "recordings": StatCard("Saved recordings"),
        }
        for index, card in enumerate(self.cards.values()):
            stats.addWidget(card, 0, index)
            stats.setColumnStretch(index, 1)
        dash.addLayout(stats)

        status_panel = QFrame()
        status_panel.setObjectName("panel")
        status_layout = QHBoxLayout(status_panel)
        status_layout.setContentsMargins(18, 15, 18, 15)
        status_copy = QVBoxLayout()
        self.monitor_status = QLabel("Monitor stopped")
        self.monitor_status.setObjectName("monitorStatus")
        self.monitor_status.setProperty("state", "stopped")
        self.monitor_detail = QLabel(f"Checks enabled channels every {POLL_SECONDS} seconds")
        self.monitor_detail.setObjectName("muted")
        status_copy.addWidget(self.monitor_status)
        status_copy.addWidget(self.monitor_detail)
        status_layout.addLayout(status_copy)
        status_layout.addStretch(1)
        self.active_label = QLabel("0 active recordings")
        self.active_label.setObjectName("activeRecordings")
        status_layout.addWidget(self.active_label)
        self.start_button = QPushButton("▶  Start monitoring")
        self.start_button.setObjectName("primary")
        self.stop_button = QPushButton("■  Stop")
        self.stop_button.setObjectName("danger")
        status_layout.addWidget(self.start_button)
        status_layout.addWidget(self.stop_button)
        dash.addWidget(status_panel)

        quick = QHBoxLayout()
        quick_title = QLabel("Recent activity")
        quick_title.setObjectName("sectionTitle")
        quick.addWidget(quick_title)
        quick.addStretch(1)
        view_all = QPushButton("View all logs  →")
        view_all.clicked.connect(lambda: self.show_page("activity"))
        quick.addWidget(view_all)
        dash.addLayout(quick)
        self.recent_table = self._make_log_table()
        self.recent_table.setMaximumHeight(255)
        dash.addWidget(self.recent_table, 1)
        self.page_stack.addWidget(self.dashboard_page)

        # Channels page
        self.channels_page = QWidget()
        channels_layout = QVBoxLayout(self.channels_page)
        channels_layout.setContentsMargins(0, 0, 0, 0)
        channels_layout.setSpacing(16)
        channels_layout.addWidget(self._page_header("Channels", "Manage the YouTube channels StreamSniper watches."))
        toolbar = QHBoxLayout()
        self.channel_search = QLineEdit()
        self.channel_search.setPlaceholderText("Search channels or URLs…")
        self.channel_search.setMaximumWidth(340)
        toolbar.addWidget(self.channel_search)
        toolbar.addStretch(1)
        self.add_channel_button = QPushButton("＋  Add channel")
        self.add_channel_button.setObjectName("primary")
        self.toggle_channel_button = QPushButton("Enable / pause")
        self.remove_channel_button = QPushButton("Remove")
        self.remove_channel_button.setObjectName("danger")
        toolbar.addWidget(self.toggle_channel_button)
        toolbar.addWidget(self.remove_channel_button)
        toolbar.addWidget(self.add_channel_button)
        channels_layout.addLayout(toolbar)
        self.channel_table = QTableWidget(0, 4)
        self.channel_table.setHorizontalHeaderLabels(["CHANNEL", "YOUTUBE URL", "STATUS", "AUTO RECORD"])
        self.channel_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.channel_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.channel_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeToContents)
        self.channel_table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeToContents)
        self.channel_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.channel_table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.channel_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.channel_table.setAlternatingRowColors(True)
        channels_layout.addWidget(self.channel_table, 1)
        self.page_stack.addWidget(self.channels_page)

        # Recorded streams library and player
        self.recordings_page = QWidget()
        rec_layout = QVBoxLayout(self.recordings_page)
        rec_layout.setContentsMargins(0, 0, 0, 0)
        rec_layout.setSpacing(16)
        rec_layout.addWidget(self._page_header("Recorded streams", "Your saved streams, ready to watch."))
        rec_toolbar = QHBoxLayout()
        self.recording_search = QLineEdit()
        self.recording_search.setPlaceholderText("Search streams or channels…")
        rec_toolbar.addWidget(self.recording_search)
        self.refresh_recordings_button = QPushButton("Refresh library")
        rec_toolbar.addWidget(self.refresh_recordings_button)
        self.open_folder_button = QPushButton("Open recordings folder ↗")
        rec_toolbar.addWidget(self.open_folder_button)
        rec_layout.addLayout(rec_toolbar)

        live_controls = QVBoxLayout()
        live_row = QHBoxLayout()
        live_label = QLabel("LIVE NOW")
        live_label.setObjectName("cardLabel")
        self.live_stream_selector = QComboBox()
        self.live_stream_selector.setMinimumWidth(260)
        self.live_stream_selector.setPlaceholderText("No live streams detected")
        self.record_full_stream_button = QPushButton("Record until offline")
        self.record_full_stream_button.setObjectName("primary")
        self.record_section_button = QPushButton("Record a section…")
        live_row.addWidget(live_label)
        live_row.addWidget(self.live_stream_selector, 1)
        live_row.addWidget(self.record_full_stream_button)
        live_row.addWidget(self.record_section_button)
        live_controls.addLayout(live_row)

        active_row = QHBoxLayout()
        active_label = QLabel("RECORDING")
        active_label.setObjectName("cardLabel")
        self.active_recording_selector = QComboBox()
        self.active_recording_selector.setMinimumWidth(260)
        self.active_recording_selector.setPlaceholderText("Nothing is recording")
        self.stop_recording_button = QPushButton("Stop selected")
        self.stop_recording_button.setObjectName("danger")
        self.stop_recording_button.setEnabled(False)
        active_row.addWidget(active_label)
        active_row.addWidget(self.active_recording_selector, 1)
        active_row.addWidget(self.stop_recording_button)
        live_controls.addLayout(active_row)
        recording_note = QLabel("Manual recording starts at detection time; earlier live footage is not recovered.")
        recording_note.setObjectName("muted")
        live_controls.addWidget(recording_note)
        rec_layout.addLayout(live_controls)

        recording_splitter = QSplitter(Qt.Horizontal)
        self.recording_list = QListWidget()
        self.recording_list.setObjectName("recordingList")
        self.recording_list.setIconSize(QSize(112, 63))
        self.recording_list.setMinimumWidth(220)
        self.recording_list.setSpacing(3)
        recording_splitter.addWidget(self.recording_list)
        self.selected_recording_path = None

        details_panel = QWidget()
        details_layout = QVBoxLayout(details_panel)
        details_layout.setContentsMargins(14, 8, 4, 4)
        details_layout.setSpacing(10)
        thumbnail_frame = QFrame()
        thumbnail_frame.setObjectName("recordingPreview")
        thumbnail_frame.setMinimumHeight(210)
        thumbnail_layout = QVBoxLayout(thumbnail_frame)
        thumbnail_layout.setContentsMargins(0, 0, 0, 0)
        self.recording_thumbnail = QLabel("Select a saved stream to view its thumbnail")
        self.recording_thumbnail.setObjectName("recordingThumbnail")
        self.recording_thumbnail.setAlignment(Qt.AlignCenter)
        self.recording_thumbnail.setMinimumHeight(200)
        thumbnail_layout.addWidget(self.recording_thumbnail)
        details_layout.addWidget(thumbnail_frame, 2)

        stream_info = QVBoxLayout()
        self.recording_title = QLabel("No stream selected")
        self.recording_title.setObjectName("recordingTitle")
        self.recording_title.setWordWrap(True)
        self.recording_channel = QLabel("Choose a stream from your library")
        self.recording_channel.setObjectName("muted")
        self.recording_description = QTextEdit()
        self.recording_description.setReadOnly(True)
        self.recording_description.setPlaceholderText("Stream description")
        self.recording_description.setMinimumHeight(85)
        self.recording_description.setMaximumHeight(135)
        stream_info.addWidget(self.recording_title)
        stream_info.addWidget(self.recording_channel)
        stream_info.addWidget(self.recording_description)
        details_layout.addLayout(stream_info, 1)

        recording_actions = QHBoxLayout()
        self.recording_status = QLabel("")
        self.recording_status.setObjectName("muted")
        recording_actions.addWidget(self.recording_status, 1)
        self.recover_partial_button = QPushButton("Recover partial")
        self.recover_partial_button.setEnabled(False)
        recording_actions.addWidget(self.recover_partial_button)
        self.open_external_button = QPushButton("Open in external player")
        self.open_external_button.setEnabled(False)
        recording_actions.addWidget(self.open_external_button)
        details_layout.addLayout(recording_actions)
        recording_splitter.addWidget(details_panel)
        recording_splitter.setStretchFactor(0, 1)
        recording_splitter.setStretchFactor(1, 2)
        rec_layout.addWidget(recording_splitter, 1)
        self.page_stack.addWidget(self.recordings_page)

        # Activity logs page
        self.activity_page = QWidget()
        activity_layout = QVBoxLayout(self.activity_page)
        activity_layout.setContentsMargins(0, 0, 0, 0)
        activity_layout.setSpacing(14)
        activity_layout.addWidget(self._page_header("Activity centre", "A readable timeline of detections, recordings and issues."))
        filters = QHBoxLayout()
        self.log_search = QLineEdit()
        self.log_search.setPlaceholderText("Search activity…")
        filters.addWidget(self.log_search, 1)
        self.log_level = QComboBox()
        self.log_level.addItems(["All events", "Debug", "Info", "Success", "Warning", "Error", "Live"])
        self.log_level.setMinimumWidth(145)
        filters.addWidget(self.log_level)
        self.auto_scroll = QCheckBox("Auto-scroll")
        self.auto_scroll.setChecked(True)
        filters.addWidget(self.auto_scroll)
        export_button = QPushButton("Export visible")
        export_button.clicked.connect(self.export_logs)
        filters.addWidget(export_button)
        open_log_button = QPushButton("Open log file ↗")
        open_log_button.clicked.connect(self.open_log_file)
        filters.addWidget(open_log_button)
        activity_layout.addLayout(filters)
        self.activity_table = self._make_log_table()
        activity_layout.addWidget(self.activity_table, 1)
        self.page_stack.addWidget(self.activity_page)

        # Settings page — values are saved to this Windows user's app data.
        self.settings_page = QWidget()
        settings_layout = QVBoxLayout(self.settings_page)
        settings_layout.setContentsMargins(0, 0, 0, 0)
        settings_layout.setSpacing(16)
        settings_layout.addWidget(self._page_header("Settings", "Local configuration. Changes apply after restarting the app."))
        settings_panel = QFrame()
        settings_panel.setObjectName("panel")
        form = QVBoxLayout(settings_panel)
        form.setContentsMargins(20, 20, 20, 20)
        form.setSpacing(9)
        webhook_label = QLabel("DISCORD WEBHOOK URL")
        webhook_label.setObjectName("cardLabel")
        self.webhook_input = QLineEdit(DISCORD_WEBHOOK)
        self.webhook_input.setEchoMode(QLineEdit.Password)
        self.webhook_input.setPlaceholderText("Paste your Discord webhook URL")
        self.webhook_input.setToolTip("Stored only in this Windows user's app data")
        folder_label = QLabel("LOCAL RECORDING FOLDER")
        folder_label.setObjectName("cardLabel")
        folder_row = QHBoxLayout()
        self.data_dir_input = QLineEdit(str(DATA_DIR))
        browse_folder = QPushButton("Browse…")
        browse_folder.clicked.connect(self.browse_data_folder)
        folder_row.addWidget(self.data_dir_input, 1)
        folder_row.addWidget(browse_folder)
        note = QLabel(
            "Your Discord webhook and recording folder are saved privately on this PC. "
            "Restart StreamSniper after saving."
        )
        note.setObjectName("muted")
        note.setWordWrap(True)
        self.save_settings_button = QPushButton("Save local settings")
        self.save_settings_button.setObjectName("primary")
        self.save_settings_button.clicked.connect(self.save_settings)
        form.addWidget(webhook_label)
        form.addWidget(self.webhook_input)
        form.addSpacing(8)
        form.addWidget(folder_label)
        form.addLayout(folder_row)
        form.addSpacing(8)
        form.addWidget(note)
        form.addWidget(self.save_settings_button, 0, Qt.AlignLeft)
        settings_layout.addWidget(settings_panel)
        settings_layout.addStretch(1)
        self.page_stack.addWidget(self.settings_page)

        self._build_upload_page()

    def _build_upload_page(self):
        self.upload_page = QWidget()
        page_layout = QVBoxLayout(self.upload_page)
        page_layout.setContentsMargins(0, 0, 0, 0)
        page_layout.setSpacing(16)
        page_layout.addWidget(self._page_header(
            "Upload",
            "Publish a saved recording to YouTube.",
        ))

        panel = QFrame()
        panel.setObjectName("panel")
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(12)

        recording_label = QLabel("COMPLETED RECORDING")
        recording_label.setObjectName("cardLabel")
        recording_row = QHBoxLayout()
        self.upload_recording_combo = QComboBox()
        self.upload_recording_combo.setMinimumHeight(40)
        self.upload_recording_refresh_button = QPushButton("Refresh list")
        recording_row.addWidget(self.upload_recording_combo, 1)
        recording_row.addWidget(self.upload_recording_refresh_button)
        layout.addWidget(recording_label)
        layout.addLayout(recording_row)

        preview_row = QHBoxLayout()
        self.upload_thumbnail_label = QLabel("Select a completed recording")
        self.upload_thumbnail_label.setObjectName("recordingThumbnail")
        self.upload_thumbnail_label.setAlignment(Qt.AlignCenter)
        self.upload_thumbnail_label.setFixedSize(320, 180)
        preview_row.addWidget(self.upload_thumbnail_label, 0, Qt.AlignTop)
        preview_details = QVBoxLayout()
        self.upload_title_label = QLabel("No recording selected")
        self.upload_title_label.setObjectName("recordingTitle")
        self.upload_title_label.setWordWrap(True)
        self.upload_channel_label = QLabel("")
        self.upload_channel_label.setObjectName("muted")
        self.upload_description_view = QTextEdit()
        self.upload_description_view.setReadOnly(True)
        self.upload_description_view.setPlaceholderText("Saved description")
        self.upload_description_view.setMinimumHeight(110)
        self.upload_description_view.setMaximumHeight(150)
        preview_details.addWidget(self.upload_title_label)
        preview_details.addWidget(self.upload_channel_label)
        preview_details.addWidget(self.upload_description_view, 1)
        preview_row.addLayout(preview_details, 1)
        layout.addLayout(preview_row)

        self.youtube_upload_controls = QWidget()
        youtube_layout = QVBoxLayout(self.youtube_upload_controls)
        youtube_layout.setContentsMargins(0, 0, 0, 0)
        youtube_layout.setSpacing(8)
        client_label = QLabel("GOOGLE DESKTOP OAUTH CLIENT JSON")
        client_label.setObjectName("cardLabel")
        client_row = QHBoxLayout()
        self.youtube_client_file_input = QLineEdit(
            self.upload_settings.value("youtube/client_file", "", type=str)
        )
        self.youtube_client_file_input.setPlaceholderText("Choose the Desktop OAuth client JSON from Google Cloud")
        self.browse_youtube_client_button = QPushButton("Browse…")
        self.connect_youtube_button = QPushButton("Connect YouTube")
        self.disconnect_youtube_button = QPushButton("Disconnect")
        client_row.addWidget(self.youtube_client_file_input, 1)
        client_row.addWidget(self.browse_youtube_client_button)
        client_row.addWidget(self.connect_youtube_button)
        client_row.addWidget(self.disconnect_youtube_button)
        youtube_layout.addWidget(client_label)
        youtube_layout.addLayout(client_row)

        visibility_row = QHBoxLayout()
        visibility_label = QLabel("VISIBILITY")
        visibility_label.setObjectName("cardLabel")
        self.youtube_visibility_combo = QComboBox()
        self.youtube_visibility_combo.addItem("Private", "private")
        self.youtube_visibility_combo.addItem("Unlisted", "unlisted")
        self.youtube_visibility_combo.addItem("Public", "public")
        self.youtube_status_label = QLabel("YouTube account not connected")
        self.youtube_status_label.setObjectName("muted")
        visibility_row.addWidget(visibility_label)
        visibility_row.addWidget(self.youtube_visibility_combo)
        visibility_row.addWidget(self.youtube_status_label, 1)
        youtube_layout.addLayout(visibility_row)
        layout.addWidget(self.youtube_upload_controls)

        action_row = QHBoxLayout()
        self.upload_button = QPushButton("Upload selected recording")
        self.upload_button.setObjectName("primary")
        self.upload_progress = QProgressBar()
        self.upload_progress.setRange(0, 100)
        self.upload_progress.setValue(0)
        self.upload_progress.setMinimumWidth(210)
        self.upload_status_label = QLabel("A prefix will be requested when you upload.")
        self.upload_status_label.setObjectName("muted")
        self.upload_status_label.setWordWrap(True)
        action_row.addWidget(self.upload_button)
        action_row.addWidget(self.upload_progress)
        action_row.addWidget(self.upload_status_label, 1)
        layout.addLayout(action_row)

        page_layout.addWidget(panel)
        page_layout.addStretch(1)
        self.page_stack.addWidget(self.upload_page)

    def _make_log_table(self):
        table = QTableWidget(0, 3)
        table.setObjectName("logTable")
        table.setHorizontalHeaderLabels(["TIME", "TYPE", "EVENT"])
        table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        table.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)
        table.setSelectionBehavior(QAbstractItemView.SelectRows)
        table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        table.setAlternatingRowColors(True)
        table.verticalHeader().setVisible(False)
        table.verticalHeader().setMinimumSectionSize(36)
        table.horizontalHeader().setMinimumSectionSize(88)
        table.setWordWrap(True)
        return table

    def _connect_signals(self):
        self.start_button.clicked.connect(self.monitor.start)
        self.stop_button.clicked.connect(self.monitor.stop)
        self.add_channel_button.clicked.connect(self.add_channel_dialog)
        self.remove_channel_button.clicked.connect(self.remove_selected_channel)
        self.toggle_channel_button.clicked.connect(self.toggle_selected_channel)
        self.open_folder_button.clicked.connect(self.open_recordings_folder)
        self.refresh_recordings_button.clicked.connect(self.refresh_recordings)
        self.record_full_stream_button.clicked.connect(self.record_selected_live_stream)
        self.record_section_button.clicked.connect(self.record_selected_live_section)
        self.stop_recording_button.clicked.connect(self.stop_selected_recording)
        self.channel_table.itemChanged.connect(self.update_channel_auto_record)
        self.recording_list.currentItemChanged.connect(self.select_recording)
        self.recording_list.itemDoubleClicked.connect(
            lambda _item: self.open_recording_externally()
        )
        self.open_external_button.clicked.connect(self.open_recording_externally)
        self.recover_partial_button.clicked.connect(self.recover_selected_partial)
        self.upload_recording_combo.currentIndexChanged.connect(
            self.update_upload_recording_preview
        )
        self.upload_recording_refresh_button.clicked.connect(self.refresh_upload_recordings)
        self.youtube_client_file_input.editingFinished.connect(
            self.save_youtube_client_file
        )
        self.browse_youtube_client_button.clicked.connect(
            self.browse_youtube_client_file
        )
        self.connect_youtube_button.clicked.connect(self.connect_youtube_account)
        self.disconnect_youtube_button.clicked.connect(self.disconnect_youtube_account)
        self.upload_button.clicked.connect(self.start_upload)
        self.channel_search.textChanged.connect(self.filter_channels)
        self.recording_search.textChanged.connect(self.filter_recordings)
        self.log_search.textChanged.connect(self.render_logs)
        self.log_level.currentTextChanged.connect(self.render_logs)
        self.activity_table.cellDoubleClicked.connect(
            lambda row, column: self.show_log_details(self.activity_table, row, column)
        )
        self.recent_table.cellDoubleClicked.connect(
            lambda row, column: self.show_log_details(self.recent_table, row, column)
        )

    def refresh_upload_recordings(self):
        selected_path = self.upload_recording_combo.currentData()
        self.upload_recording_combo.blockSignals(True)
        self.upload_recording_combo.clear()
        selected_index = -1
        for path in self.recording_files():
            if path.suffix.lower() == ".part" or self.is_recording_active_file(path):
                continue
            title, _ = self.recording_metadata(path)
            channel = self.recording_channel_name(path)
            self.upload_recording_combo.addItem(
                f"{title} · {channel} · {self.format_size(path.stat().st_size)}",
                str(path),
            )
            if str(path) == selected_path:
                selected_index = self.upload_recording_combo.count() - 1
        if self.upload_recording_combo.count():
            self.upload_recording_combo.setCurrentIndex(
                selected_index if selected_index >= 0 else 0
            )
        self.upload_recording_combo.blockSignals(False)
        self.update_upload_recording_preview()

    def update_upload_recording_preview(self, *_):
        path_text = self.upload_recording_combo.currentData()
        if not path_text:
            self.upload_title_label.setText("No completed recording selected")
            self.upload_channel_label.setText("")
            self.upload_description_view.clear()
            self.upload_thumbnail_label.setPixmap(QPixmap())
            self.upload_thumbnail_label.setText("No completed recordings available")
            return

        path = Path(path_text)
        title, description = self.recording_metadata(path)
        self.upload_title_label.setText(title)
        self.upload_channel_label.setText(
            f"{self.recording_channel_name(path)} · {path.name} · "
            f"{self.format_size(path.stat().st_size)}"
        )
        self.upload_description_view.setPlainText(
            description or "No saved description for this recording."
        )
        thumbnail = self.recording_thumbnail(path)
        pixmap = QPixmap(str(thumbnail)) if thumbnail else QPixmap()
        if pixmap.isNull():
            self.upload_thumbnail_label.setPixmap(QPixmap())
            self.upload_thumbnail_label.setText("No saved thumbnail")
        else:
            self.upload_thumbnail_label.setText("")
            self.upload_thumbnail_label.setPixmap(
                pixmap.scaled(QSize(320, 180), Qt.KeepAspectRatio, Qt.SmoothTransformation)
            )

    def save_youtube_client_file(self):
        client_file = self.youtube_client_file_input.text().strip()
        self.upload_settings.setValue("youtube/client_file", client_file)
        self.refresh_youtube_connection_status()

    def browse_youtube_client_file(self):
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Select Google Desktop OAuth client",
            str(Path.home()),
            "JSON files (*.json)",
        )
        if path:
            self.youtube_client_file_input.setText(path)
            self.save_youtube_client_file()

    def refresh_youtube_connection_status(self):
        client_text = self.youtube_client_file_input.text().strip()
        client_file = Path(client_text).expanduser() if client_text else None
        if not client_file or not client_file.is_file():
            self.youtube_status_label.setText("Choose a Google Desktop OAuth client file")
            self.connect_youtube_button.setEnabled(False)
            self.disconnect_youtube_button.setEnabled(False)
            return False
        try:
            connected = has_youtube_connection(client_file)
        except Exception as exc:
            self.youtube_status_label.setText(f"Credential store unavailable: {exc}")
            self.connect_youtube_button.setEnabled(True)
            self.disconnect_youtube_button.setEnabled(False)
            return False
        self.youtube_status_label.setText(
            "YouTube account connected" if connected else "YouTube account not connected"
        )
        self.connect_youtube_button.setEnabled(not connected)
        self.disconnect_youtube_button.setEnabled(connected)
        return connected

    def connect_youtube_account(self):
        client_file = Path(self.youtube_client_file_input.text().strip()).expanduser()
        if not client_file.is_file():
            self.youtube_status_label.setText("Choose a valid OAuth client JSON file first")
            return
        if self.youtube_auth_thread and self.youtube_auth_thread.is_alive():
            return

        self.connect_youtube_button.setEnabled(False)
        self.youtube_status_label.setText("Waiting for Google sign-in in your browser…")

        def authenticate():
            try:
                channel_name = connect_youtube(client_file)
            except Exception as exc:
                self.bus.youtube_auth_finished.emit(False, str(exc))
            else:
                self.bus.youtube_auth_finished.emit(True, channel_name)

        self.youtube_auth_thread = threading.Thread(
            target=authenticate,
            daemon=True,
            name="StreamSniperYouTubeAuth",
        )
        self.youtube_auth_thread.start()

    def finish_youtube_connection(self, success: bool, result: str):
        if success:
            self.youtube_status_label.setText(f"Connected: {result}")
            self.connect_youtube_button.setEnabled(False)
            self.disconnect_youtube_button.setEnabled(True)
            self.add_log(f"Connected YouTube account: {result}")
        else:
            self.youtube_status_label.setText(f"YouTube sign-in failed: {result}")
            self.refresh_youtube_connection_status()

    def disconnect_youtube_account(self):
        client_text = self.youtube_client_file_input.text().strip()
        if not client_text:
            return
        try:
            disconnect_youtube(Path(client_text).expanduser())
        except Exception as exc:
            self.youtube_status_label.setText(f"Could not disconnect YouTube: {exc}")
            return
        self.refresh_youtube_connection_status()

    def start_upload(self):
        if self.upload_thread and self.upload_thread.is_alive():
            return
        path_text = self.upload_recording_combo.currentData()
        if not path_text:
            self.upload_status_label.setText("Choose a completed recording first.")
            return
        media_path = Path(path_text)
        if not media_path.is_file() or media_path.suffix.lower() == ".part":
            self.upload_status_label.setText("Only completed recording files can be uploaded.")
            return

        title, description = self.recording_metadata(media_path)
        prefix, accepted = QInputDialog.getText(
            self,
            "Upload title prefix",
            f"Prefix to add before ‘{title}’ (leave blank for no prefix):",
        )
        if not accepted:
            return

        visibility = self.youtube_visibility_combo.currentData()
        client_file = Path(self.youtube_client_file_input.text().strip()).expanduser()
        try:
            title = build_prefixed_title(title, prefix)
        except ValueError as exc:
            self.upload_status_label.setText(str(exc))
            return
        if not client_file.is_file() or not self.refresh_youtube_connection_status():
            self.upload_status_label.setText("Connect a YouTube account before uploading.")
            return

        thumbnail_path = self.recording_thumbnail(media_path)
        self.upload_button.setEnabled(False)
        self.upload_progress.setValue(0)
        self.upload_status_label.setText("Preparing upload…")

        def upload():
            def report(percent, message):
                self.bus.upload_progress.emit(max(0, min(100, round(percent))), message)

            try:
                url, warning = upload_to_youtube(
                    media_path,
                    title,
                    description,
                    visibility,
                    client_file,
                    thumbnail_path,
                    report,
                )
                result = f"Uploaded to YouTube: {url}"
                if warning:
                    result += f"\n{warning}"
            except Exception as exc:
                logging.error("YouTube upload failed: %s", exc)
                self.bus.upload_finished.emit(False, str(exc))
            else:
                self.bus.upload_finished.emit(True, result)

        self.upload_thread = threading.Thread(
            target=upload,
            daemon=True,
            name="StreamSniperYouTubeUpload",
        )
        self.upload_thread.start()

    def update_upload_progress(self, percent: int, message: str):
        self.upload_progress.setValue(percent)
        self.upload_status_label.setText(message)

    def finish_upload(self, success: bool, message: str):
        self.upload_button.setEnabled(True)
        if success:
            self.upload_progress.setValue(100)
            self.upload_status_label.setText(message)
            self.add_log(message.splitlines()[0])
        else:
            self.upload_status_label.setText(f"Upload failed: {message}")
            self.add_log("Upload failed. See the status message for details.")

    # ------------------------------------------------------------------
    # Page navigation and refresh
    # ------------------------------------------------------------------
    def show_page(self, page_name: str):
        indexes = {"dashboard": 0, "channels": 1, "recordings": 2, "activity": 3, "settings": 4, "upload": 5}
        self.page_stack.setCurrentIndex(indexes[page_name])
        # A subtle fade-in keeps navigation feeling smooth without slowing it down.
        page = self.page_stack.currentWidget()
        effect = QGraphicsOpacityEffect(page)
        page.setGraphicsEffect(effect)
        self._page_animation = QPropertyAnimation(effect, b"opacity", self)
        self._page_animation.setDuration(170)
        self._page_animation.setStartValue(0.72)
        self._page_animation.setEndValue(1.0)
        self._page_animation.setEasingCurve(QEasingCurve.OutCubic)
        self._page_animation.start()
        for key, button in self.nav_buttons.items():
            button.setProperty("active", key == page_name)
            button.style().unpolish(button)
            button.style().polish(button)
        if page_name == "recordings":
            self.refresh_recordings()
        elif page_name == "upload":
            self.refresh_upload_recordings()
            self.refresh_youtube_connection_status()
            self.update_upload_destination()

    def refresh_all(self):
        self.refresh_dashboard()
        self.refresh_channels()
        self.refresh_live_recording_controls()
        if self.page_stack.currentIndex() == 5:
            self.refresh_upload_recordings()

    def refresh_live_recording_controls(self):
        active = self.monitor.active_recordings_snapshot()
        active_ids = {recording["video_id"] for recording in active}
        live = [
            stream for stream in self.monitor.live_streams_snapshot()
            if stream["video_id"] not in active_ids
        ]
        for combo, entries in (
            (self.live_stream_selector, live),
            (self.active_recording_selector, active),
        ):
            selected_id = combo.currentData()
            combo.blockSignals(True)
            combo.clear()
            for entry in entries:
                combo.addItem(
                    f"{entry['channel']} — {entry['title']}",
                    entry["video_id"],
                )
            if selected_id is not None:
                selected_index = combo.findData(selected_id)
                if selected_index >= 0:
                    combo.setCurrentIndex(selected_index)
            if combo.currentIndex() < 0 and combo.count():
                combo.setCurrentIndex(0)
            combo.blockSignals(False)
        self.record_full_stream_button.setEnabled(bool(live))
        self.record_section_button.setEnabled(bool(live))
        self.stop_recording_button.setEnabled(bool(active))

    def refresh_dashboard(self):
        total, enabled, uploads = dashboard_counts()
        recordings = self.recording_files()
        self.cards["channels"].value.setText(str(total))
        self.cards["enabled"].value.setText(str(enabled))
        self.cards["uploads"].value.setText(str(uploads))
        self.cards["recordings"].value.setText(str(len(recordings)))
        with self.monitor.lock:
            active = len(self.monitor.recording)
        self.active_label.setText(f"{active} active recording{'s' if active != 1 else ''}")
        running = self.monitor.running
        self.monitor_status.setText("Monitoring is running" if running else "Monitor stopped")
        self.monitor_status.setProperty("state", "running" if running else "stopped")
        self.monitor_status.style().unpolish(self.monitor_status)
        self.monitor_status.style().polish(self.monitor_status)
        self.sidebar_status.setText("●  MONITORING" if running else "●  STOPPED")
        self.sidebar_status.setProperty("state", "running" if running else "stopped")
        self.sidebar_status.style().unpolish(self.sidebar_status)
        self.sidebar_status.style().polish(self.sidebar_status)

    def refresh_channels(self):
        rows = list_channels()
        self.channel_table.blockSignals(True)
        self.channel_table.setRowCount(len(rows))
        for row_index, (channel_id, url, label, enabled, auto_record) in enumerate(rows):
            name_item = QTableWidgetItem(label)
            name_item.setData(Qt.UserRole, channel_id)
            url_item = QTableWidgetItem(url)
            status_item = QTableWidgetItem("●  Enabled" if enabled else "Ⅱ  Paused")
            palette = theme_colors(
                QApplication.instance().property("streamSniperTheme")
            )
            status_item.setForeground(
                QColor(palette["success"] if enabled else palette["muted"])
            )
            auto_item = QTableWidgetItem()
            auto_item.setFlags(auto_item.flags() | Qt.ItemIsUserCheckable | Qt.ItemIsEnabled)
            auto_item.setCheckState(Qt.Checked if auto_record else Qt.Unchecked)
            auto_item.setTextAlignment(Qt.AlignCenter)
            self.channel_table.setItem(row_index, 0, name_item)
            self.channel_table.setItem(row_index, 1, url_item)
            self.channel_table.setItem(row_index, 2, status_item)
            self.channel_table.setItem(row_index, 3, auto_item)
        self.channel_table.blockSignals(False)
        self.filter_channels()

    def update_channel_auto_record(self, item):
        if item.column() != 3:
            return
        channel_id = self.channel_table.item(item.row(), 0).data(Qt.UserRole)
        enabled = item.checkState() == Qt.Checked
        set_channel_auto_record(int(channel_id), enabled)
        label = self.channel_table.item(item.row(), 0).text()
        mode = "automatically" if enabled else "manually"
        self.add_log(f"{label} will be recorded {mode} when live.")

    def recording_files(self):
        if not DATA_DIR.exists():
            return []
        files = [
            path for path in DATA_DIR.rglob("*")
            if path.is_file() and (
                path.suffix.lower() in VIDEO_EXTENSIONS
                or (
                    path.suffix.lower() == ".part"
                    and Path(path.stem).suffix.lower() in VIDEO_EXTENSIONS
                )
            )
        ]
        return sorted(files, key=lambda path: path.stat().st_mtime, reverse=True)

    def refresh_recordings(self):
        files = self.recording_files()
        selected_path = self.selected_recording_path
        self.recording_list.blockSignals(True)
        self.recording_list.clear()
        selected_item = None
        for path in files:
            title, _ = self.recording_metadata(path)
            channel = self.recording_channel_name(path)
            is_partial = path.suffix.lower() == ".part"
            is_active = self.is_recording_active_file(path)
            item = QListWidgetItem()
            item.setData(Qt.UserRole, str(path))
            item.setData(
                Qt.UserRole + 1,
                "in-progress" if is_active else "incomplete" if is_partial else "ready",
            )
            state = " · RECORDING" if is_active else " · INCOMPLETE" if is_partial else ""
            item.setText(f"{title}\n{channel} · {self.format_size(path.stat().st_size)}{state}")
            item.setSizeHint(QSize(260, 82))
            thumbnail = self.recording_thumbnail(path)
            if thumbnail:
                pixmap = QPixmap(str(thumbnail))
                if not pixmap.isNull():
                    scaled = pixmap.scaled(112, 63, Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation)
                    x = max(0, (scaled.width() - 112) // 2)
                    y = max(0, (scaled.height() - 63) // 2)
                    item.setIcon(QIcon(scaled.copy(x, y, 112, 63)))
            self.recording_list.addItem(item)
            if str(path) == selected_path:
                selected_item = item

        if selected_item is None and self.recording_list.count():
            selected_item = self.recording_list.item(0)
        if selected_item:
            self.recording_list.setCurrentItem(selected_item)
        self.recording_list.blockSignals(False)
        if selected_item:
            self.select_recording(selected_item, None)
        else:
            self.select_recording(None, None)
        self.filter_recordings()

    @staticmethod
    def recording_metadata(path: Path):
        sidecar_stem = Path(path.name.removesuffix(".part")).stem
        title = sidecar_stem
        description = ""
        stream_info = path.parent / "stream-info.txt"
        if stream_info.exists():
            try:
                contents = stream_info.read_text(encoding="utf-8")
                title_line, separator, details = contents.partition("\n\nDescription:\n")
                if title_line.startswith("Title:"):
                    title = title_line.partition(":")[2].strip() or title
                if separator:
                    description = details.strip()
                return title, description
            except OSError:
                logging.exception("Could not read stream info text: %s", stream_info)

        for info_path in path.parent.glob(f"{sidecar_stem}*.info.json"):
            try:
                metadata = json.loads(info_path.read_text(encoding="utf-8"))
                return metadata.get("title") or title, metadata.get("description") or ""
            except (OSError, json.JSONDecodeError):
                logging.exception("Could not read stream info JSON: %s", info_path)

        for description_path in path.parent.glob(f"{sidecar_stem}*.description"):
            try:
                description = description_path.read_text(encoding="utf-8").strip()
                break
            except OSError:
                logging.exception("Could not read stream description: %s", description_path)
        return title, description

    @staticmethod
    def recording_thumbnail(path: Path):
        image_extensions = {".jpg", ".jpeg", ".png", ".webp"}
        sidecar_stem = Path(path.name.removesuffix(".part")).stem
        candidates = sorted(
            image for image in path.parent.glob(f"{sidecar_stem}.*")
            if image.suffix.lower() in image_extensions
        )
        return candidates[0] if candidates else None

    def is_recording_active_file(self, path: Path):
        return path.suffix.lower() == ".part" and any(
            recording["video_id"] in path.name
            for recording in self.monitor.active_recordings_snapshot()
        )

    @staticmethod
    def recording_channel_name(path: Path):
        try:
            parts = path.relative_to(DATA_DIR).parts
            return parts[0] if len(parts) > 1 else path.parent.name
        except ValueError:
            return path.parent.name

    def select_recording(self, item, previous_item):
        if item is None:
            self.selected_recording_path = None
            self.recording_title.setText("No streams found")
            self.recording_channel.setText("Saved videos will appear here")
            self.recording_description.clear()
            self.recording_thumbnail.setPixmap(QPixmap())
            self.recording_thumbnail.setText("No saved streams yet")
            self.open_external_button.setEnabled(False)
            self.recover_partial_button.setEnabled(False)
            self.recording_status.setText("")
            return

        path = Path(item.data(Qt.UserRole))
        title, description = self.recording_metadata(path)
        channel = self.recording_channel_name(path)
        self.recording_title.setText(title)
        self.recording_channel.setText(
            f"{channel} · {self.format_size(path.stat().st_size)} · {path.name}"
        )
        self.recording_description.setPlainText(description or "No description was saved for this stream.")
        item_state = item.data(Qt.UserRole + 1)
        is_partial = path.suffix.lower() == ".part"
        self.open_external_button.setEnabled(path.exists() and not is_partial)
        self.recover_partial_button.setEnabled(False)

        if is_partial:
            recovered_path = path.with_suffix("")
            is_active = item_state == "in-progress" or self.is_recording_active_file(path)
            is_idle = time.time() - path.stat().st_mtime >= 120
            self.recover_partial_button.setEnabled(
                not is_active and is_idle and not recovered_path.exists()
            )
            if str(path) != self.selected_recording_path:
                self.selected_recording_path = str(path)
                thumbnail = self.recording_thumbnail(path)
                pixmap = QPixmap(str(thumbnail)) if thumbnail else QPixmap()
                if pixmap.isNull():
                    self.recording_thumbnail.setPixmap(QPixmap())
                    self.recording_thumbnail.setText("Partial recording")
                else:
                    self.recording_thumbnail.setText("")
                    self.recording_thumbnail.setPixmap(
                        pixmap.scaled(QSize(960, 540), Qt.KeepAspectRatio, Qt.SmoothTransformation)
                    )
            if recovered_path.exists():
                self.recording_status.setText("A recovered playable copy is available in this library.")
            elif is_active:
                self.recording_status.setText("Recording in progress; external playback is available when it finishes.")
            elif not is_idle:
                self.recording_status.setText("This file changed recently. Wait for recording to stop before recovery.")
            else:
                self.recording_status.setText("This recording did not finalize. Recover a playable MP4 copy.")
            return

        if str(path) != self.selected_recording_path:
            self.selected_recording_path = str(path)
            thumbnail = self.recording_thumbnail(path)
            pixmap = QPixmap(str(thumbnail)) if thumbnail else QPixmap()
            if pixmap.isNull():
                self.recording_thumbnail.setPixmap(QPixmap())
                self.recording_thumbnail.setText("Thumbnail not available")
            else:
                self.recording_thumbnail.setText("")
                self.recording_thumbnail.setPixmap(
                    pixmap.scaled(QSize(960, 540), Qt.KeepAspectRatio, Qt.SmoothTransformation)
                )
            self.recording_status.setText("")

    def open_recording_externally(self):
        if not self.selected_recording_path:
            return
        path = Path(self.selected_recording_path)
        if path.suffix.lower() == ".part":
            self.recording_status.setText("Wait for the recording to finish before opening it externally.")
            return
        if path.exists():
            os.startfile(str(path))

    def recover_selected_partial(self):
        item = self.recording_list.currentItem()
        if not item:
            return
        partial_path = Path(item.data(Qt.UserRole))
        if partial_path.suffix.lower() != ".part":
            return
        if self.is_recording_active_file(partial_path):
            self.recording_status.setText("Stop the recording before recovery.")
            return
        if time.time() - partial_path.stat().st_mtime < 120:
            self.recording_status.setText("Wait until this file has stopped changing before recovery.")
            return
        self.recover_partial_button.setEnabled(False)
        self.recording_status.setText("Recovering playable MP4 copy…")
        threading.Thread(
            target=self._recover_partial_worker,
            args=(partial_path,),
            daemon=True,
            name="YouTubeGuardPartialRecovery",
        ).start()

    def _recover_partial_worker(self, partial_path: Path):
        try:
            output_path = recover_partial_recording(partial_path)
            self.bus.recovery_finished.emit(str(output_path), "")
        except Exception as exc:
            logging.exception("Partial recording recovery failed")
            self.bus.recovery_finished.emit("", str(exc))

    def finish_partial_recovery(self, output_path: str, error_message: str):
        if error_message:
            self.recording_status.setText(f"Recovery failed: {error_message}")
            item = self.recording_list.currentItem()
            if item:
                partial_path = Path(item.data(Qt.UserRole))
                self.recover_partial_button.setEnabled(
                    partial_path.exists()
                    and not partial_path.with_suffix("").exists()
                    and not self.is_recording_active_file(partial_path)
                    and time.time() - partial_path.stat().st_mtime >= 120
                )
            return
        self.recording_status.setText("Recovered playable copy saved.")
        self.add_log(f"Recovered partial recording: {Path(output_path).name}")
        self.selected_recording_path = output_path
        self.refresh_recordings()

    def record_selected_live_stream(self):
        self.start_selected_live_recording()

    def record_selected_live_section(self):
        minutes, accepted = QInputDialog.getInt(
            self, "Record a section", "Minutes to record from now:", 10, 1, 720
        )
        if accepted:
            self.start_selected_live_recording(duration_seconds=minutes * 60)

    def start_selected_live_recording(self, duration_seconds=None):
        video_id = self.live_stream_selector.currentData()
        stream = next(
            (
                item for item in self.monitor.live_streams_snapshot()
                if item["video_id"] == video_id
            ),
            None,
        )
        if not stream:
            self.recording_status.setText("No live stream is selected.")
            return
        started = self.monitor.start_recording(
            stream["video_id"], stream["title"], stream["link"],
            stream["channel"], duration_seconds,
        )
        self.recording_status.setText(
            f"Recording {stream['channel']} — {stream['title']}"
            if started else "This stream is already being recorded."
        )
        self.refresh_live_recording_controls()

    def stop_selected_recording(self):
        video_id = self.active_recording_selector.currentData()
        if video_id and self.monitor.stop_recording(video_id):
            self.recording_status.setText("Stop requested; the current video is being finalized.")

    # ------------------------------------------------------------------
    # Channel and recording actions
    # ------------------------------------------------------------------
    def add_channel_dialog(self):
        url, accepted = QInputDialog.getText(self, "Add YouTube channel", "Channel URL or @handle URL:")
        if not accepted or not url.strip():
            return
        url = url.strip()
        if not (url.startswith("https://www.youtube.com/") or url.startswith("https://youtube.com/")):
            QMessageBox.warning(self, "Invalid URL", "Enter a YouTube channel URL, such as https://www.youtube.com/@handle")
            return
        default_label = url.rstrip("/").split("/")[-1]
        label, accepted = QInputDialog.getText(self, "Channel name", "Display name:", text=default_label)
        if not accepted:
            return
        try:
            add_channel(url, label.strip() or default_label)
            self.add_log(f"Added channel: {label.strip() or default_label}")
            self.refresh_all()
        except Exception as exc:
            QMessageBox.information(self, "Could not add channel", f"This channel may already be in your list.\n\n{exc}")

    def selected_channel_id(self):
        row = self.channel_table.currentRow()
        if row < 0 or not self.channel_table.item(row, 0):
            return None
        return self.channel_table.item(row, 0).data(Qt.UserRole)

    def remove_selected_channel(self):
        channel_id = self.selected_channel_id()
        if channel_id is None:
            QMessageBox.information(self, "Select a channel", "Choose a channel first.")
            return
        if QMessageBox.question(self, "Remove channel", "Remove this channel from StreamSniper?") == QMessageBox.Yes:
            remove_channel(int(channel_id))
            self.add_log("Channel removed from monitoring list.")
            self.refresh_all()

    def toggle_selected_channel(self):
        channel_id = self.selected_channel_id()
        if channel_id is None:
            QMessageBox.information(self, "Select a channel", "Choose a channel first.")
            return
        toggle_channel(int(channel_id))
        self.refresh_all()

    def browse_data_folder(self):
        folder = QFileDialog.getExistingDirectory(self, "Choose recording folder", self.data_dir_input.text())
        if folder:
            self.data_dir_input.setText(folder)

    def save_settings(self):
        """Save local settings while preserving unrelated user settings."""
        folder_text = self.data_dir_input.text().strip()
        if not folder_text:
            QMessageBox.warning(self, "Recording folder required", "Choose a folder for recordings.")
            return
        recording_folder = Path(folder_text).expanduser()
        if not recording_folder.is_absolute():
            recording_folder = Path.cwd() / recording_folder
        try:
            recording_folder.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            QMessageBox.warning(
                self, "Invalid recording folder", f"Could not use that folder:\n{exc}"
            )
            return

        env_path = CONFIG_PATH
        try:
            set_key(
                str(env_path), "DISCORD_WEBHOOK", self.webhook_input.text().strip(),
                quote_mode="always",
            )
            set_key(
                str(env_path), "DATA_DIR", str(recording_folder),
                quote_mode="always",
            )
        except OSError as exc:
            QMessageBox.warning(
                self, "Could not save settings", f"Local settings were not saved:\n{exc}"
            )
            return
        QMessageBox.information(self, "Settings saved", "Your local settings were saved. Restart StreamSniper to apply them.")

    def open_selected_recording(self, row: int, column: int):
        item = self.recording_table.item(row, 0)
        if item:
            path = item.data(Qt.UserRole)
            if path and Path(path).exists():
                os.startfile(path)

    def open_recordings_folder(self):
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        os.startfile(str(DATA_DIR))

    # ------------------------------------------------------------------
    # Readable activity logging
    # ------------------------------------------------------------------
    @staticmethod
    def extract_log_level(message: str):
        logged_level, separator, detail = message.partition(" ")
        level = {
            "DEBUG": "Debug",
            "INFO": "Info",
            "WARNING": "Warning",
            "ERROR": "Error",
            "CRITICAL": "Error",
        }.get(logged_level.upper())
        if level and separator:
            return level, detail
        return None, message

    @staticmethod
    def classify_event(message: str):
        text = message.lower()
        if text.startswith("debug ") or text.startswith("debug:"):
            return "Debug"
        if any(word in text for word in ("failed", "failure", "error", "exit code", "timed out")):
            return "Error"
        if "live:" in text or "recording started" in text:
            return "Live"
        if any(word in text for word in ("complete", "added channel", "started.", "stopped.")):
            return "Success"
        if any(word in text for word in ("warning", "not configured", "stopping")):
            return "Warning"
        return "Info"

    def add_log(self, message: str):
        timestamp = datetime.now().strftime("%H:%M:%S")
        level, message = self.extract_log_level(message)
        level = level or self.classify_event(message)
        self.log_rows.append((timestamp, level, message))
        logging.info(message)
        if message.startswith((
            "Recording started:", "Recording file active:", "Recording section saved:",
            "Recording complete:", "Recording stopped before",
        )):
            self.refresh_live_recording_controls()
            if self.page_stack.currentIndex() == 2:
                self.refresh_recordings()
        if message.startswith("Recording complete:"):
            self.refresh_dashboard()
        if len(self.log_rows) > 3000:
            self.log_rows = self.log_rows[-3000:]
        self.render_logs()
        self.render_recent_logs()

    def _fill_log_table(self, table: QTableWidget, rows):
        table.setUpdatesEnabled(False)
        table.setRowCount(len(rows))
        colors = log_badge_colors(
            QApplication.instance().property("streamSniperTheme")
        )
        for index, (stamp, level, message) in enumerate(rows):
            time_item = QTableWidgetItem(stamp)
            type_item = QTableWidgetItem(level.upper())
            event_item = QTableWidgetItem(message)
            background, foreground = colors[level]
            type_item.setForeground(QColor(foreground))
            type_item.setBackground(QColor(background))
            type_item.setTextAlignment(Qt.AlignCenter)
            badge_font = table.font()
            badge_font.setBold(True)
            type_item.setFont(badge_font)
            event_item.setToolTip(message)
            table.setItem(index, 0, time_item)
            table.setItem(index, 1, type_item)
            table.setItem(index, 2, event_item)
            table.resizeRowToContents(index)
        table.setUpdatesEnabled(True)
        if self.auto_scroll.isChecked() if hasattr(self, "auto_scroll") else True:
            table.scrollToBottom()

    def render_logs(self):
        if not hasattr(self, "activity_table"):
            return
        needle = self.log_search.text().strip().lower()
        selected_level = self.log_level.currentText()
        rows = [row for row in self.log_rows if (not needle or needle in row[2].lower()) and (selected_level == "All events" or row[1] == selected_level)]
        self._fill_log_table(self.activity_table, rows)

    def render_recent_logs(self):
        if hasattr(self, "recent_table"):
            self._fill_log_table(self.recent_table, self.log_rows[-7:])

    def load_existing_log_once(self):
        if not LOG_PATH.exists():
            return
        try:
            lines = LOG_PATH.read_text(encoding="utf-8", errors="replace").splitlines()[-300:]
            for line in lines:
                if not line.strip():
                    continue
                # Keep the original timestamp when it is present.
                parts = line.split(" ", 2)
                if len(parts) == 3:
                    stamp = parts[1][:8]
                    message = parts[2]
                else:
                    stamp, message = "—", line
                level, message = self.extract_log_level(message)
                self.log_rows.append((stamp, level or self.classify_event(message), message))
            self.render_logs()
            self.render_recent_logs()
        except Exception:
            logging.exception("Could not load previous activity log")

    def export_logs(self):
        path, _ = QFileDialog.getSaveFileName(self, "Export activity", "youtube_guard_activity.txt", "Text files (*.txt)")
        if not path:
            return
        needle = self.log_search.text().strip().lower()
        level = self.log_level.currentText()
        rows = [row for row in self.log_rows if (not needle or needle in row[2].lower()) and (level == "All events" or row[1] == level)]
        Path(path).write_text("\n".join(f"{stamp}  [{kind.upper()}]  {message}" for stamp, kind, message in rows), encoding="utf-8")
        QMessageBox.information(self, "Export complete", f"Exported {len(rows)} events.")

    def open_log_file(self):
        if LOG_PATH.exists():
            os.startfile(str(LOG_PATH))
        else:
            QMessageBox.information(self, "No log file", "The log file will appear after the app records activity.")

    def show_log_details(self, table: QTableWidget, row: int, column: int):
        stamp_item = table.item(row, 0)
        level_item = table.item(row, 1)
        event_item = table.item(row, 2)
        if not stamp_item or not level_item or not event_item:
            return

        dialog = QDialog(self)
        dialog.setObjectName("root")
        dialog.setWindowTitle("Activity details")
        dialog.setMinimumSize(520, 320)
        dialog.resize(720, 440)
        layout = QVBoxLayout(dialog)
        heading = QLabel(f"{stamp_item.text()}    {level_item.text()}")
        heading.setObjectName("muted")
        layout.addWidget(heading)

        details = QTextEdit()
        details.setReadOnly(True)
        details.setLineWrapMode(QTextEdit.WidgetWidth)
        details.setPlainText(event_item.text())
        layout.addWidget(details, 1)

        buttons = QDialogButtonBox(QDialogButtonBox.Close)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)
        dialog.exec()

    # ------------------------------------------------------------------
    # Search, dependencies and shutdown
    # ------------------------------------------------------------------
    def filter_channels(self):
        needle = self.channel_search.text().lower().strip()
        for row in range(self.channel_table.rowCount()):
            match = any(needle in (self.channel_table.item(row, col).text().lower() if self.channel_table.item(row, col) else "") for col in range(4))
            self.channel_table.setRowHidden(row, not match)

    def filter_recordings(self):
        needle = self.recording_search.text().lower().strip()
        for index in range(self.recording_list.count()):
            item = self.recording_list.item(index)
            item.setHidden(needle not in item.text().lower())

    def check_dependencies(self):
        missing = []
        for name, command in [
            ("yt-dlp", yt_dlp_command("--version")),
            ("FFmpeg", ["ffmpeg", "-version"]),
        ]:
            try:
                subprocess.run(command, capture_output=True, timeout=10, check=True)
            except Exception:
                missing.append(name)
        if missing:
            QMessageBox.warning(self, "Dependencies missing", "Missing: " + ", ".join(missing) + ". Install them before recording.")

    def showEvent(self, event):
        super().showEvent(event)
        if os.name == "nt":
            self._apply_windows_taskbar_icon()

    def _apply_windows_taskbar_icon(self):
        if self._native_icon_handles:
            return

        import ctypes

        user32 = ctypes.WinDLL("user32", use_last_error=True)
        load_image = user32.LoadImageW
        load_image.argtypes = [
            ctypes.c_void_p, ctypes.c_wchar_p, ctypes.c_uint,
            ctypes.c_int, ctypes.c_int, ctypes.c_uint,
        ]
        load_image.restype = ctypes.c_void_p
        get_system_metrics = user32.GetSystemMetrics
        get_system_metrics.argtypes = [ctypes.c_int]
        get_system_metrics.restype = ctypes.c_int
        send_message = user32.SendMessageW
        send_message.argtypes = [
            ctypes.c_void_p, ctypes.c_uint, ctypes.c_void_p, ctypes.c_void_p,
        ]
        send_message.restype = ctypes.c_void_p

        icon = 1
        load_from_file = 0x0010
        icon_sizes = (
            (1, get_system_metrics(11), get_system_metrics(12)),
            (0, get_system_metrics(49), get_system_metrics(50)),
        )
        window_handle = ctypes.c_void_p(int(self.winId()))
        loaded_handles = []
        for icon_type, width, height in icon_sizes:
            handle = load_image(
                None, str(APP_ICON_PATH), icon, width, height, load_from_file
            )
            if not handle:
                raise ctypes.WinError(ctypes.get_last_error())
            loaded_handles.append(handle)
            send_message(
                window_handle, 0x0080, ctypes.c_void_p(icon_type), handle
            )

        self._native_icon_handles.extend(loaded_handles)

    def closeEvent(self, event):
        active_upload = self.upload_thread and self.upload_thread.is_alive()
        active_auth = self.youtube_auth_thread and self.youtube_auth_thread.is_alive()
        if active_upload or active_auth:
            answer = QMessageBox.question(
                self,
                "Work in progress",
                "An upload or YouTube sign-in is in progress. Closing may interrupt it. Close anyway?",
            )
            if answer != QMessageBox.Yes:
                event.ignore()
                return
        if self.monitor.thread and self.monitor.thread.is_alive():
            answer = QMessageBox.question(self, "Exit StreamSniper", "Monitoring is active. Stop monitoring and close the app?")
            if answer != QMessageBox.Yes:
                event.ignore()
                return
            self.monitor.stop()
        event.accept()

    @staticmethod
    def format_size(size: int):
        value = float(size)
        for unit in ("B", "KB", "MB", "GB", "TB"):
            if value < 1024 or unit == "TB":
                return f"{value:.1f} {unit}"
            value /= 1024
