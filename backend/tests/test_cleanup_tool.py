"""Legacy deletion exercises only disposable, explicitly marked CLMS fixtures."""
import json
from pathlib import Path

import pytest

from scripts.legacy_cleanup import MARKER, boundary, execute, inventory


def legacy(tmp_path):
    clms = tmp_path / 'CLMS'
    root = clms / 'old-data'
    root.mkdir(parents=True)
    (root / MARKER).write_text(json.dumps({'application': 'CLMS', 'purpose': 'legacy-data'}))
    (root / 'ledger.db').write_bytes(b'disposable legacy fixture')
    return root, clms


def test_dry_run_is_read_only_and_snapshot_precedes_deletion(tmp_path):
    root, clms = legacy(tmp_path)
    manifest = inventory(root)
    assert (root / 'ledger.db').exists()
    result = execute(root, clms, tmp_path / 'private-rollback.tar.gz', manifest, str(root))
    assert not root.exists()
    assert Path(result['snapshot']).is_file()
    assert Path(result['snapshot']).stat().st_mode & 0o777 == 0o600


def test_cleanup_rejects_changed_inventory(tmp_path):
    root, clms = legacy(tmp_path)
    manifest = inventory(root)
    (root / 'ledger.db').write_bytes(b'new write after dry run')
    with pytest.raises(ValueError, match='inventory changed'):
        execute(root, clms, tmp_path / 'snapshot.tar.gz', manifest, str(root))
    assert root.exists()


def test_cleanup_requires_exact_confirmed_boundary(tmp_path):
    root, clms = legacy(tmp_path)
    with pytest.raises(ValueError, match='strictly inside'):
        boundary(clms, clms)
    with pytest.raises(ValueError, match='exactly match'):
        execute(root, clms, tmp_path / 'snapshot.tar.gz', inventory(root), str(clms))
    with pytest.raises(ValueError, match='outside'):
        execute(root, clms, clms / 'snapshot.tar.gz', inventory(root), str(root))
    assert root.exists()


def test_cleanup_rejects_symlink_escape_and_unmarked_data(tmp_path):
    root, clms = legacy(tmp_path)
    (root / 'outside').symlink_to(tmp_path)
    with pytest.raises(ValueError, match='symlink'):
        boundary(root, clms)
    (root / 'outside').unlink()
    (root / MARKER).unlink()
    with pytest.raises(FileNotFoundError):
        boundary(root, clms)
