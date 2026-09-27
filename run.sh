#!/usr/bin/env sh
# macOS / Linux 启动脚本：数据放在本目录的 语文/.clms/ 下。
# 要放到别处：python3 clms_engine.py --vault <目录> serve --open（--vault 必须写在 serve 前面）。
# 额外参数传给 serve，例如 ./run.sh -p 9000
cd "$(dirname "$0")" || exit 1
exec python3 clms_engine.py serve --open "$@"
