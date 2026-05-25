#!/bin/bash
# Linux 서버에서 ansible-web 실행 (Windows 브라우저에서 접속 가능)
set -e
cd "$(dirname "$0")"

if [ ! -x ./venv/bin/python ]; then
  echo "venv 없음. 먼저: bash setup-venv.sh"
  exit 1
fi

IP=$(hostname -I 2>/dev/null | awk '{print $1}')
echo "============================================"
echo " Ansible Web 시작"
echo " 이 PC에서:  http://127.0.0.1:8080"
echo " Windows 등: http://${IP:-서버IP}:8080"
echo " API 키는 아래 콘솔에 출력됩니다."
echo "============================================"
exec ./venv/bin/python run.py
