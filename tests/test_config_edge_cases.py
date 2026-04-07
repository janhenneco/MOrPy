import pytest

from mesa_runner.config import MesaConfig, MesaVersion


# --- helpers ---

def make_fake_mesa_dir(tmp_path, version_raw: str):
    mesa_dir = tmp_path / "mesa"
    data_dir = mesa_dir / "data"
    data_dir.mkdir(parents=True)
    (data_dir / "version_number").write_text(version_raw, encoding="utf-8")
    return mesa_dir


# =============================================================================
# MesaVersion.parse_mesa_version — string-handling edge cases
# =============================================================================

def test_parse_strips_leading_trailing_whitespace():
    v = MesaVersion.parse_mesa_version("  r23.05.1  ")
    assert v.scheme == "release"
    assert v.year == 23


def test_parse_uppercase_r_prefix():
    # re.IGNORECASE means R and r are both accepted
    v = MesaVersion.parse_mesa_version("R23.05.1")
    assert v.scheme == "release"
    assert v.year == 23


def test_parse_empty_string_raises():
    with pytest.raises(ValueError):
        MesaVersion.parse_mesa_version("")


def test_parse_bare_r_prefix_raises():
    # "r" alone matches neither release, revision nor git
    with pytest.raises(ValueError):
        MesaVersion.parse_mesa_version("r")


def test_parse_six_char_hex_raises():
    # 6 hex chars is one short of the 7-char minimum for git hashes
    with pytest.raises(ValueError):
        MesaVersion.parse_mesa_version("5c166b")


def test_parse_git_hash_at_minimum_length():
    v = MesaVersion.parse_mesa_version("5c166bf")  # exactly 7 hex chars
    assert v.scheme == "git"
    assert v.version_name == "5c166bf"


def test_parse_git_hash_at_maximum_length():
    v = MesaVersion.parse_mesa_version("a" * 40)   # exactly 40 hex chars (full SHA-1)
    assert v.scheme == "git"


def test_parse_forty_one_char_hex_raises():
    # One character over the git-hash maximum
    with pytest.raises(ValueError):
        MesaVersion.parse_mesa_version("a" * 41)


def test_pure_digit_string_is_revision_not_git():
    # A 7-digit string like "1234567" looks like a hex string but is matched
    # by the revision pattern first (r?(\d+)) and returned as scheme "revision".
    v = MesaVersion.parse_mesa_version("1234567")
    assert v.scheme == "revision"
    assert v.revision == 1234567


# =============================================================================
# MesaVersion comparisons — ordering correctness
# =============================================================================

def test_comparison_release_gt_revision_via_total_ordering():
    # __gt__ is provided by @total_ordering; test it explicitly
    rev = MesaVersion.parse_mesa_version("r12786")
    rel = MesaVersion.parse_mesa_version("r23.05.1")
    assert rel > rev


def test_comparison_git_gt_release():
    # git key is (2, ...), release key is (1, ...) → git sorts highest
    rel = MesaVersion.parse_mesa_version("r23.05.1")
    git = MesaVersion.parse_mesa_version("5c166bf")
    assert git > rel


def test_comparison_two_releases_differ_by_patch_only():
    v1 = MesaVersion.parse_mesa_version("r23.05.1")
    v2 = MesaVersion.parse_mesa_version("r23.05.2")
    assert v1 < v2


def test_comparison_two_revisions():
    v1 = MesaVersion.parse_mesa_version("r12000")
    v2 = MesaVersion.parse_mesa_version("r15000")
    assert v1 < v2


def test_equality_same_release_version():
    v1 = MesaVersion.parse_mesa_version("r23.05.1")
    v2 = MesaVersion.parse_mesa_version("r23.05.1")
    assert v1 == v2


def test_sorted_mixed_list_of_versions():
    versions = [
        MesaVersion.parse_mesa_version("r23.05.1"),
        MesaVersion.parse_mesa_version("r12786"),
        MesaVersion.parse_mesa_version("5c166bf"),
        MesaVersion.parse_mesa_version("r21.12.1"),
    ]
    result = sorted(versions)
    assert result[0].scheme == "revision"        # (0, ...)
    assert result[1].scheme == "release"
    assert result[1].year == 21                  # r21.12.1 before r23.05.1
    assert result[2].scheme == "release"
    assert result[2].year == 23
    assert result[3].scheme == "git"             # (2, ...) sorts last


def test_comparison_with_non_mesaversion_returns_not_implemented():
    v = MesaVersion.parse_mesa_version("r23.05.1")
    assert v.__lt__("some string") is NotImplemented
    assert v.__eq__(42) is NotImplemented


# =============================================================================
# MesaConfig.setup — path handling edge cases
# =============================================================================

def test_setup_accepts_string_mesa_dir(tmp_path):
    mesa_dir = make_fake_mesa_dir(tmp_path, "r23.05.1")
    cfg = MesaConfig.setup(mesa_dir=str(mesa_dir))  # str, not Path
    assert cfg.mesa_version.scheme == "release"


def test_setup_mesa_dir_is_file_raises(tmp_path):
    # A path that exists but is a file, not a directory, still raises FileNotFoundError
    fake_file = tmp_path / "notadir.txt"
    fake_file.write_text("hello")
    with pytest.raises(FileNotFoundError):
        MesaConfig.setup(mesa_dir=fake_file)


def test_setup_version_file_with_trailing_newline(tmp_path):
    # Files on Unix typically end with \n; .strip() should handle this
    mesa_dir = make_fake_mesa_dir(tmp_path, "r23.05.1\n")
    cfg = MesaConfig.setup(mesa_dir=mesa_dir)
    assert cfg.mesa_version.scheme == "release"
    assert cfg.version_raw == "r23.05.1"


def test_setup_version_raw_stores_file_content_not_override(tmp_path):
    # version_raw is always what was in the file; version_name override only
    # affects which MesaVersion is parsed
    mesa_dir = make_fake_mesa_dir(tmp_path, "5c166bf")
    cfg = MesaConfig.setup(mesa_dir=mesa_dir, version_name="r23.05.1")
    assert cfg.version_raw == None
    assert cfg.mesa_version.version_name == "r23.05.1"
    assert cfg.mesa_version.scheme == "release"