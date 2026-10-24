import argparse
import json

from backend.app.auth.service import ensure_bootstrap
from backend.app.config import Settings
from backend.app.db.base import Database


def main():
    parser = argparse.ArgumentParser(prog="CLMS", description="中英作文档案馆")
    subs = parser.add_subparsers(dest="command", required=True)
    subs.add_parser("init", help="迁移空档案库并创建本地首次设置令牌")
    serve = subs.add_parser("serve", help="启动网页及独立鉴权MCP")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=18474)
    cleanup = subs.add_parser("cleanup", help="清理超期无引用暂存原件")
    cleanup.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    settings = Settings()
    if args.command == "serve":
        import uvicorn
        uvicorn.run("backend.app.main:app", host=args.host, port=args.port, proxy_headers=False)
        return
    db = Database(settings)
    db.migrate()
    if args.command == "init":
        ensure_bootstrap(settings)
        print(f"档案库已初始化。首次设置令牌文件：{settings.bootstrap_token_file}")
    else:
        from backend.app.media.service import cleanup, cleanup_orphan_files
        with db.transaction() as session:
            result = cleanup(session, settings, dry_run=not args.apply)
            result.update(cleanup_orphan_files(session, settings, dry_run=not args.apply))
            print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
