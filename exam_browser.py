"""Exam Browser - kiosk/locked-down web client for CBT exams.

Runs the configured exam URL inside a fullscreen Chromium view (QtWebEngine),
suppresses dangerous keyboard shortcuts system-wide, blocks the context menu
and popups, and requires a password (via a secret hotkey) to exit.

Uses PySide6 (LGPL) instead of PyQt6 because PyQt6-Qt6 6.11 dynamically links
a newer ICU (icuuc.dll) that is not present on this machine, whereas PySide6
bundles ICU statically and runs cleanly inside the Anaconda environment.
"""

import json
import os
import sys
import time

from PySide6.QtCore import Qt, QTimer, QUrl
from PySide6.QtGui import (
    QBrush,
    QColor,
    QFont,
    QIcon,
    QKeySequence,
    QLinearGradient,
    QPainter,
    QPixmap,
    QShortcut,
    QTransform,
)
from PySide6.QtWidgets import (
    QApplication,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMainWindow,
    QProgressBar,
    QVBoxLayout,
    QWidget,
)
from PySide6.QtWebEngineCore import (
    QWebEnginePage,
    QWebEngineProfile,
    QWebEngineSettings,
)
from PySide6.QtWebEngineWidgets import QWebEngineView

try:
    from PySide6.QtMultimedia import (
        QCamera,
        QMediaCaptureSession,
        QMediaDevices,
        QVideoSink,
    )

    MULTIMEDIA_AVAILABLE = True
except ImportError:
    MULTIMEDIA_AVAILABLE = False

from keyboard_hook import KeyboardBlocker, VK_MAP, is_key_down

def _app_dir():
    """Directory for config/profile/data: next to the .exe when frozen,
    otherwise next to this source file."""
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))


BASE_DIR = _app_dir()
CONFIG_PATH = os.path.join(BASE_DIR, "config.json")
EXIT_FLAG = os.path.join(BASE_DIR, "exit.flag")
PROFILE_DIR = os.path.join(BASE_DIR, "profile")
CAM_LOG = os.path.join(BASE_DIR, "cam_debug.log")


def _asset_path(name):
    """Locate a bundled asset: the copy inside the frozen exe first
    (PyInstaller _MEIPASS), otherwise next to the source file."""
    if getattr(sys, "frozen", False) and getattr(sys, "_MEIPASS", None):
        candidate = os.path.join(sys._MEIPASS, name)
        if os.path.exists(candidate):
            return candidate
    return os.path.join(BASE_DIR, name)


ICON_PATH = _asset_path("app.ico")


def _camlog(msg):
    if not os.environ.get("EXAMBROWSER_CAM_DEBUG"):
        return
    try:
        with open(CAM_LOG, "a", encoding="utf-8") as fh:
            fh.write("%.2f %s\n" % (time.time(), msg))
    except OSError:
        pass
CACHE_DIR = os.path.join(BASE_DIR, "cache")

DEFAULT_CONFIG = {
    "url": "https://cbt.smkpenerbangan.sch.id",
    "title": "Exam Browser",
    "exit_password": "admin123",
    "secret_combo": ["ctrl", "shift", "q"],
    "fullscreen": True,
    "always_on_top": True,
    "allowed_hosts": [],
    "camera_preview": True,
    "camera_index": 0,
    "camera_size": [320, 180],
    "camera_position": "bottom-right",
    "marquee": {
        "enabled": True,
        "text": "SMKP CAKRA NUSANTARA",
        "height": 30,
        "height_percent": 10,
        "speed": 2,
        "interval": 25,
        "background": ["#ff512f", "#dd2476", "#7b2ff7"],
        "color": "#ffffff",
    },
    "block_keys": {
        "windows_key": True,
        "alt_tab": True,
        "alt_f4": True,
        "alt_esc": True,
        "ctrl_esc": True,
        "ctrl_shift_esc": True,
        "refresh": True,
        "devtools": True,
        "new_window": True,
        "print": True,
        "view_source": True,
    },
}


def deep_merge(base, override):
    result = dict(base)
    for key, value in (override or {}).items():
        if (
            key in result
            and isinstance(result[key], dict)
            and isinstance(value, dict)
        ):
            result[key] = deep_merge(result[key], value)
        else:
            result[key] = value
    return result


def config_candidates():
    """Config locations, in priority order: an override file next to the
    executable/source first, then the copy bundled inside the frozen exe."""
    paths = [CONFIG_PATH]
    if getattr(sys, "frozen", False) and getattr(sys, "_MEIPASS", None):
        paths.append(os.path.join(sys._MEIPASS, "config.json"))
    return paths


def load_config():
    user_cfg = {}
    for path in config_candidates():
        if os.path.exists(path):
            try:
                with open(path, "r", encoding="utf-8") as fh:
                    user_cfg = json.load(fh)
                _camlog("config loaded from %s" % path)
                break
            except (OSError, ValueError):
                user_cfg = {}
    else:
        _camlog("config not found; using built-in defaults")
    return deep_merge(DEFAULT_CONFIG, user_cfg)


def available_cameras():
    """Return the list of camera devices, or [] if none / unsupported."""
    if not MULTIMEDIA_AVAILABLE:
        return []
    try:
        return list(QMediaDevices.videoInputs())
    except Exception:
        return []


class CameraPreview(QWidget):
    """Small always-on-top webcam preview shown in a screen corner.

    It is a separate frameless top-level window so it renders above the
    fullscreen QtWebEngine view (QtWebEngine content would otherwise cover
    child widgets).
    """

    def __init__(self, parent=None):
        super().__init__(None)
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        self.setWindowTitle("Camera")
        self.setCursor(Qt.CursorShape.SizeAllCursor)
        self.setStyleSheet("background:#0b1220; border:2px solid #2563eb;")

        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(2, 2, 2, 2)
        self._layout.setSpacing(0)

        self._label = QLabel(self)
        self._label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._label.setScaledContents(False)
        self._label.setStyleSheet("background:#000; color:#8899aa;")
        self._label.setText("Menyalakan kamera...")
        self._label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self._layout.addWidget(self._label)

        self._drag_offset = None
        self._confine_widget = None

        self._sink = QVideoSink(self)
        self._sink.videoFrameChanged.connect(self._on_frame)
        self._session = QMediaCaptureSession()
        self._session.setVideoSink(self._sink)
        self._camera = None

    def start(self, device, size, position):
        width, height = size
        self.setFixedSize(int(width), int(height))
        self._camera = QCamera(device)
        self._session.setCamera(self._camera)
        self._camera.start()
        self._position = position
        _camlog(
            "START requested=%sx%s size=%sx%s dpr=%s"
            % (width, height, self.width(), self.height(),
               self.devicePixelRatioF())
        )
        self._place(position)
        self.show()
        self.raise_()
        _camlog("START shown frameGeometry=%s" % (self.frameGeometry(),))

    def reposition(self):
        _camlog(
            "REPOSITION confine=%s windowGeometry=%s screen=%s"
            % (
                self._confine_widget.geometry() if self._confine_widget else None,
                self.geometry(),
                QApplication.primaryScreen().availableGeometry()
                if QApplication.primaryScreen() else None,
            )
        )
        self._place(getattr(self, "_position", "bottom-right"))

    def _on_frame(self, frame):
        image = frame.toImage()
        if image.isNull():
            return
        pixmap = QPixmap.fromImage(image)
        # Mirror horizontally so it looks like a selfie preview.
        pixmap = pixmap.transformed(QTransform().scale(-1, 1))
        self._label.setPixmap(
            pixmap.scaled(
                self._label.size(),
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
        )

    def _place(self, position):
        area = None
        if self._confine_widget is not None:
            geo = self._confine_widget.geometry()
            if geo.width() > 0 and geo.height() > 0:
                area = geo
        if area is None:
            screen = QApplication.primaryScreen()
            if screen is None:
                return
            area = screen.availableGeometry()
        margin = 12
        w, h = self.width(), self.height()
        position = (position or "bottom-right").lower()
        if position == "top-left":
            x, y = area.left() + margin, area.top() + margin
        elif position == "top-right":
            x, y = area.right() - w - margin, area.top() + margin
        elif position == "bottom-left":
            x, y = area.left() + margin, area.bottom() - h - margin
        else:  # bottom-right
            x, y = area.right() - w - margin, area.bottom() - h - margin
        x, y = self._clamp(x, y)
        self.move(x, y)
        _camlog(
            "PLACE pos=%s area=%s size=%sx%s -> move=(%s,%s) frameGeometry=%s"
            % (position, area, w, h, x, y, self.frameGeometry())
        )

    def set_confine_widget(self, widget):
        """Keep the preview inside ``widget`` (the browser window)."""
        self._confine_widget = widget

    def _clamp(self, x, y):
        widget = self._confine_widget
        if widget is not None:
            area = widget.geometry()
        else:
            screen = QApplication.primaryScreen()
            if screen is None:
                return x, y
            area = screen.availableGeometry()
        w, h = self.width(), self.height()
        max_x = area.right() - w + 1
        max_y = area.bottom() - h + 1
        x = max(area.left(), min(x, max_x))
        y = max(area.top(), min(y, max_y))
        return x, y

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_offset = (
                event.globalPosition().toPoint() - self.frameGeometry().topLeft()
            )
            _camlog(
                "PRESS global=%s frameTopLeft=%s offset=%s"
                % (event.globalPosition().toPoint(),
                   self.frameGeometry().topLeft(), self._drag_offset)
            )
            self.raise_()
            event.accept()

    def mouseMoveEvent(self, event):
        if self._drag_offset is not None and (
            event.buttons() & Qt.MouseButton.LeftButton
        ):
            pos = event.globalPosition().toPoint() - self._drag_offset
            x, y = self._clamp(pos.x(), pos.y())
            self.move(x, y)
            _camlog(
                "MOVE global=%s -> desired=(%s,%s) clamped=(%s,%s) "
                "confine=%s size=%sx%s"
                % (event.globalPosition().toPoint(), pos.x(), pos.y(), x, y,
                   self._confine_widget.geometry()
                   if self._confine_widget else None,
                   self.width(), self.height())
            )
            event.accept()

    def mouseReleaseEvent(self, event):
        self._drag_offset = None
        event.accept()

    def stop(self):
        if self._camera is not None:
            self._camera.stop()
        self.close()


class MarqueeBar(QWidget):
    """A fixed bottom bar that scrolls a text message continuously.

    It lives inside the main window layout (below the web view) so it stays
    visible at all times and is never covered by the QtWebEngine content.
    """

    def __init__(self, text="", height=30, speed=2, interval=25,
                 background="#0b1220", color="#e5edf7", parent=None):
        super().__init__(parent)
        self._text = text or ""
        self._speed = max(1, int(speed))
        self._offset = 0.0
        self._period = 0.0
        self._gap = 120
        self._bg_spec = background
        self._fg = QColor(color)
        font = QFont()
        font.setBold(True)
        self.setFont(font)
        self.set_height(height)
        self._timer = QTimer(self)
        self._timer.setInterval(int(interval))
        self._timer.timeout.connect(self._tick)
        self._timer.start()

    def set_height(self, height):
        height = max(16, int(height))
        self.setFixedHeight(height)
        font = self.font()
        font.setPixelSize(max(12, int(height * 0.45)))
        self.setFont(font)
        self.update()

    def set_text(self, text):
        self._text = text or ""
        self._offset = 0.0
        self.update()

    def _tick(self):
        self._offset += self._speed
        self.update()

    def _background_brush(self):
        spec = self._bg_spec
        if isinstance(spec, (list, tuple)) and len(spec) >= 2:
            grad = QLinearGradient(0, 0, self.width(), 0)
            step = 1.0 / (len(spec) - 1)
            for i, c in enumerate(spec):
                grad.setColorAt(i * step, QColor(c))
            return QBrush(grad)
        return QBrush(QColor(spec))

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.fillRect(self.rect(), self._background_brush())
        if not self._text:
            return
        painter.setFont(self.font())
        metrics = painter.fontMetrics()
        text_w = metrics.horizontalAdvance(self._text)
        self._period = text_w + self._gap
        self._offset %= self._period
        y = (self.height() + metrics.ascent() - metrics.descent()) // 2
        start = self.width() - self._offset
        while start > -text_w:
            start -= self._period
        start += self._period
        x = start
        while x < self.width():
            painter.setPen(QColor(0, 0, 0, 110))
            painter.drawText(x + 2, y + 2, self._text)
            painter.setPen(self._fg)
            painter.drawText(x, y, self._text)
            x += self._period

    def stop(self):
        self._timer.stop()


class LoadingScreen(QWidget):
    """Frameless always-on-top splash with a progress bar shown while the
    exam page is loading."""

    def __init__(self, title="Exam Browser"):
        super().__init__(None)
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        self.setFixedSize(460, 190)
        self.setStyleSheet(
            "QWidget { background:#0f172a; color:#e2e8f0;"
            " font-family:'Segoe UI'; }"
            "QLabel#title { font-size:22px; font-weight:bold;"
            " color:#ffffff; }"
            "QLabel#status { font-size:13px; color:#94a3b8; }"
            "QProgressBar { border:1px solid #334155; border-radius:6px;"
            " background:#1e293b; height:18px; text-align:center;"
            " color:#e2e8f0; font-size:11px; }"
            "QProgressBar::chunk { background:#2563eb; border-radius:5px; }"
        )

        layout = QVBoxLayout(self)
        layout.setContentsMargins(28, 24, 28, 24)
        layout.setSpacing(12)

        self._title = QLabel(title)
        self._title.setObjectName("title")
        self._status = QLabel("Menyiapkan exam browser...")
        self._status.setObjectName("status")
        self._bar = QProgressBar()
        self._bar.setRange(0, 100)
        self._bar.setValue(0)

        layout.addWidget(self._title)
        layout.addWidget(self._status)
        layout.addWidget(self._bar)

    def set_status(self, text):
        self._status.setText(text)

    def set_progress(self, value):
        self._bar.setValue(max(0, min(100, int(value))))

    def show_centered(self):
        screen = QApplication.primaryScreen()
        if screen is not None:
            area = screen.availableGeometry()
            self.move(
                area.center().x() - self.width() // 2,
                area.center().y() - self.height() // 2,
            )
        self.show()
        self.raise_()



class ExamPage(QWebEnginePage):
    """A page that optionally restricts navigation to allowed hosts and
    never opens separate windows."""

    def __init__(self, profile, parent, allowed_hosts):
        super().__init__(profile, parent)
        self._allowed_hosts = [h.lower() for h in (allowed_hosts or [])]

    def acceptNavigationRequest(self, url, nav_type, is_main_frame):
        host = (url.host() or "").lower()
        if self._allowed_hosts and host:
            allowed = any(
                host == h or host.endswith("." + h) for h in self._allowed_hosts
            )
            if not allowed:
                return False
        return super().acceptNavigationRequest(url, nav_type, is_main_frame)

    def createWindow(self, _window_type):
        # Force popups/new tabs to reuse this page instead of a new window.
        return self


class ExamBrowser(QMainWindow):
    def __init__(self, config):
        super().__init__()
        self.config = config
        self._allow_close = False
        self._shutting_down = False

        self.setWindowTitle(config.get("title", "Exam Browser"))

        flags = Qt.WindowType.FramelessWindowHint
        if config.get("always_on_top", True):
            flags |= Qt.WindowType.WindowStaysOnTopHint
        self.setWindowFlags(flags)

        # Persistent, named profile so login/session survives restarts.
        os.makedirs(PROFILE_DIR, exist_ok=True)
        os.makedirs(CACHE_DIR, exist_ok=True)
        self.profile = QWebEngineProfile("exambrowser", self)
        self.profile.setPersistentStoragePath(PROFILE_DIR)
        self.profile.setCachePath(CACHE_DIR)
        self.profile.setPersistentCookiesPolicy(
            QWebEngineProfile.PersistentCookiesPolicy.ForcePersistentCookies
        )

        self.view = QWebEngineView(self)
        self.view.setContextMenuPolicy(Qt.ContextMenuPolicy.NoContextMenu)

        container = QWidget(self)
        layout = QVBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self.view, 1)
        self.marquee = None
        marquee_cfg = config.get("marquee", {})
        if marquee_cfg.get("enabled", False):
            self.marquee = MarqueeBar(
                text=marquee_cfg.get("text", ""),
                height=marquee_cfg.get("height", 30),
                speed=marquee_cfg.get("speed", 2),
                interval=marquee_cfg.get("interval", 25),
                background=marquee_cfg.get("background", "#0b1220"),
                color=marquee_cfg.get("color", "#e5edf7"),
            )
            layout.addWidget(self.marquee, 0)
        self.setCentralWidget(container)

        page = ExamPage(
            self.profile, self.view, config.get("allowed_hosts", [])
        )
        self.view.setPage(page)

        settings = self.view.settings()
        settings.setAttribute(
            QWebEngineSettings.WebAttribute.JavascriptCanOpenWindows, False
        )
        settings.setAttribute(
            QWebEngineSettings.WebAttribute.LocalStorageEnabled, True
        )
        settings.setAttribute(
            QWebEngineSettings.WebAttribute.FullScreenSupportEnabled, True
        )
        settings.setAttribute(
            QWebEngineSettings.WebAttribute.PluginsEnabled, True
        )

        # System-wide keyboard suppression.
        self.keyboard = KeyboardBlocker(config.get("block_keys", {}))
        self.keyboard.start()

        # Secret combo to request an admin exit.
        self._combo_vks = [
            VK_MAP[name.lower()]
            for name in config.get("secret_combo", [])
            if name.lower() in VK_MAP
        ]
        self._combo_timer = QTimer(self)
        self._combo_timer.setInterval(150)
        self._combo_timer.timeout.connect(self._check_secret_combo)
        self._combo_timer.start()

        # F5 reloads the page (allowed so students can refresh the exam).
        self.refresh_shortcut = QShortcut(QKeySequence(Qt.Key.Key_F5), self)
        self.refresh_shortcut.setContext(
            Qt.ShortcutContext.WindowShortcut
        )
        self.refresh_shortcut.activated.connect(self.view.reload)

        # Optional mini webcam preview (shown only if a camera is present).
        self.camera_preview = None
        self._dialog_open = False
        self._start_camera_preview()

        # Keep the camera preview above the browser even when the browser
        # window is the active one (re-asserts topmost without stealing focus).
        self._cam_raise_timer = QTimer(self)
        self._cam_raise_timer.setInterval(500)
        self._cam_raise_timer.timeout.connect(self._raise_camera)
        self._cam_raise_timer.start()

        # Loading splash shown while the exam page downloads.
        self.loading = LoadingScreen(config.get("title", "Exam Browser"))
        self.view.loadStarted.connect(self._on_load_started)
        self.view.loadProgress.connect(self._on_load_progress)
        self.view.loadFinished.connect(self._on_load_finished)
        self.loading.set_status("Memuat halaman ujian...")
        self.loading.show_centered()

        self.view.setUrl(QUrl(config["url"]))

    # -- page loading splash ----------------------------------------------
    def _on_load_started(self):
        self.loading.set_status("Memuat halaman ujian...")
        self.loading.set_progress(0)
        self.loading.show_centered()

    def _on_load_progress(self, value):
        self.loading.set_progress(value)

    def _on_load_finished(self, ok):
        if ok:
            self.loading.set_progress(100)
            self.loading.hide()
            if self.camera_preview is not None:
                self.camera_preview.raise_()
        else:
            self.loading.set_status(
                "Gagal memuat halaman. Tekan F5 untuk mencoba lagi."
            )

    def _start_camera_preview(self):
        if not self.config.get("camera_preview", True):
            return
        cameras = available_cameras()
        if not cameras:
            return
        index = self.config.get("camera_index", 0)
        if not isinstance(index, int) or not 0 <= index < len(cameras):
            index = 0
        self.camera_preview = CameraPreview()
        self.camera_preview.set_confine_widget(self)
        self.camera_preview.start(
            cameras[index],
            self.config.get("camera_size", [240, 180]),
            self.config.get("camera_position", "bottom-right"),
        )

    # -- window behaviour -------------------------------------------------
    def contextMenuEvent(self, event):
        event.ignore()

    def closeEvent(self, event):
        if self._allow_close:
            event.accept()
        else:
            event.ignore()

    # -- secret exit ------------------------------------------------------
    def _check_secret_combo(self):
        if self._shutting_down or not self._combo_vks:
            return
        if all(is_key_down(vk) for vk in self._combo_vks):
            _camlog("COMBO triggered vks=%s" % (self._combo_vks,))
            self._combo_timer.stop()
            self._ask_exit()
            if not self._shutting_down:
                self._combo_timer.start()

    def _apply_marquee_height(self):
        if self.marquee is None:
            return
        pct = (self.config.get("marquee", {}) or {}).get("height_percent")
        if not pct:
            return
        screen = self.screen()
        base = screen.geometry().height() if screen is not None else self.height()
        self.marquee.set_height(int(base * float(pct) / 100.0))

    def _raise_camera(self):
        if self.camera_preview is None or self._shutting_down or self._dialog_open:
            return
        if not self.camera_preview.isVisible():
            return
        self.camera_preview.raise_()

    def _ask_exit(self):
        self._dialog_open = True
        try:
            text, ok = QInputDialog.getText(
                self,
                "Exit Exam Browser",
                "Masukkan password untuk keluar:",
                QLineEdit.EchoMode.Password,
            )
        finally:
            self._dialog_open = False
        matched = text == self.config.get("exit_password", "admin123")
        _camlog(
            "ASK_EXIT ok=%s matched=%s textlen=%d" % (ok, matched, len(text or ""))
        )
        if ok and matched:
            self._shutdown()

    def _shutdown(self):
        _camlog("SHUTDOWN called")
        self._shutting_down = True
        try:
            with open(EXIT_FLAG, "w", encoding="utf-8") as fh:
                fh.write("exit")
        except OSError:
            pass
        self._cam_raise_timer.stop()
        if self.marquee is not None:
            self.marquee.stop()
        if self.camera_preview is not None:
            self.camera_preview.stop()
        self.loading.close()
        self.keyboard.stop()
        self._allow_close = True
        self.close()
        QApplication.instance().quit()


def main():
    try:
        QApplication.setAttribute(
            Qt.ApplicationAttribute.AA_ShareOpenGLContexts
        )
    except Exception:
        pass

    config = load_config()
    app = QApplication(sys.argv)
    app.setApplicationName(config.get("title", "Exam Browser"))
    if os.path.exists(ICON_PATH):
        app.setWindowIcon(QIcon(ICON_PATH))
    app.setQuitOnLastWindowClosed(False)
    app.aboutToQuit.connect(lambda: _camlog("aboutToQuit signal"))

    browser = ExamBrowser(config)
    if config.get("fullscreen", True):
        browser.showFullScreen()
    else:
        browser.show()
    if browser.camera_preview is not None:
        browser.camera_preview.reposition()
        browser.camera_preview.raise_()
    browser._apply_marquee_height()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
