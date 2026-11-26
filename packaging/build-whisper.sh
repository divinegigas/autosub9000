#!/usr/bin/env bash
# Build whisper.cpp (whisper-cli) with the Vulkan backend.
#
# Backends are built as loadable modules (GGML_BACKEND_DL): whisper-cli loads
# libggml-vulkan.so at runtime if the system has libvulkan.so.1 and a working
# driver (Mesa RADV on AMD). If not, only the CPU backend is used. CPU code is
# built for all x86-64 variants and the best one is picked at runtime, so the
# binary is portable between machines.
#
# Usage: packaging/build-whisper.sh [OUTPUT_DIR]   (default: vendor/bin)
set -euo pipefail

WHISPER_VERSION="${WHISPER_VERSION:-v1.8.2}"
WHISPER_COMMIT="${WHISPER_COMMIT:-4979e04f5dcaccb36057e059bbaed8a2f5288315}"

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
OUT="${1:-$ROOT/vendor/bin}"
WORK="${WORK_DIR:-$ROOT/build/work}"
SRC="$WORK/whisper.cpp"
JOBS="${JOBS:-$(nproc)}"

mkdir -p "$WORK" "$OUT"

if [ ! -d "$SRC/.git" ]; then
    git clone --depth 1 --branch "$WHISPER_VERSION" https://github.com/ggml-org/whisper.cpp "$SRC"
fi
actual="$(git -C "$SRC" rev-parse HEAD)"
if [ "$actual" != "$WHISPER_COMMIT" ]; then
    echo "error: whisper.cpp $WHISPER_VERSION is at $actual, expected $WHISPER_COMMIT" >&2
    exit 1
fi

cmake -S "$SRC" -B "$SRC/build" -G "Unix Makefiles" \
    -DCMAKE_BUILD_TYPE=Release \
    -DBUILD_SHARED_LIBS=ON \
    -DGGML_BACKEND_DL=ON \
    -DGGML_CPU_ALL_VARIANTS=ON \
    -DGGML_NATIVE=OFF \
    -DGGML_VULKAN=ON \
    -DGGML_OPENMP=OFF \
    -DWHISPER_BUILD_TESTS=OFF \
    -DWHISPER_BUILD_SERVER=OFF \
    -DWHISPER_BUILD_EXAMPLES=ON \
    -DWHISPER_SDL2=OFF \
    -DWHISPER_CURL=OFF \
    -DCMAKE_BUILD_RPATH='$ORIGIN' \
    -DCMAKE_INSTALL_RPATH='$ORIGIN' \
    -DCMAKE_BUILD_RPATH_USE_ORIGIN=ON
cmake --build "$SRC/build" --target whisper-cli -j "$JOBS"

# Collect whisper-cli, libwhisper, libggml* and all backend modules into $OUT.
cp -a "$SRC/build/bin/whisper-cli" "$OUT/"
find "$SRC/build" \( -name 'libwhisper.so*' -o -name 'libggml*.so*' \) -exec cp -a {} "$OUT/" \;
for f in "$OUT"/whisper-cli "$OUT"/lib*.so*; do
    [ -L "$f" ] && continue
    patchelf --set-rpath '$ORIGIN' "$f" 2>/dev/null || true
    strip --strip-unneeded "$f" 2>/dev/null || true
done
echo "whisper-cli built into $OUT:"
ls -la "$OUT"
