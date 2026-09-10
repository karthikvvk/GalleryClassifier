#!/usr/bin/env bash
# ==============================================================================
# bundle.sh - Package GalleryClassifier into a standalone 3-file ZIP bundle
#
# Output ZIP contains strictly 3 files:
#   1. backend   - PyInstaller onefile binary (FastAPI + ONNX Runtime + Model)
#   2. frontend  - Flutter release executable (self-extracting standalone binary)
#   3. runner.sh - Silent launcher script (creates menu entry + starts backend/frontend)
# ==============================================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# Virtual environment path
VENV_DIR="${VENV_DIR:-$SCRIPT_DIR/virtual}"
PYTHON="$VENV_DIR/bin/python"
PYINSTALLER="$VENV_DIR/bin/pyinstaller"
OUTPUT_ZIP="${1:-$SCRIPT_DIR/gallery_classifier.zip}"
TMP_BUILD_DIR="$SCRIPT_DIR/.bundle_tmp"

# Embedded 256x256 modern PNG app icon (base64)
ICON_B64="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"

echo "============================================================"
echo "📦  GalleryClassifier Bundler"
echo "============================================================"
echo "• Project Root:  $SCRIPT_DIR"
echo "• Virtualenv:    $VENV_DIR"
echo "• Output ZIP:    $OUTPUT_ZIP"
echo "============================================================"

# 1. Sanity Checks
if [ ! -x "$PYTHON" ]; then
    echo "❌ Error: Python not found in virtualenv: $PYTHON"
    exit 1
fi

if ! command -v flutter >/dev/null 2>&1; then
    echo "❌ Error: 'flutter' command not found in PATH."
    exit 1
fi

if [ ! -x "$PYINSTALLER" ]; then
    echo "ℹ️  Installing PyInstaller in virtualenv..."
    "$VENV_DIR/bin/pip" install pyinstaller
fi

# Clean up any leftover build/dist/temporary artifacts before starting
rm -rf "$TMP_BUILD_DIR" "$SCRIPT_DIR/build" "$SCRIPT_DIR/dist" "$SCRIPT_DIR/backend.spec"
mkdir -p "$TMP_BUILD_DIR"

# Cleanup function ensures NO build, dist, or .vscode folders remain on exit
cleanup() {
    rm -rf "$TMP_BUILD_DIR" \
           "$SCRIPT_DIR/build" \
           "$SCRIPT_DIR/dist" \
           "$SCRIPT_DIR/backend.spec" \
           "$SCRIPT_DIR/.vscode"
}
trap cleanup EXIT

# ==============================================================================
# 2. Build Flutter Release
# ==============================================================================
echo ""
echo "🚀 [1/4] Building Flutter release..."
(
    cd "$SCRIPT_DIR/frontend"
    flutter build linux --release
)

FLUTTER_BUNDLE="$SCRIPT_DIR/frontend/build/linux/x64/release/bundle"
if [ ! -f "$FLUTTER_BUNDLE/image_classifier_app" ]; then
    echo "❌ Error: Flutter build output not found at $FLUTTER_BUNDLE"
    exit 1
fi

echo "📦 Packaging Flutter bundle into single-file executable 'frontend'..."
"$PYTHON" - << EOF
import os, tarfile, hashlib, io

bundle_dir = "$FLUTTER_BUNDLE"
tar_buffer = io.BytesIO()
with tarfile.open(fileobj=tar_buffer, mode="w:gz") as tar:
    for item in sorted(os.listdir(bundle_dir)):
        tar.add(os.path.join(bundle_dir, item), arcname=item)

tar_bytes = tar_buffer.getvalue()
bundle_hash = hashlib.md5(tar_bytes).hexdigest()

stub = f"""#!/usr/bin/env bash
# Single-file self-extracting Flutter executable
set -e
APP_NAME="gallery_classifier_frontend"
CACHE_DIR="\${{XDG_CACHE_HOME:-\$HOME/.cache}}/\$APP_NAME"
BUNDLE_HASH="{bundle_hash}"

if [ ! -x "\$CACHE_DIR/image_classifier_app" ] || [ ! -f "\$CACHE_DIR/.hash" ] || [ "\$(cat "\$CACHE_DIR/.hash" 2>/dev/null)" != "\$BUNDLE_HASH" ]; then
    rm -rf "\$CACHE_DIR"
    mkdir -p "\$CACHE_DIR"
    SKIP=\$(awk '/^__PAYLOAD_START__/ {{print NR + 1; exit 0; }}' "\$0")
    tail -n +"\$SKIP" "\$0" | tar -xz -C "\$CACHE_DIR"
    echo "\$BUNDLE_HASH" > "\$CACHE_DIR/.hash"
fi

exec "\$CACHE_DIR/image_classifier_app" "\$@"
exit 0
__PAYLOAD_START__
"""

out_path = "$TMP_BUILD_DIR/frontend"
with open(out_path, "wb") as f:
    f.write(stub.encode("utf-8"))
    f.write(tar_bytes)

os.chmod(out_path, 0o755)
print(f"✓ Single-file frontend created: {os.path.getsize(out_path) / (1024*1024):.1f} MB")
EOF

# ==============================================================================
# 3. Build Python Backend with PyInstaller (--onefile)
# ==============================================================================
echo ""
echo "🚀 [2/4] Building Python backend with PyInstaller (--onefile)..."
"$PYINSTALLER" \
    --noconfirm \
    --clean \
    --onefile \
    --name backend \
    --distpath "$TMP_BUILD_DIR" \
    --workpath "$TMP_BUILD_DIR/pyinstaller_work" \
    --specpath "$TMP_BUILD_DIR" \
    --add-data "$SCRIPT_DIR/backend/runtime/model.onnx:backend/runtime" \
    --add-data "$SCRIPT_DIR/backend/runtime/model.onnx.data:backend/runtime" \
    --add-data "$SCRIPT_DIR/backend/runtime/model.json:backend/runtime" \
    --collect-all uvicorn \
    --collect-all onnxruntime \
    "$SCRIPT_DIR/backend/runtime/server.py"

chmod +x "$TMP_BUILD_DIR/backend"
echo "✓ Backend onefile binary created: $(du -h "$TMP_BUILD_DIR/backend" | cut -f1)"

# ==============================================================================
# 4. Create runner.sh (Silent execution, Menu Entry creation, Lifecycle management)
# ==============================================================================
echo ""
echo "🚀 [3/4] Generating runner.sh with desktop menu entry support..."
cat << EOF > "$TMP_BUILD_DIR/runner.sh"
#!/usr/bin/env bash
# ==============================================================================
# runner.sh - Silent Launcher for GalleryClassifier
# 1. Automatically creates/updates system desktop menu entry.
# 2. Starts backend server and Flutter frontend without opening a terminal window.
# 3. Cleanly terminates the backend process when the frontend window is closed.
# ==============================================================================

SCRIPT_DIR="\$(cd "\$(dirname "\${BASH_SOURCE[0]}")" && pwd)"
cd "\$SCRIPT_DIR"

# Ensure executables have execution permissions
chmod +x "\$SCRIPT_DIR/backend" "\$SCRIPT_DIR/frontend" 2>/dev/null || true

# ------------------------------------------------------------------------------
# Create / update Desktop Menu Entry in ~/.local/share/applications
# ------------------------------------------------------------------------------
DESKTOP_DIR="\${XDG_DATA_HOME:-\$HOME/.local/share}/applications"
ICON_DIR="\${XDG_DATA_HOME:-\$HOME/.local/share}/icons"
DESKTOP_FILE="\$DESKTOP_DIR/gallery-classifier.desktop"
ICON_FILE="\$ICON_DIR/gallery_classifier.png"

mkdir -p "\$DESKTOP_DIR" "\$ICON_DIR"

# Install icon if not present
if [ ! -f "\$ICON_FILE" ]; then
    echo "$ICON_B64" | base64 -d > "\$ICON_FILE" 2>/dev/null || true
fi

# Write desktop entry pointing to this runner.sh
cat << DESKTOPEOF > "\$DESKTOP_FILE"
[Desktop Entry]
Version=1.0
Type=Application
Name=Gallery Classifier
Comment=AI-powered image classification and gallery organization
Exec="\$SCRIPT_DIR/runner.sh"
Icon=\$ICON_FILE
Terminal=false
Categories=Utility;Graphics;Photography;
StartupNotify=true
DESKTOPEOF

chmod +x "\$DESKTOP_FILE"
update-desktop-database "\$DESKTOP_DIR" 2>/dev/null || true

# ------------------------------------------------------------------------------
# Process Management
# ------------------------------------------------------------------------------
BACKEND_PID=""

# Cleanup function to kill backend when frontend exits
cleanup() {
    if [ -n "\$BACKEND_PID" ]; then
        kill "\$BACKEND_PID" 2>/dev/null || true
        wait "\$BACKEND_PID" 2>/dev/null || true
    fi
}
trap cleanup EXIT INT TERM

# Start backend server if port 8000 is not already responding
if ! curl -s http://localhost:8000/health >/dev/null 2>&1; then
    "\$SCRIPT_DIR/backend" >/dev/null 2>&1 &
    BACKEND_PID=\$!

    # Wait up to 15 seconds for backend to become ready
    for i in {1..30}; do
        if curl -s http://localhost:8000/health >/dev/null 2>&1; then
            break
        fi
        if ! kill -0 "\$BACKEND_PID" 2>/dev/null; then
            break
        fi
        sleep 0.5
    done
fi

# Launch frontend (runs until user closes the application window)
"\$SCRIPT_DIR/frontend" >/dev/null 2>&1

EOF

chmod +x "$TMP_BUILD_DIR/runner.sh"
echo "✓ runner.sh created."

# Pre-install icon to user's icon directory
ICON_DIR="${XDG_DATA_HOME:-$HOME/.local/share}/icons"
mkdir -p "$ICON_DIR"
echo "$ICON_B64" | base64 -d > "$ICON_DIR/gallery_classifier.png" 2>/dev/null || true

# ==============================================================================
# 5. Package into ZIP (strictly 3 files with executable permissions preserved)
# ==============================================================================
echo ""
echo "🚀 [4/4] Assembling ZIP archive ($OUTPUT_ZIP)..."
rm -f "$OUTPUT_ZIP"

"$PYTHON" - << EOF
import os, zipfile

zip_path = "$OUTPUT_ZIP"
source_dir = "$TMP_BUILD_DIR"
files_to_pack = ["backend", "frontend", "runner.sh"]

with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
    for name in files_to_pack:
        file_path = os.path.join(source_dir, name)
        if not os.path.exists(file_path):
            raise FileNotFoundError(f"Missing required bundle file: {file_path}")
        
        zinfo = zipfile.ZipInfo(name)
        # Preserve POSIX file permissions (0755: rwxr-xr-x)
        zinfo.external_attr = (0o100755) << 16
        with open(file_path, "rb") as f:
            zf.writestr(zinfo, f.read())

print(f"✓ ZIP created successfully: {os.path.getsize(zip_path) / (1024*1024):.1f} MB")
EOF

# Explicitly ensure build, dist, and .vscode folders are deleted
rm -rf "$SCRIPT_DIR/build" "$SCRIPT_DIR/dist" "$SCRIPT_DIR/backend.spec" "$SCRIPT_DIR/.vscode"

echo ""
echo "============================================================"
echo "🎉 Bundling complete! The ZIP contains strictly 3 files:"
echo "============================================================"
"$PYTHON" -m zipfile -l "$OUTPUT_ZIP"
echo "============================================================"
echo "To use:"
echo "  1. Unzip $OUTPUT_ZIP"
echo "  2. Run ./runner.sh (double-click or execute from terminal)"
echo "  3. 'Gallery Classifier' is also available in your application menu!"
echo "============================================================"
