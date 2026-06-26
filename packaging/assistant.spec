# PyInstaller spec for the single-file `assistant` binary.
#   build with:  pyinstaller --clean --noconfirm packaging/assistant.spec
#
# Collections below are the load-bearing ones with no stock hook (verified
# against the installed packages). scipy/sklearn/numpy/onnxruntime/pydantic are
# left to pyinstaller-hooks-contrib.
import glob
import os

from PyInstaller.utils.hooks import (
    collect_all,
    collect_data_files,
    collect_dynamic_libs,
    copy_metadata,
)

PROJECT_ROOT = os.path.abspath(os.path.join(SPECPATH, ".."))

datas, binaries, hiddenimports = [], [], []


def add_all(pkg):
    d, b, h = collect_all(pkg)
    datas.extend(d)
    binaries.extend(b)
    hiddenimports.extend(h)


# Packages whose data/native libs resolve via __file__ and have no stock hook.
add_all("openwakeword")  # resources/models/*.onnx (melspectrogram + embedding: mandatory)
add_all("piper")         # espeakbridge.so + espeak-ng-data/ + tashkeel/model.onnx
add_all("dateparser")    # language data
add_all("dateparser_data")
add_all("textual")       # .tcss stylesheet data (drop this + the `tui` subcommand for daemon-only)

datas += collect_data_files("faster_whisper")           # assets/silero_vad_v6.onnx
binaries += collect_dynamic_libs("ctranslate2")          # ctranslate2.libs/{libctranslate2,libgomp}
binaries += collect_dynamic_libs("onnxruntime")          # capi/*.so (belt-and-braces)
datas += collect_data_files("onnxruntime")

# Metadata read at runtime via importlib.metadata / entry points.
for _m in ("apscheduler", "faster_whisper", "huggingface_hub",
           "tokenizers", "ctranslate2", "onnxruntime"):
    datas += copy_metadata(_m)

hiddenimports += [
    "pkg_resources",                       # webrtcvad imports it at module top
    "_webrtcvad", "webrtcvad",
    "yaml",                                # pydantic-settings YamlConfigSettingsSource
    "huggingface_hub",
    "sklearn.utils._typedefs",
    "sklearn.neighbors._partition_nodes",
    "scipy.special.cython_special",
    "apscheduler.triggers.date",
    "apscheduler.triggers.interval",
    "apscheduler.triggers.cron",
    "apscheduler.executors.pool",
    "apscheduler.executors.asyncio",
    "apscheduler.jobstores.memory",
    "tzlocal", "tzdata", "ddgs",
    "assistant.app", "assistant.bootstrap", "assistant.tui.app",
]


# PortAudio: sounddevice ships none and resolves it via ctypes.util.find_library
# at import (which ignores the bundle), so PortAudio stays a host prerequisite
# surfaced by `assistant doctor`. We still bundle the host lib as a fallback.
def _find_portaudio():
    for d in ("/usr/lib", "/usr/lib/x86_64-linux-gnu", "/usr/lib/aarch64-linux-gnu",
              "/lib", "/usr/local/lib"):
        hits = sorted(glob.glob(os.path.join(d, "libportaudio.so*")))
        if hits:
            return hits[-1]
    return None


_pa = _find_portaudio()
if _pa:
    binaries += [(_pa, ".")]

# Project data: config + models tree. cwd-relative paths resolve under _MEIPASS
# because the entrypoint chdir's into the bundle.
datas += [
    (os.path.join(PROJECT_ROOT, "config.yaml"), "."),
    (os.path.join(PROJECT_ROOT, "default-config.yaml"), "."),
    (os.path.join(PROJECT_ROOT, "models"), "models"),
]

a = Analysis(
    [os.path.join(PROJECT_ROOT, "packaging", "entrypoint.py")],
    pathex=[PROJECT_ROOT],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    excludes=["tkinter", "matplotlib", "PyQt5", "PySide6", "IPython"],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="assistant",
    debug=False,
    strip=False,
    upx=False,          # never UPX native ML .so's
    console=True,
    onefile=True,
)
