# -*- mode: python ; coding: utf-8 -*-
from PyInstaller.utils.hooks import collect_all

datas = [("config.json", "."), ("app.ico", ".")]
binaries = []
hiddenimports = []
for pkg in (
    "PySide6.QtWebEngineCore",
    "PySide6.QtWebEngineWidgets",
    "PySide6.QtMultimedia",
):
    d, b, h = collect_all(pkg)
    datas += d
    binaries += b
    hiddenimports += h

excludes = [
    "PySide6.QtQuick3D",
    "PySide6.Qt3DCore",
    "PySide6.Qt3DRender",
    "PySide6.Qt3DInput",
    "PySide6.Qt3DLogic",
    "PySide6.Qt3DAnimation",
    "PySide6.Qt3DExtras",
    "PySide6.Qt3DQuick",
    "PySide6.QtCharts",
    "PySide6.QtDataVisualization",
    "PySide6.QtGraphs",
    "PySide6.QtDesigner",
    "PySide6.QtUiTools",
    "PySide6.QtSql",
    "PySide6.QtTest",
    "PySide6.QtHelp",
    "PySide6.QtBluetooth",
    "PySide6.QtNfc",
    "PySide6.QtSerialPort",
    "PySide6.QtWebSockets",
    "PySide6.QtSensors",
    "PySide6.QtSpatialAudio",
    "PySide6.QtTextToSpeech",
    "PySide6.QtRemoteObjects",
    "PySide6.QtScxml",
    "PySide6.QtStateMachine",
    "PySide6.QtNetworkAuth",
    "PySide6.QtHttpServer",
    "PySide6.QtPdf",
    "PySide6.QtPdfWidgets",
    "PySide6.QtSvgWidgets",
    "PySide6.QtConcurrent",
    "PySide6.QtOpenGL",
    "PySide6.QtOpenGLWidgets",
    "tkinter",
    "unittest",
    "pydoc",
    "doctest",
    "test",
]


_DROP = (
    "qt6pdf.dll",
    "qt6shadertools.dll",
    "qt6quick3druntimerender.dll",
    "qt6quick3dparticles",
    "qt6quick3d",
    "qt63d",
    "qt6graphs.dll",
    "qt6charts.dll",
    "qt6datavisualization.dll",
    "qt6location.dll",
    "qt6quickcontrols2imagine.dll",
    "qt6quickcontrols2universal.dll",
    "qt6quickcontrols2material.dll",
    "qt6quickcontrols2fluentwinui3.dll",
    "qt6quickdialogs2quickimpl.dll",
    "qt6quickdialogs2.dll",
    "qt6virtualkeyboard.dll",
    "qt6qmlcompiler.dll",
    "qt6quickvectorimage",
)


def _keep(name):
    low = name.replace("\\", "/").lower()
    if "qtwebengine_devtools_resources.pak" in low:
        return False
    if "v8_context_snapshot.debug.bin" in low:
        return False
    if low.endswith("opengl32sw.dll"):
        return False
    if "/translations/" in low:
        return False
    if "/qml/" in low:
        return False
    for d in _DROP:
        if low.endswith(d) or ("/" + d) in low:
            return False
    if "qtwebengine_locales" in low:
        return low.endswith(("en-us.pak", "id.pak"))
    return True


a = Analysis(
    ["exam_browser.py"],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    excludes=excludes,
    noarchive=False,
)
a.datas = [d for d in a.datas if _keep(d[0])]
a.binaries = [b for b in a.binaries if _keep(b[0])]

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="ExamBrowser",
    icon="app.ico",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    onefile=True,
)
