import pytest

from mesa_runner.config import MesaConfig, MesaVersion


def make_fake_mesa_dir(tmp_path, version_raw: str):
    mesa_dir = tmp_path / "mesa"
    data_dir = mesa_dir / "data"
    data_dir.mkdir(parents=True)
    (data_dir / "version_number").write_text(version_raw, encoding="utf-8")
    return mesa_dir


def test_parse_release_with_r():
    v = MesaVersion.parse_mesa_version("r23.05.1")
    assert v.scheme == "release"
    assert v.year == 23
    assert v.month == 5
    assert v.patch == 1


def test_parse_release_without_r():
    v = MesaVersion.parse_mesa_version("23.05.1")
    assert v.scheme == "release"
    assert v.year == 23
    assert v.month == 5
    assert v.patch == 1


def test_parse_release_without_patch_defaults_to_1():
    v = MesaVersion.parse_mesa_version("r23.05")
    assert v.scheme == "release"
    assert v.year == 23
    assert v.month == 5
    assert v.patch == 1


def test_parse_revision_with_and_without_r():
    v1 = MesaVersion.parse_mesa_version("r12786")
    v2 = MesaVersion.parse_mesa_version("12786")
    assert v1.scheme == "revision"
    assert v1.revision == 12786
    assert v2.scheme == "revision"
    assert v2.revision == 12786


def test_parse_git_hash():
    v = MesaVersion.parse_mesa_version("5c166bf")
    assert v.scheme == "git"
    assert v.version_name == "5c166bf"


def test_parse_invalid_raises():
    with pytest.raises(ValueError):
        MesaVersion.parse_mesa_version("not_a_version")


def test_comparison_revision_lt_release():
    rev = MesaVersion.parse_mesa_version("r12786")
    rel = MesaVersion.parse_mesa_version("r23.05.1")
    assert rev < rel


def test_setup_with_explicit_mesa_dir_release(tmp_path):
    mesa_dir = make_fake_mesa_dir(tmp_path, "r23.05.1")
    cfg = MesaConfig.setup(mesa_dir=mesa_dir)

    assert cfg.mesa_dir == mesa_dir.resolve()
    assert cfg.version_raw == "r23.05.1"
    assert cfg.mesa_version.scheme == "release"


def test_setup_uses_env_var(monkeypatch, tmp_path):
    mesa_dir = make_fake_mesa_dir(tmp_path, "12786")
    monkeypatch.setenv("MESA_DIR", str(mesa_dir))

    cfg = MesaConfig.setup()
    assert cfg.mesa_dir == mesa_dir.resolve()
    assert cfg.mesa_version.scheme == "revision"


def test_setup_missing_env_and_no_arg_raises(monkeypatch):
    monkeypatch.delenv("MESA_DIR", raising=False)
    with pytest.raises(EnvironmentError):
        MesaConfig.setup()


def test_setup_nonexistent_dir_raises():
    with pytest.raises(FileNotFoundError):
        MesaConfig.setup(mesa_dir="/this/path/does/not/exist")


def test_setup_git_hash_requires_manual_version(tmp_path):
    mesa_dir = make_fake_mesa_dir(tmp_path, "5c166bf")
    with pytest.raises(ValueError, match="Please specify version_name manually"):
        MesaConfig.setup(mesa_dir=mesa_dir)


def test_setup_git_hash_with_manual_override(tmp_path):
    mesa_dir = make_fake_mesa_dir(tmp_path, "5c166bf")
    cfg = MesaConfig.setup(mesa_dir=mesa_dir, version_name="r23.05.1")

    assert cfg.version_raw == "5c166bf"
    assert cfg.mesa_version.scheme == "release"
    assert cfg.mesa_version.year == 23