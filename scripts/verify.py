#!/usr/bin/env python3
"""Required engineering gates. Missing dependencies and skipped tests never pass."""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import platform
import subprocess
import sys
import time
import xml.etree.ElementTree as ET
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def utc() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat()


def git(*args: str) -> str | None:
    result = subprocess.run(['git', *args], cwd=ROOT, capture_output=True, text=True, check=False)
    return result.stdout.strip() if result.returncode == 0 else None


def program_version(command: list[str]) -> str | None:
    try:
        result = subprocess.run(command, capture_output=True, text=True, check=False)
        return result.stdout.strip() if result.returncode == 0 else None
    except OSError:
        return None


def package_versions() -> dict[str, str | None]:
    result = {}
    for name in ('fastapi', 'sqlalchemy', 'alembic', 'mcp', 'pillow', 'pypdfium2', 'pytest'):
        try:
            result[name] = version(name)
        except PackageNotFoundError:
            result[name] = None
    return result


def gates(evidence: Path) -> list[tuple[str, list[str], Path, Path | None]]:
    return [
        ('backend', [sys.executable, '-m', 'pytest', 'backend/tests', '--junitxml=' + str(evidence / 'backend.xml'), '-q'], ROOT, evidence / 'backend.xml'),
        ('frontend-types', ['npm', 'run', 'typecheck'], ROOT / 'frontend', None),
        ('frontend-unit', ['npm', 'run', 'test', '--', '--run', '--reporter=junit', '--outputFile=' + str(evidence / 'frontend.xml')], ROOT / 'frontend', evidence / 'frontend.xml'),
        ('frontend-build', ['npm', 'run', 'build'], ROOT / 'frontend', None),
        ('dependency-audit', ['npm', 'audit', '--audit-level=high', '--json'], ROOT / 'frontend', None),
        ('browser', [sys.executable, 'scripts/browser_verify.py'], ROOT, None),
        ('mcp-protocol', [sys.executable, '-m', 'pytest', 'backend/tests/test_mcp_protocol.py', '--junitxml=' + str(evidence / 'mcp.xml'), '-q'], ROOT, evidence / 'mcp.xml'),
        ('security', [sys.executable, '-m', 'pytest', 'backend/tests/test_security.py', '--junitxml=' + str(evidence / 'security.xml'), '-q'], ROOT, evidence / 'security.xml'),
        ('clean-deployment', [sys.executable, 'scripts/clean_deploy_verify.py'], ROOT, None),
    ]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--all', action='store_true', help='Run every required gate.')
    parser.add_argument('--gate', action='append', default=[], help='Run named gates for development only.')
    parser.add_argument('--report', type=Path, default=Path('artifacts/verification.json'))
    args = parser.parse_args()
    if not args.all and not args.gate:
        parser.error('choose --all or one or more --gate names')
    report_path = (ROOT / args.report).resolve() if not args.report.is_absolute() else args.report
    evidence = report_path.parent / 'gates'
    evidence.mkdir(parents=True, exist_ok=True)
    available = gates(evidence)
    unknown = set(args.gate) - {name for name, *_ in available}
    if unknown:
        parser.error('unknown gate: ' + ', '.join(sorted(unknown)))
    selected = available if args.all else [gate for gate in available if gate[0] in args.gate]
    report = {
        'schema_version': 1, 'started_at': utc(), 'baseline_commit': '50f272167b14df9fc27f55fd6f185e5de3418ab2',
        'delivery_commit': git('rev-parse', 'HEAD'), 'branch': git('branch', '--show-current'),
        'working_tree_dirty': bool(git('status', '--porcelain')), 'complete_required_suite': args.all,
        'environment': {'python': sys.version, 'platform': platform.platform(), 'node': program_version(['node', '--version']),
                        'npm': program_version(['npm', '--version']), 'uv': program_version(['uv', '--version']),
                        'packages': package_versions(), 'browser_executable_override': os.getenv('PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH')},
        'gates': [], 'unverified': ['E01–E05 actual external AI account/client', 'Physical tablet/phone', 'Production cutover and legacy production data deletion'],
    }
    for name, command, cwd, junit in selected:
        started = utc()
        before = time.monotonic()
        log = evidence / f'{name}.log'
        status, code, error = 'fail', None, None
        print(f'[{name}] {" ".join(command)}', flush=True)
        try:
            with log.open('w', encoding='utf-8') as output:
                env = os.environ.copy()
                env['CLMS_VERIFY_ARTIFACTS'] = str(report_path.parent)
                process = subprocess.run(command, cwd=cwd, stdout=output, stderr=subprocess.STDOUT, env=env, check=False)
                code = process.returncode
            status = 'pass' if code == 0 else 'fail'
            if junit and code == 0:
                suites = ET.parse(junit).getroot()
                cases = list(suites.iter('testcase'))
                skipped = list(suites.iter('skipped'))
                if not cases or skipped:
                    status = 'fail'
                    error = f'required test suite has {len(cases)} tests and {len(skipped)} skips'
        except (OSError, ET.ParseError) as exc:
            status, error = 'blocked', f'{type(exc).__name__}: {exc}'
            log.write_text(error + '\n', encoding='utf-8')
        item = {'name': name, 'command': command, 'cwd': str(cwd), 'started_at': started, 'finished_at': utc(),
                'duration_seconds': round(time.monotonic() - before, 3), 'exit_code': code, 'status': status,
                'evidence': [str(log)] + ([str(junit)] if junit else []), 'error': error}
        report['gates'].append(item)
        report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
        print(f'[{name}] {status}; exit={code}; evidence={log}', flush=True)
    report['finished_at'] = utc()
    report['status'] = 'pass' if all(item['status'] == 'pass' for item in report['gates']) else 'fail'
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    return 0 if report['status'] == 'pass' else 1


if __name__ == '__main__':
    raise SystemExit(main())
