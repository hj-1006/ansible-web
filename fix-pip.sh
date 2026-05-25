#!/bin/bash
# venv 는 있는데 pip/패키지 없을 때 (setup-venv.sh 가 curl 실패한 경우)
set -e
cd "$(dirname "$0")"

GET_PIP="$PWD/get-pip.py"

if command -v curl &>/dev/null; then
  curl -fsSL https://bootstrap.pypa.io/get-pip.py -o "$GET_PIP"
else
  wget -q -O "$GET_PIP" https://bootstrap.pypa.io/get-pip.py
fi

if [ ! -x ./venv/bin/python ]; then
  echo "venv 없음. 먼저: bash setup-venv.sh"
  exit 1
fi

./venv/bin/python "$GET_PIP"
./venv/bin/pip install -r requirements.txt

echo "완료. 실행: ./venv/bin/python run.py"
