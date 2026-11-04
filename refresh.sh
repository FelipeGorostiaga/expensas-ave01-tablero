#!/bin/bash
# Regenera data.json / data.js a partir de los PDF de la carpeta Expensas y publica data.js
# cifrado (data.enc) en GitHub Pages. Lo ejecuta launchd cada 10 minutos a través de
# "Expensas Refresh.app"; solo trabaja si cambió la lista de PDF. Con FORCE=1 regenera siempre.
set -u
DIR="$(cd "$(dirname "$0")" && pwd)"
PDFS="$(dirname "$DIR")"
LOG="$DIR/refresh.log"
STATE="$DIR/.pdf-state"
LOCK="$DIR/.refresh.lock"
PY=/usr/bin/python3
cd "$DIR" || exit 1

# firma de la carpeta: nombres, tamaños y fechas de los PDF
SIG=$(ls -l "$PDFS"/*.pdf 2>/dev/null | /usr/bin/awk '{print $5, $6, $7, $8, $9, $10, $11, $12}' | /sbin/md5 -q)
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
  if [ ! -x venv/bin/python ]; then
    echo "creando entorno virtual..."
    "$PY" -m venv venv && ./venv/bin/pip install -q -r requirements.txt
  fi
  if ./venv/bin/python parse_expensas.py "$PDFS" data.json; then
    echo "$SIG" > "$STATE"
    ./venv/bin/python -I encrypt_data.py data.json data.enc .password || echo "ERROR al cifrar data.json"
  else
    echo "ERROR: el parser falló; no se actualiza el estado"
  fi
  # publicar: si data.js cambió, commit + push al repo privado (Cloudflare Pages redespliega solo)
  if [ -d .git ] && ! /usr/bin/git diff --quiet -- data.enc; then
    /usr/bin/git add data.enc index.html README.md parse_expensas.py encrypt_data.py refresh.sh requirements.txt .gitignore
    /usr/bin/git -c commit.gpgsign=false commit -q -m "Datos actualizados $(date '+%Y-%m-%d')" \
      && GIT_TERMINAL_PROMPT=0 /usr/bin/git push -q origin main && echo "publicado en GitHub" || echo "ERROR al publicar en GitHub"
  else
    echo "sin cambios en data.enc, no se publica"
  fi
  echo "listo"
} >> "$LOG" 2>&1
tail -n 400 "$LOG" > "$LOG.tmp" && mv "$LOG.tmp" "$LOG"
