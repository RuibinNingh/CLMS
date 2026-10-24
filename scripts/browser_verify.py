#!/usr/bin/env python3
"""Build-backed UI against a fresh real HTTP service and official MCP client."""
from __future__ import annotations

import json
import os
import secrets
import subprocess
import sys
import tempfile
import textwrap
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.test_server import server  # noqa: E402


def main() -> int:
    evidence = Path(os.getenv('CLMS_VERIFY_ARTIFACTS', ROOT / 'artifacts')).resolve() / 'browser'
    evidence.mkdir(parents=True, exist_ok=True)
    if not (ROOT / 'frontend/dist/index.html').is_file():
        raise RuntimeError('frontend build is required before browser verification')
    with tempfile.TemporaryDirectory(prefix='clms-browser-') as temporary:
        data = Path(temporary) / 'archive'
        from PIL import Image, ImageDraw, ImageFont
        picture = Image.new('RGB', (720, 960), '#fdfcf8')
        draw = ImageDraw.Draw(picture)
        title_font = ImageFont.load_default(size=30)
        body_font = ImageFont.load_default(size=23)
        note_font = ImageFont.load_default(size=16)
        draw.text((58, 46), 'CLMS / SYNTHETIC TEST ORIGINAL', fill='#657181', font=note_font)
        draw.text((58, 95), 'A place I remember', fill='#263c59', font=title_font)
        paragraphs = [
            'At the end of our street stood a small library. Its blue door was always open. On rainy afternoons I would sit beside the window, listening to the soft sound of pages turning.',
            'One day the librarian left a book on my desk. Inside was a note: every ordinary day has a story. I began to notice the tree outside, the footsteps in the hall, and the people who came to read.',
            'The library is different now, but I still remember that afternoon. It taught me to look closely, and to find a little light in familiar places.',
        ]
        line_y = 174
        for paragraph in paragraphs:
            for line in textwrap.wrap(paragraph, width=46):
                draw.line((58, line_y + 31, 660, line_y + 31), fill='#d9dee3', width=1)
                draw.text((58, line_y), line, fill='#343e4c', font=body_font)
                line_y += 39
            line_y += 24
        draw.text((58, 909), 'Fixture only / original image / no production data', fill='#657181', font=note_font)
        image_path = Path(temporary) / 'original.png'
        pdf_path = Path(temporary) / 'material.pdf'
        picture.save(image_path)
        second = Image.new('RGB', (720, 960), '#e5eef8')
        ImageDraw.Draw(second).text((60, 80), 'Second PDF source page', fill='#222222')
        picture.save(pdf_path, save_all=True, append_images=[second])
        with server(ROOT, sys.executable, data, evidence / 'server.log') as (origin, _):
            env = {**os.environ, 'CLMS_TEST_BASE_URL': origin, 'CLMS_TEST_BOOTSTRAP_TOKEN': (data / 'bootstrap.token').read_text().strip(),
                   'CLMS_TEST_PASSWORD': secrets.token_urlsafe(24), 'CLMS_TEST_PYTHON': sys.executable,
                   'CLMS_TEST_EVIDENCE': str(evidence), 'CLMS_TEST_IMAGE': str(image_path), 'CLMS_TEST_PDF': str(pdf_path)}
            result = subprocess.run(['npm', 'run', 'test:browser'], cwd=ROOT / 'frontend', env=env, check=False)
            report_file = evidence / 'playwright.json'
            if not report_file.is_file():
                raise RuntimeError('Playwright must produce a JSON report')
            report = json.loads(report_file.read_text())
            stats = report.get('stats', {})
            if stats.get('skipped', 0) or stats.get('expected', 0) == 0:
                print('required browser tests skipped or zero tests collected', file=sys.stderr)
                return 1
            return result.returncode


if __name__ == '__main__':
    raise SystemExit(main())
