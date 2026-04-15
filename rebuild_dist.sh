#!/usr/bin/env zsh
# To run the script directly without building:   .venv/bin/python3 advisor.py
# rebuild_dist.sh
# Run this from the advising/ directory after installing Python 3.12 from python.org.
# Builds CoeAdvisor.app and packages it as both .zip and .dmg.

set -e
cd "$(dirname "$0")"

# ── Find python.org Python 3.12 ──────────────────────────────────────────────
PY=""
for candidate in \
    /Library/Frameworks/Python.framework/Versions/3.12/bin/python3.12 \
    /Library/Frameworks/Python.framework/Versions/3.13/bin/python3.13 \
    /Library/Frameworks/Python.framework/Versions/3.11/bin/python3.11; do
  if [[ -x "$candidate" ]]; then
    # Make sure it actually runs on this OS
    if "$candidate" -c "import sys" 2>/dev/null; then
      PY="$candidate"
      break
    fi
  fi
done

if [[ -z "$PY" ]]; then
  echo "ERROR: No python.org Python found in /Library/Frameworks/Python.framework/."
  echo "Download the Python 3.12 macOS universal2 installer from python.org and install it, then re-run this script."
  exit 1
fi

echo "Using Python: $PY  ($($PY --version))"

# ── Check minimum-OS target of this Python ───────────────────────────────────
MINOS=$(otool -l "$PY" 2>/dev/null | awk '/minos/{print $2; exit}')
echo "Minimum macOS target of this Python: ${MINOS:-unknown}"

# ── Ensure tkinter is available ───────────────────────────────────────────────
if ! "$PY" -c "import tkinter" 2>/dev/null; then
  echo "ERROR: tkinter not available in $PY"
  echo "Run the 'Install Certificates.command' from the Python 3.12 install folder,"
  echo "then ensure Tcl/Tk is installed (python.org installer includes it)."
  exit 1
fi

# ── Install / upgrade PyInstaller and dependencies for this Python ────────────
echo "Installing PyInstaller and customtkinter..."
"$PY" -m pip install --upgrade pyinstaller customtkinter --quiet

# ── Clean and rebuild ─────────────────────────────────────────────────────────
echo "Building app..."
"$PY" -m PyInstaller advisor.spec --clean --noconfirm

# ── Verify data files are present ────────────────────────────────────────────
JSON_COUNT=$(find dist/CoeAdvisor.app -name "*.json" 2>/dev/null | wc -l | tr -d ' ')
echo "JSON files in bundle: $JSON_COUNT"

# ── Package ──────────────────────────────────────────────────────────────────
echo "Packaging..."
rm -f dist/CoeAdvisor_macOS.zip dist/CoeAdvisor_macOS.dmg

ditto -c -k --keepParent dist/CoeAdvisor.app dist/CoeAdvisor_macOS.zip
hdiutil create \
  -volname "Coe Advising Tool" \
  -srcfolder dist/CoeAdvisor.app \
  -ov -format UDZO \
  dist/CoeAdvisor_macOS.dmg

echo ""
echo "Done. Distributable files:"
ls -lh dist/CoeAdvisor_macOS.zip dist/CoeAdvisor_macOS.dmg
echo ""
echo "Minimum macOS required: ${MINOS:-check with 'otool -l dist/CoeAdvisor.app/Contents/MacOS/CoeAdvisor'}"
