#!/bin/bash
# Linux — apt python3-pip 불가 환경용 venv + pip 설치
set -e
cd "$(dirname "$0")"

PY="${PYTHON:-python3.11}"
if ! command -v "$PY" &>/dev/null; then
  PY=python3
fi

echo "Python: $($PY --version)"

GET_PIP="$PWD/get-pip.py"

download_get_pip() {
  if command -v curl &>/dev/null; then
    curl -fsSL  https://bootstrap.pypa.io/pip/3.9/get-pip.py -o "$GET_PIP"
  elif command -v wget &>/dev/null; then
    wget -q -O "$GET_PIP" https://bootstrap.pypa.io/pip/3.9/get-pip.py
  else
    echo "curl 또는 wget 이 필요합니다."
    exit 1
  fi
}

# /tmp 대신 프로젝트 폴더에 저장 (curl error 23 방지)
echo "get-pip.py 다운로드 → $GET_PIP"
download_get_pip
[ -s "$GET_PIP" ] || { echo "get-pip.py 다운로드 실패"; exit 1; }

if [ -d venv ]; then
  echo "기존 venv 제거..."
  rm -rf venv || {
    echo ""
    echo "venv 삭제 권한 없음. root 로 실행하거나:"
    echo "  sudo rm -rf $PWD/venv"
    echo "  bash setup-venv.sh"
    exit 1
  }
fi

"$PY" -m venv venv --without-pip
./venv/bin/python "$GET_PIP"
./venv/bin/pip install -r requirements.txt

# root 로 만들었으면 프로젝트 소유자에게 넘김
OWNER=$(stat -c '%U' "$PWD" 2>/dev/null || echo "")
if [ "$(id -u)" = "0" ] && [ -n "$OWNER" ] && [ "$OWNER" != "root" ]; then
  chown -R "$OWNER:$OWNER" venv "$GET_PIP" 2>/dev/null || true
  echo "venv 소유권 → $OWNER"
fi

echo ""
echo "설치 완료. 실행:"
echo "  source venv/bin/activate"
echo "  python run.py"
echo ""
echo "또는: ./venv/bin/python run.py"
