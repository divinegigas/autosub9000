#!/usr/bin/env bash
# Build AutoSub9000-x86_64.AppImage – one self-contained file.
#
# Bundles: Python 3.12 (python-build-standalone), PySide6 (Qt 6, trimmed),
#          whisper.cpp with the Vulkan backend (compiled here),
#          static ffmpeg + ffprobe (BtbN GPL build: includes libass + x264).
# Not bundled: the GPU driver – the system's libvulkan.so.1 + Mesa RADV are used.
#
# Every download is pinned by SHA-256 and cached in build/downloads, so a
# rebuild with the same cache is byte-for-byte reproducible in its inputs.
#
# Usage:  packaging/build-appimage.sh            -> dist/AutoSub9000-x86_64.AppImage
# Env:    JOBS=N            parallel compile jobs
#         FFMPEG_TARBALL    use a local static ffmpeg .tar.xz instead of downloading
#         SKIP_SHA_CHECK=1  accept downloads whose hash differs (prints the new hash)
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
BUILD="$ROOT/build"
DL="$BUILD/downloads"
APPDIR="$BUILD/AppDir"
DIST="$ROOT/dist"
VERSION="$(sed -n 's/^__version__ = "\(.*\)"/\1/p' "$ROOT/autosub/__init__.py")"
OUT="$DIST/AutoSub9000-${VERSION}-x86_64.AppImage"

# ---------------------------------------------------------------- pinned inputs
PY_URL="https://github.com/astral-sh/python-build-standalone/releases/download/20251120/cpython-3.12.12+20251120-x86_64-unknown-linux-gnu-install_only_stripped.tar.gz"
PY_SHA256="8d2cd1393c1aec9d701cebeccb83d1519951f71d3ecb42d5e70c70af4db9be34"

PYSIDE_VERSION="6.10.1"

# BtbN rotates its daily builds; the pinned hash protects against silent changes.
# If the hash check fails because upstream moved on, download a new build,
# check it, and update FFMPEG_SHA256 (or pass FFMPEG_TARBALL=/path/to/file).
FFMPEG_URL="https://github.com/BtbN/FFmpeg-Builds/releases/download/latest/ffmpeg-master-latest-linux64-gpl.tar.xz"
FFMPEG_SHA256="d88bef364ff976b76ae3dedf66ff5b40cc5e361adeadc7f534b0ec1c397ae09e"

APPIMAGETOOL_URL="https://github.com/AppImage/appimagetool/releases/download/1.9.1/appimagetool-x86_64.AppImage"
APPIMAGETOOL_SHA256="ed4ce84f0d9caff66f50bcca6ff6f35aae54ce8135408b3fa33abfc3cb384eb0"
RUNTIME_URL="https://github.com/AppImage/type2-runtime/releases/download/continuous/runtime-x86_64"
RUNTIME_SHA256="617aa77314d57c8b8e4fae9c3f0b35af7b30d5529cb69e98f64f92510ed98a46"

# ---------------------------------------------------------------- helpers
say() { printf '\n\033[1;31m==>\033[0m \033[1m%s\033[0m\n' "$*"; }
die() { echo "error: $*" >&2; exit 1; }

need() {
    local missing=()
    for t in "$@"; do command -v "$t" >/dev/null || missing+=("$t"); done
    if [ ${#missing[@]} -gt 0 ]; then
        die "missing tools: ${missing[*]}  (see README → Building the AppImage)"
    fi
}

fetch() {  # fetch URL SHA256 [filename]
    local url="$1" sha="$2" name="${3:-$(basename "$1")}"
    local f="$DL/$name"
    mkdir -p "$DL"
    if [ ! -f "$f" ]; then
        echo "downloading $name"
        curl -fL --retry 4 --retry-delay 3 -o "$f.tmp" "$url"
        mv "$f.tmp" "$f"
    fi
    local got
    got="$(sha256sum "$f" | cut -d' ' -f1)"
    if [ "$got" != "$sha" ]; then
        if [ "${SKIP_SHA_CHECK:-0}" = 1 ]; then
            echo "warning: $name sha256 is $got (expected $sha) – accepted because SKIP_SHA_CHECK=1" >&2
        else
            die "$name: sha256 mismatch
   expected $sha
   got      $got
   Delete $f to re-download, or update the pin in $0."
        fi
    fi
    echo "$f"
}

need curl tar xz git cmake make gcc g++ glslc patchelf sha256sum file
[ -e /usr/include/vulkan/vulkan.h ] || die "Vulkan headers missing (Fedora: sudo dnf install vulkan-headers vulkan-loader-devel)"

rm -rf "$APPDIR"
mkdir -p "$APPDIR/usr/bin" "$APPDIR/usr/share/autosub9000" "$DIST"

# ---------------------------------------------------------------- python
say "Python runtime"
PY_TGZ="$(fetch "$PY_URL" "$PY_SHA256" | tail -1)"
tar xzf "$PY_TGZ" -C "$APPDIR/usr"
PY="$APPDIR/usr/python/bin/python3"
"$PY" -c 'import sys; print(sys.version)'

# ---------------------------------------------------------------- PySide6
say "PySide6 $PYSIDE_VERSION (trimmed)"
WHEELS="$DL/wheels-$PYSIDE_VERSION"
mkdir -p "$WHEELS"
"$PY" -m pip download --quiet --only-binary=:all: --no-deps -d "$WHEELS" \
    "PySide6-Essentials==$PYSIDE_VERSION" "PySide6-Addons==$PYSIDE_VERSION" "shiboken6==$PYSIDE_VERSION"
"$PY" -m pip install --quiet --no-index --no-compile --no-deps \
    "$WHEELS"/shiboken6-*.whl "$WHEELS"/[Pp]y[Ss]ide6_[Ee]ssentials-*.whl
SITE="$("$PY" -c 'import sysconfig; print(sysconfig.get_paths()["purelib"])')"
# From Addons we only need QtMultimedia (video preview in the subtitle editor).
"$PY" - "$WHEELS" "$SITE" <<'PYEOF'
import glob, re, sys, zipfile
wheels, site = sys.argv[1], sys.argv[2]
whl = glob.glob(f"{wheels}/[Pp]y[Ss]ide6_[Aa]ddons-*.whl")[0]
keep = re.compile(r"^PySide6/(QtMultimedia(Widgets)?\.abi3\.so"
                  r"|Qt/lib/libQt6Multimedia(Widgets)?\.so\.6"
                  r"|Qt/lib/libQt6FFmpegStub-.*"
                  r"|Qt/lib/lib(avcodec|avformat|avutil|swresample|swscale)\.so\.\d+"
                  r"|Qt/plugins/multimedia/libffmpegmediaplugin\.so)$")
with zipfile.ZipFile(whl) as z:
    for info in z.infolist():
        if keep.match(info.filename):
            z.extract(info, site)
            print("  +", info.filename)
PYEOF
# Make extracted .so files executable/readable like pip would.
find "$SITE/PySide6" -name '*.so*' -exec chmod 755 {} +

P6="$SITE/PySide6"
# Trim: tools, QML/Quick, translations, dev files, unused modules.
rm -rf "$P6"/{Qt/qml,Qt/translations,Qt/metatypes,Qt/libexec,include,typesystems,glue,scripts,examples,doc}
rm -f "$P6"/{designer,assistant,linguist,lrelease,lupdate,qmllint,qmlformat,qmlls,qmlcachegen,qmltyperegistrar,qmlimportscanner,rcc,uic,balsam,balsamui,svgtoqml,androiddeployqt,qsb,qtpaths,metaobjectdump.py,project.py}
rm -f "$P6"/*.pyi
for mod in Qml Quick QuickControls2 QuickWidgets QuickTest Designer Help Pdf PdfWidgets Sql Test UiTools Xml \
           OpenGL OpenGLWidgets Concurrent PrintSupport StateMachine SpatialAudio; do
    rm -f "$P6"/Qt"$mod".abi3.so
done
rm -f "$P6"/Qt/lib/libQt6{Qml,Quick,QmlModels,QmlWorkerScript,QmlMeta,QuickControls2,QuickTemplates2,QuickWidgets,QuickTest,QuickShapes,QuickLayouts,QuickEffects,QuickDialogs2,QuickParticles,Designer,DesignerComponents,Help,Pdf,PdfWidgets,PdfQuick,Sql,Test,UiTools,LabsAnimation,LabsFolderListModel,LabsQmlModels,LabsSettings,LabsSharedImage,LabsWavefrontMesh,LabsPlatform,LabsSynchronizer,QmlCompiler,QmlCore,QmlLocalStorage,QmlXmlListModel,ShaderTools,VirtualKeyboard,VirtualKeyboardQml,VirtualKeyboardSettings,QuickControls2Impl,QuickDialogs2Utils,QuickDialogs2QuickImpl,QuickControls2Basic,QuickControls2BasicStyleImpl,QuickControls2Fusion,QuickControls2FusionStyleImpl,QuickControls2Imagine,QuickControls2ImagineStyleImpl,QuickControls2Material,QuickControls2MaterialStyleImpl,QuickControls2Universal,QuickControls2UniversalStyleImpl,QuickControls2FluentWinUI3StyleImpl,QuickControlsTestUtils,QuickVectorImage,QuickVectorImageGenerator,QuickVectorImageHelpers,QmlDebug,QmlDom,QmlToolingSettings,QmlTypeRegistrar,QmlNetwork,QmlAssetDownloader,WaylandEglCompositorHwIntegration,WaylandCompositor}*.so* 2>/dev/null || true
rm -rf "$P6"/Qt/plugins/{qmltooling,designer,sqldrivers,virtualkeyboard,platforminputcontexts/libqtvirtualkeyboardplugin.so,scenegraph,qmllint,assetimporters,renderers}
find "$APPDIR/usr/python" -name '__pycache__' -prune -exec rm -rf {} +
rm -rf "$APPDIR/usr/python/lib/python3.12/"{test,idlelib,tkinter,turtledemo,ensurepip,lib2to3} \
       "$APPDIR/usr/python/lib/"{libtcl*,libtk*,tcl*,tk*,itcl*,thread*} "$APPDIR/usr/python/include" \
       "$APPDIR/usr/python/share"
"$PY" -m pip uninstall --quiet -y pip setuptools 2>/dev/null || true

# ---------------------------------------------------------------- whisper.cpp
say "whisper.cpp with Vulkan"
WORK_DIR="$BUILD/work" JOBS="${JOBS:-$(nproc)}" "$ROOT/packaging/build-whisper.sh" "$APPDIR/usr/bin"

# ---------------------------------------------------------------- ffmpeg
say "Static ffmpeg"
if [ -n "${FFMPEG_TARBALL:-}" ]; then
    FF_TXZ="$FFMPEG_TARBALL"
else
    FF_TXZ="$(fetch "$FFMPEG_URL" "$FFMPEG_SHA256" | tail -1)"
fi
FFTMP="$BUILD/ffmpeg-extract"
rm -rf "$FFTMP" && mkdir -p "$FFTMP"
tar xJf "$FF_TXZ" -C "$FFTMP" --wildcards '*/bin/ffmpeg' '*/bin/ffprobe' '*/LICENSE.txt'
install -m755 "$FFTMP"/*/bin/ffmpeg "$FFTMP"/*/bin/ffprobe "$APPDIR/usr/bin/"
mkdir -p "$APPDIR/usr/share/licenses/ffmpeg"
cp "$FFTMP"/*/LICENSE.txt "$APPDIR/usr/share/licenses/ffmpeg/" 2>/dev/null || true
file "$APPDIR/usr/bin/ffmpeg" | grep -q 'statically linked\|static-pie' || echo "note: ffmpeg is not reported as static"

# ---------------------------------------------------------------- the app
say "AutoSub9000 $VERSION"
cp -r "$ROOT/autosub" "$SITE/"
find "$SITE/autosub" -name '__pycache__' -prune -exec rm -rf {} +
cp -r "$ROOT/assets" "$APPDIR/usr/share/autosub9000/"
mkdir -p "$APPDIR/usr/share/licenses/whisper.cpp"
cp "$BUILD/work/whisper.cpp/LICENSE" "$APPDIR/usr/share/licenses/whisper.cpp/" 2>/dev/null || true
cp "$ROOT/LICENSE" "$APPDIR/usr/share/autosub9000/" 2>/dev/null || true

# icon: render the SVG to PNG with the bundled Qt (no extra build deps)
QT_QPA_PLATFORM=offscreen "$PY" -I - "$ROOT/assets/autosub9000.svg" "$APPDIR/autosub9000.png" <<'PYEOF'
import sys
from PySide6.QtGui import QGuiApplication, QImage, QPainter
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtCore import Qt
app = QGuiApplication([])
img = QImage(256, 256, QImage.Format.Format_ARGB32)
img.fill(Qt.GlobalColor.transparent)
p = QPainter(img); QSvgRenderer(sys.argv[1]).render(p); p.end()
img.save(sys.argv[2])
PYEOF
cp "$APPDIR/autosub9000.png" "$APPDIR/usr/share/autosub9000/assets/autosub9000.png"
mkdir -p "$APPDIR/usr/share/icons/hicolor/256x256/apps" "$APPDIR/usr/share/icons/hicolor/scalable/apps" "$APPDIR/usr/share/applications"
cp "$APPDIR/autosub9000.png" "$APPDIR/usr/share/icons/hicolor/256x256/apps/"
cp "$ROOT/assets/autosub9000.svg" "$APPDIR/usr/share/icons/hicolor/scalable/apps/"
cp "$ROOT/assets/autosub9000.desktop" "$APPDIR/autosub9000.desktop"
cp "$ROOT/assets/autosub9000.desktop" "$APPDIR/usr/share/applications/"
ln -sf autosub9000.png "$APPDIR/.DirIcon"
install -m755 "$ROOT/packaging/AppRun" "$APPDIR/AppRun"

# ---------------------------------------------------------------- smoke test
say "Smoke test (inside AppDir)"
"$APPDIR/AppRun" --version
"$APPDIR/AppRun" --check-gpu || true
QT_QPA_PLATFORM=offscreen "$PY" -I -c '
import PySide6.QtWidgets, PySide6.QtMultimedia, PySide6.QtMultimediaWidgets, PySide6.QtSvg
import autosub.gui.main_window, autosub.gui.editor
print("Qt modules OK")'

# ---------------------------------------------------------------- appimage
say "Packing AppImage"
TOOL="$(fetch "$APPIMAGETOOL_URL" "$APPIMAGETOOL_SHA256" | tail -1)"
RUNTIME="$(fetch "$RUNTIME_URL" "$RUNTIME_SHA256" | tail -1)"
chmod +x "$TOOL"
# --appimage-extract-and-run: works without FUSE (containers, CI)
ARCH=x86_64 SOURCE_DATE_EPOCH="${SOURCE_DATE_EPOCH:-$(git -C "$ROOT" log -1 --format=%ct 2>/dev/null || date +%s)}" \
    "$TOOL" --appimage-extract-and-run --no-appstream --runtime-file "$RUNTIME" \
    --comp zstd "$APPDIR" "$OUT"
ln -sf "$(basename "$OUT")" "$DIST/AutoSub9000-x86_64.AppImage"
(cd "$DIST" && sha256sum "$(basename "$OUT")" > "$(basename "$OUT").sha256")
say "Done: $OUT ($(du -h "$OUT" | cut -f1))"
