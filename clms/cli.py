"""命令行入口：serve（启动界面）/ stats（统计摘要）/ verify（校验提交链）/ export-source（导出脱敏源码包）。"""

import argparse
import json
import os
import sys
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
    serve.add_argument("--mcp-port", type=int, help="可选官方 MCP 服务的独立本机端口")
    serve.add_argument("--mcp-public-url", help="反向代理 MCP 地址，登记精确 Host/Origin")
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
        mcp_port = getattr(args, "mcp_port", None)
        if mcp_port is not None and (not 1 <= mcp_port <= 65535 or mcp_port == port):
            parser.error("MCP 端口必须为 1–65535，且与 Web 端口不同")
        from . import ai_review, assistant, essays_ocr, runtime_history
        ai_review.recover(vault)
        assistant.recover(vault)
        runtime_history.recover(vault)
        essays_ocr.recover(vault)
        recovered = drafts.recover(vault)
        server = make_server(vault, host, port, restart_enabled=True)
        port = server.server_address[1]
        url = f"http://{'localhost' if host in ('127.0.0.1', '') else host}:{port}/"
        print(f"CLMS {VERSION}  数据目录 {os.path.join(vault, '语文', '.clms')}")
        if recovered:
            print(f"有 {recovered} 份草稿在上次关闭时处理到一半，已标为可重试")
        mcp_service = None
        if mcp_port is not None:
            from .mcp.server import start_background
            try:
                mcp_service = start_background(vault, mcp_port, public_url=getattr(args, "mcp_public_url", None), web_url=url)
            except (ValueError, RuntimeError) as error:
                server.server_close()
                parser.error(str(error))
            print(f"MCP {mcp_service.url}  （独立 Key 鉴权）")
        print(f"打开 {url}  （Ctrl+C 退出）")
        if host not in ("127.0.0.1", "localhost"):
            print("注意：已监听非本机地址，同一网络里的设备都能访问，且没有登录保护")
        if getattr(args, "open", False):
            webbrowser.open(url)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            print("\n已退出")
        finally:
            server.server_close()
            if mcp_service:
                mcp_service.stop()
        if server.restart_requested:
            # exec 保留 PID、环境和 systemd 托管关系；只替换当前程序，不创建第二个服务。
            command = [sys.executable, os.path.join(os.path.dirname(os.path.dirname(__file__)), "clms_engine.py"),
                       "--vault", vault, "serve", "--host", host, "--port", str(port)]
            if mcp_port is not None:
                command.extend(["--mcp-port", str(mcp_port)])
                if getattr(args, "mcp_public_url", None):
                    command.extend(["--mcp-public-url", args.mcp_public_url])
            print("正在重启 CLMS…", flush=True)
            sys.stderr.flush()
            os.execv(sys.executable, command)
