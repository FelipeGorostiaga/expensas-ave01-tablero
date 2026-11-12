#!/bin/bash
# Regenera data.json / data.js a partir de los PDF de la carpeta Expensas y publica data.js
# cifrado (data.enc) en GitHub Pages. Lo ejecuta launchd cada 10 minutos a través de
# "Expensas Refresh.app"; solo trabaja si cambió la lista de PDF. Con FORCE=1 regenera siempre.
# Funciona en macOS y en Windows (Git Bash).
set -u
DIR="$(cd "$(dirname "$0")" && pwd)"
LOG="$DIR/refresh.log"
STATE="$DIR/.pdf-state"
LOCK="$DIR/.refresh.lock"
cd "$DIR" || exit 1

# carpeta de los PDF: variable PDFS_DIR, o archivo local .pdf-dir (una línea, fuera de git),
# o por defecto la carpeta padre del repo
if [ -n "${PDFS_DIR:-}" ]; then
  PDFS="$PDFS_DIR"
elif [ -s "$DIR/.pdf-dir" ]; then
  PDFS="$(head -n 1 "$DIR/.pdf-dir" | tr -d '\r')"
else
  PDFS="$(dirname "$DIR")"
fi

# python del entorno virtual: venv/bin en macOS y Linux, venv/Scripts en Windows
venv_python() {
  if [ -x venv/bin/python ]; then echo ./venv/bin/python
  elif [ -x venv/Scripts/python.exe ]; then echo ./venv/Scripts/python.exe
  fi
}

md5_stdin() {
  if command -v md5sum >/dev/null 2>&1; then md5sum | cut -d' ' -f1; else /sbin/md5 -q; fi
}

# firma de la carpeta: nombres, tamaños y fechas de los PDF
SIG=$(ls -l "$PDFS"/*.pdf 2>/dev/null | awk '{print $5, $6, $7, $8, $9, $10, $11, $12}' | md5_stdin)
if [ "${FORCE:-0}" != "1" ] && [ -f "$STATE" ] && [ "$(cat "$STATE")" = "$SIG" ]; then
  exit 0   # nada nuevo; salir en silencio
fi

# evitar corridas simultáneas
if ! mkdir "$LOCK" 2>/dev/null; then
  echo "$(date '+%Y-%m-%d %H:%M:%S') otra corrida en curso, se omite" >> "$LOG"; exit 0
fi
trap 'rmdir "$LOCK" 2>/dev/null' EXIT

{
  echo "=== $(date '+%Y-%m-%d %H:%M:%S') ==="
  VPY="$(venv_python)"
  if [ -z "$VPY" ]; then
    echo "creando entorno virtual..."
    if [ -x /usr/bin/python3 ]; then
      /usr/bin/python3 -m venv venv
    elif command -v uv >/dev/null 2>&1; then
      uv venv venv --seed
    else
      python3 -m venv venv || python -m venv venv
    fi
    VPY="$(venv_python)"
    [ -n "$VPY" ] && "$VPY" -m pip install -q -r requirements.txt
  fi
  if [ -z "$VPY" ]; then
    echo "ERROR: no se pudo crear el entorno virtual"
  elif "$VPY" parse_expensas.py "$PDFS" data.json; then
    echo "$SIG" > "$STATE"
    "$VPY" -I encrypt_data.py data.json data.enc .password || echo "ERROR al cifrar data.json"
  else
    echo "ERROR: el parser falló; no se actualiza el estado"
  fi
  # publicar: si data.enc cambió, commit + push (GitHub Pages redespliega solo)
  if [ -d .git ] && ! git diff --quiet -- data.enc; then
    git add data.enc index.html README.md parse_expensas.py encrypt_data.py refresh.sh requirements.txt .gitignore
    git -c commit.gpgsign=false commit -q -m "Datos actualizados $(date '+%Y-%m-%d')" \
      && GIT_TERMINAL_PROMPT=0 git push -q origin main && echo "publicado en GitHub" || echo "ERROR al publicar en GitHub"
  else
    echo "sin cambios en data.enc, no se publica"
  fi
  echo "listo"
} >> "$LOG" 2>&1
tail -n 400 "$LOG" > "$LOG.tmp" && mv "$LOG.tmp" "$LOG"
