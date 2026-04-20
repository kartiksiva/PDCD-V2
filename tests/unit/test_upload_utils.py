import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[2]
BACKEND = ROOT / "backend"
sys.path.append(str(BACKEND))

from app.main import _safe_upload_name


def test_safe_upload_name_defaults_to_upload_for_empty_inputs():
    assert _safe_upload_name(None) == "upload"
    assert _safe_upload_name("") == "upload"
    assert _safe_upload_name("   ") == "upload"
    assert _safe_upload_name("...") == "upload"


def test_safe_upload_name_strips_path_traversal_segments():
    assert _safe_upload_name("../evil.txt") == "evil.txt"
    assert _safe_upload_name("..\\..\\evil.txt") == "evil.txt"
    assert _safe_upload_name("/tmp/path/to/file.vtt") == "file.vtt"


def test_safe_upload_name_strips_leading_dots_but_keeps_basename():
    assert _safe_upload_name(".env") == "env"
    assert _safe_upload_name("../.secrets.txt") == "secrets.txt"
