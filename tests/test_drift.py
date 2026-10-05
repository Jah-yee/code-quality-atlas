# SPDX-License-Identifier: MIT
# tests/test_drift.py
from pathlib import Path

import pytest

from tooling.drift import DriftReport, check_drift
from tooling.generate_skill import generate_skill
from tooling.manifest import Skill, Source

ROOT = Path(__file__).resolve().parent.parent


def _skill():
    return Skill(
        name="hunting-silent-failures",
        description="x",
        shape="diff",
        wave=1,
        built_from=[Source(2, "tests/fixtures/research_sample.md#2")],
    )


def test_no_drift_right_after_generation(tmp_path):
    generate_skill(_skill(), "v0.2", docs_root=str(ROOT), skills_root=str(tmp_path))
    reports = check_drift(skills_root=str(tmp_path), docs_root=str(ROOT))
    assert reports == []


def test_drift_detected_when_source_changes(tmp_path, monkeypatch):
    generate_skill(_skill(), "v0.2", docs_root=str(ROOT), skills_root=str(tmp_path))
    # Simulate a docs edit by pointing drift at an altered copy of the docs root.
    altered = tmp_path / "docs_altered"
    (altered / "tests" / "fixtures").mkdir(parents=True)
    original = (ROOT / "tests" / "fixtures" / "research_sample.md").read_text()
    (altered / "tests" / "fixtures" / "research_sample.md").write_text(
        original.replace(
            "Does every remote call have a timeout?",
            "Does every remote call have a timeout and deadline?",
        )
    )
    reports = check_drift(skills_root=str(tmp_path), docs_root=str(altered))
    assert len(reports) == 1
    assert isinstance(reports[0], DriftReport)
    assert reports[0].skill == "hunting-silent-failures"
    assert [s.section for s in reports[0].changed] == [2]


def _two_source_skill():
    return Skill(
        name="hunting-silent-failures",
        description="x",
        shape="diff",
        wave=1,
        built_from=[
            Source(2, "tests/fixtures/research_sample.md#2"),
            Source(4, "tests/fixtures/research_sample.md#4"),
        ],
    )


def test_multi_source_drift_only_changed_source_reported(tmp_path):
    """Only the section that was actually edited should appear in DriftReport.changed."""
    generate_skill(
        _two_source_skill(), "v0.2", docs_root=str(ROOT), skills_root=str(tmp_path)
    )
    # Build altered docs root where ONLY section #2 is changed.
    altered = tmp_path / "docs_altered"
    (altered / "tests" / "fixtures").mkdir(parents=True)
    original = (ROOT / "tests" / "fixtures" / "research_sample.md").read_text()
    (altered / "tests" / "fixtures" / "research_sample.md").write_text(
        original.replace(
            "Does every remote call have a timeout?",
            "Does every remote call have a timeout and deadline?",
        )
    )
    reports = check_drift(skills_root=str(tmp_path), docs_root=str(altered))
    assert len(reports) == 1
    assert reports[0].skill == "hunting-silent-failures"
    changed_sections = [s.section for s in reports[0].changed]
    assert changed_sections == [2]  # #2 drifted
    assert 4 not in changed_sections  # #4 untouched


def test_malformed_skill_md_raises_clear_error(tmp_path):
    """A SKILL.md missing its YAML frontmatter must raise a clear error, not a
    bare IndexError from splitting on '---'."""
    import pytest

    skill_dir = tmp_path / "broken"
    skill_dir.mkdir()
    (skill_dir / "SKILL.md").write_text("# broken\n\nno frontmatter here\n")
    with pytest.raises(ValueError, match="frontmatter"):
        check_drift(skills_root=str(tmp_path), docs_root=str(ROOT))


def test_drift_tolerates_crlf_skill_md(tmp_path):
    """A Windows (CRLF) checkout must not break frontmatter parsing."""
    generate_skill(_skill(), "v0.2", docs_root=str(ROOT), skills_root=str(tmp_path))
    skill_md = tmp_path / "hunting-silent-failures" / "SKILL.md"
    crlf = skill_md.read_text(encoding="utf-8").replace("\n", "\r\n")
    skill_md.write_bytes(crlf.encode("utf-8"))
    assert check_drift(skills_root=str(tmp_path), docs_root=str(ROOT)) == []


def test_drift_rejects_frontmatter_without_provenance(tmp_path):
    """Valid YAML but missing name/provenance.built_from must raise a clear
    ValueError, not TypeError/KeyError."""
    import pytest

    skill_dir = tmp_path / "noprov"
    skill_dir.mkdir()
    (skill_dir / "SKILL.md").write_text("---\nname: noprov\n---\n\nbody\n")
    with pytest.raises(ValueError, match="provenance"):
        check_drift(skills_root=str(tmp_path), docs_root=str(ROOT))


def test_drift_missing_source_file_raises_clear_drift_error(tmp_path):
    """A referenced source file that can't be read must raise a clear DriftError
    naming the skill and path, not a bare FileNotFoundError traceback."""
    import pytest

    from tooling.drift import DriftError

    generate_skill(_skill(), "v0.2", docs_root=str(ROOT), skills_root=str(tmp_path))
    # Point docs-root at an empty dir so the referenced source file is missing.
    empty_docs = tmp_path / "empty_docs"
    empty_docs.mkdir()
    with pytest.raises(DriftError) as exc:
        check_drift(skills_root=str(tmp_path), docs_root=str(empty_docs))
    assert "hunting-silent-failures" in str(exc.value)
    assert "research_sample.md" in str(exc.value)


def test_drift_renumbered_source_section_raises_clear_drift_error(tmp_path):
    """A source section that was renumbered/removed in the research doc after
    a skill was generated from it must raise a clear DriftError naming the
    skill, path, and section -- not a bare KeyError traceback from
    extract_section (mirrors the sibling missing-file/non-UTF-8 cases above;
    see issue filed against this exact gap)."""
    import pytest

    from tooling.drift import DriftError

    generate_skill(_skill(), "v0.2", docs_root=str(ROOT), skills_root=str(tmp_path))
    # Point docs-root at a copy of the research doc with section #2 renumbered
    # away, simulating a taxonomy promotion/renumbering after generation.
    altered = tmp_path / "docs_renumbered"
    (altered / "tests" / "fixtures").mkdir(parents=True)
    original = (ROOT / "tests" / "fixtures" / "research_sample.md").read_text()
    (altered / "tests" / "fixtures" / "research_sample.md").write_text(
        original.replace("## #2 ", "## #99 ")
    )
    with pytest.raises(DriftError) as exc:
        check_drift(skills_root=str(tmp_path), docs_root=str(altered))
    assert "hunting-silent-failures" in str(exc.value)
    assert "#2" in str(exc.value)


def test_drift_non_utf8_source_file_raises_clear_drift_error(tmp_path):
    """A source file that exists but isn't valid UTF-8 raises UnicodeDecodeError
    (a ValueError, not an OSError); it must still surface as a clean DriftError."""
    import pytest

    from tooling.drift import DriftError

    generate_skill(_skill(), "v0.2", docs_root=str(ROOT), skills_root=str(tmp_path))
    bad_docs = tmp_path / "bad_docs"
    (bad_docs / "tests" / "fixtures").mkdir(parents=True)
    # invalid UTF-8 bytes at the referenced source path
    (bad_docs / "tests" / "fixtures" / "research_sample.md").write_bytes(
        b"\xff\xfe\x00bad"
    )
    with pytest.raises(DriftError) as exc:
        check_drift(skills_root=str(tmp_path), docs_root=str(bad_docs))
    assert "hunting-silent-failures" in str(exc.value)


def test_drift_built_from_entry_missing_hash_raises_clear_drift_error(tmp_path):
    """A built_from entry missing its `hash` field must raise a clear
    DriftError naming the skill, not a bare KeyError traceback."""
    import pytest

    from tooling.drift import DriftError

    skill_dir = tmp_path / "broken"
    skill_dir.mkdir()
    (skill_dir / "SKILL.md").write_text(
        "---\n"
        "name: broken\n"
        "provenance:\n"
        "  built_from:\n"
        "    - category: 2\n"
        '      source: "tests/fixtures/research_sample.md#2"\n'
        "---\n\nbody\n"
    )
    with pytest.raises(DriftError) as exc:
        check_drift(skills_root=str(tmp_path), docs_root=str(ROOT))
    assert "broken" in str(exc.value)
    assert "hash" in str(exc.value)


def test_drift_built_from_entry_bool_category_raises_clear_drift_error(tmp_path):
    """A built_from entry whose `category` is a bool (a subtype of int in
    Python, so it would otherwise silently masquerade as category 1) must
    raise a clear DriftError naming the skill, not a bare ValueError escaping
    with no skill context."""
    import pytest

    from tooling.drift import DriftError

    skill_dir = tmp_path / "broken"
    skill_dir.mkdir()
    (skill_dir / "SKILL.md").write_text(
        "---\n"
        "name: broken\n"
        "provenance:\n"
        "  built_from:\n"
        "    - category: true\n"
        '      source: "tests/fixtures/research_sample.md#2"\n'
        '      hash: "deadbeef"\n'
        "---\n\nbody\n"
    )
    with pytest.raises(DriftError) as exc:
        check_drift(skills_root=str(tmp_path), docs_root=str(ROOT))
    assert "broken" in str(exc.value)


@pytest.mark.parametrize(
    "entry_yaml, expected_type",
    [
        # built_from entry is a bare string, not a dict
        ('    - "not-a-dict"', "str"),
        # built_from entry is a number
        ("    - 123", "int"),
        # built_from entry is null
        ("    - null", "NoneType"),
        # built_from entry is a bool
        ("    - true", "bool"),
    ],
)
def test_drift_built_from_non_dict_entry_raises_clear_drift_error(
    tmp_path, entry_yaml, expected_type
):
    """A built_from entry that is not a dict (string/number/null/bool) must raise
    a clear DriftError naming the skill and the type received, not a bare
    TypeError escaping with no skill context."""
    from tooling.drift import DriftError

    skill_dir = tmp_path / "broken"
    skill_dir.mkdir()
    (skill_dir / "SKILL.md").write_text(
        "---\n"
        "name: broken\n"
        "provenance:\n"
        "  built_from:\n" + entry_yaml + "\n---\n\nbody\n"
    )
    with pytest.raises(DriftError) as exc:
        check_drift(skills_root=str(tmp_path), docs_root=str(ROOT))
    assert "broken" in str(exc.value)
    assert expected_type in str(exc.value)


@pytest.mark.parametrize(
    "entry_yaml, expected_type",
    [
        # built_from entry is a dict but source is a number
        (
            "    - category: 2\n      source: 5\n      hash: deadbeef",
            "int",
        ),
        # built_from entry is a dict but source is null
        (
            "    - category: 2\n      source: null\n      hash: deadbeef",
            "NoneType",
        ),
    ],
)
def test_drift_built_from_non_string_source_raises_clear_drift_error(
    tmp_path, entry_yaml, expected_type
):
    """A built_from entry whose `source` is not a string (number/null) must raise
    a clear DriftError naming the skill and the offending field, not a bare
    TypeError from Source.__post_init__ with no skill context."""
    from tooling.drift import DriftError

    skill_dir = tmp_path / "broken"
    skill_dir.mkdir()
    (skill_dir / "SKILL.md").write_text(
        "---\n"
        "name: broken\n"
        "provenance:\n"
        "  built_from:\n" + entry_yaml + "\n---\n\nbody\n"
    )
    with pytest.raises(DriftError) as exc:
        check_drift(skills_root=str(tmp_path), docs_root=str(ROOT))
    assert "broken" in str(exc.value)
    assert "source" in str(exc.value)
    assert expected_type in str(exc.value)


def test_drift_built_from_entry_missing_source_raises_clear_drift_error(tmp_path):
    """A built_from entry missing its `source` field must raise a clear
    DriftError naming the missing field, not a type-error about NoneType."""
    import pytest

    from tooling.drift import DriftError

    skill_dir = tmp_path / "broken"
    skill_dir.mkdir()
    (skill_dir / "SKILL.md").write_text(
        "---\n"
        "name: broken\n"
        "provenance:\n"
        "  built_from:\n"
        "    - category: research\n"
        '      hash: "abc123def456"\n'
        "---\n\nbody\n"
    )
    with pytest.raises(DriftError) as exc:
        check_drift(skills_root=str(tmp_path), docs_root=str(ROOT))
    assert "broken" in str(exc.value)
    assert "source" in str(exc.value)


def test_drift_built_from_not_a_list_raises_clear_error(tmp_path):
    """`provenance.built_from` that is not a list (e.g. a bare dict or number)
    must raise a clear TypeError, not a raw TypeError from iteration."""
    import pytest

    skill_dir = tmp_path / "broken"
    skill_dir.mkdir()
    (skill_dir / "SKILL.md").write_text(
        "---\nname: broken\nprovenance:\n  built_from: 7\n---\n\nbody\n"
    )
    with pytest.raises(TypeError, match="built_from"):
        check_drift(skills_root=str(tmp_path), docs_root=str(ROOT))
