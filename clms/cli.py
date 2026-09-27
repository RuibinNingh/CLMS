"""命令行入口：serve（启动界面）/ stats（统计摘要）/ verify（校验提交链）/ export-source（导出脱敏源码包）。"""

import argparse
import json
import os
import webbrowser

from . import drafts, sessions
from .ledger import verify_ledger
from .server import make_server
from .version import VERSION


def main(argv=None):
    parser = argparse.ArgumentParser(description=f"CLMS {VERSION} — 语文错题系统")
    parser.add_argument("--vault", default=".", help="数据根目录，默认当前目录（数据在 <vault>/语文/.clms/）")
    sub = parser.add_subparsers(dest="command")
    serve = sub.add_parser("serve", help="启动 Web 界面")
    serve.add_argument("-p", "--port", type=int, default=8472)
    serve.add_argument("--host", default="127.0.0.1", help="监听地址；默认只允许本机访问")
    serve.add_argument("--open", action="store_true", help="启动后打开浏览器")
    sub.add_parser("stats", help="输出统计摘要")
    sub.add_parser("verify", help="校验 Ledger 提交链")
    export = sub.add_parser("export-source", help="导出脱敏源码包（不依赖 Git）")
    export.add_argument("-o", "--out", default=".", help="zip 存放目录，默认当前目录")
    args = parser.parse_args(argv)
    vault = os.path.abspath(args.vault)

    if args.command == "stats":
        print(json.dumps(sessions.summary(vault), ensure_ascii=False, indent=2))
    elif args.command == "export-source":
        from .source_export import create_source_export
        data, filename, meta = create_source_export(vault)
        target = os.path.join(os.path.abspath(args.out), filename)
        with open(target, "wb") as fh:
            fh.write(data)
        print(f"[OK] 已导出 {meta['files']} 个文件：{target}")
        if meta["redacted"]:
            print("脱敏替换：" + "；".join(meta["redacted"]))
    elif args.command == "verify":
        result = verify_ledger(vault)
        status = "[OK] 提交链完整" if result["ok"] else "[FAIL] 提交链校验失败"
        detail = f"：{result['error']}" if result["error"] else ""
        print(f"{status}，共 {result['count']} 条提交{detail}")
        raise SystemExit(0 if result["ok"] else 1)
    else:
        port = getattr(args, "port", 8472)
        host = getattr(args, "host", "127.0.0.1")
        recovered = drafts.recover(vault)
        server = make_server(vault, host, port)
        url = f"http://{'localhost' if host in ('127.0.0.1', '') else host}:{port}/"
        print(f"CLMS {VERSION}  数据目录 {os.path.join(vault, '语文', '.clms')}")
        if recovered:
            print(f"有 {recovered} 份草稿在上次关闭时处理到一半，已标为可重试")
        print(f"打开 {url}  （Ctrl+C 退出）")
        if host not in ("127.0.0.1", "localhost"):
            print("注意：已监听非本机地址，同一网络里的设备都能访问，且没有登录保护")
        if getattr(args, "open", False):
            webbrowser.open(url)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            print("\n已退出")
