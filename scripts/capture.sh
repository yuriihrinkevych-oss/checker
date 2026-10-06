#!/usr/bin/env bash
# Швидкий збір скрінів з емулятора Android Studio.
#
# Використання:
#   ./scripts/capture.sh <апка> <країна> [package]
#   ./scripts/capture.sh life360 br com.life360.android.safetymapd
#
# Enter      -> скрін поточного екрана
# f + Enter  -> "чисте встановлення": стерти дані апки і запустити її знову
#               (новий користувач = шанс потрапити в іншу гілку A/B-тесту)
# q + Enter  -> вийти
#
# Скріни лягають у screens/<апка>/<країна>/<дата>/run<N>/001.png ...

set -e
APP="$1"; COUNTRY="$2"; PKG="$3"
if [ -z "$APP" ] || [ -z "$COUNTRY" ]; then
  echo "Використання: $0 <апка> <країна> [package]"; exit 1
fi

ADB="$(command -v adb || true)"
[ -z "$ADB" ] && ADB="$HOME/Library/Android/sdk/platform-tools/adb"
[ -x "$ADB" ] || { echo "Не знайдено adb. Встанови Android Studio або додай platform-tools у PATH."; exit 1; }
"$ADB" get-state >/dev/null 2>&1 || { echo "Емулятор не запущено."; exit 1; }

BASE="screens/$APP/$COUNTRY/$(date +%F)"
RUN=1; while [ -d "$BASE/run$RUN" ]; do RUN=$((RUN+1)); done
DIR="$BASE/run$RUN"; mkdir -p "$DIR"; N=1
echo "Пишу в $DIR"

while true; do
  read -r -p "[Enter=скрін, f=чисте встановлення, q=вихід] " CMD
  case "$CMD" in
    q) break ;;
    f)
      [ -z "$PKG" ] && { echo "Для f вкажи package третім аргументом."; continue; }
      "$ADB" shell pm clear "$PKG" >/dev/null
      "$ADB" shell monkey -p "$PKG" -c android.intent.category.LAUNCHER 1 >/dev/null 2>&1
      RUN=$((RUN+1)); DIR="$BASE/run$RUN"; mkdir -p "$DIR"; N=1
      echo "Дані стерто, апку перезапущено. Новий прохід: $DIR" ;;
    *)
      F="$DIR/$(printf '%03d' $N).png"
      "$ADB" exec-out screencap -p > "$F"
      echo "  збережено $F"; N=$((N+1)) ;;
  esac
done
echo "Готово: $BASE"
