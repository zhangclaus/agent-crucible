from codex_claude_orchestrator.crew.scope import normalize_path, scope_covers, scope_covers_all, is_protected


class TestNormalizePath:
    def test_strips_leading_dot_slash(self):
        assert normalize_path("./src/main.py") == "src/main.py"

    def test_strips_leading_slash(self):
        assert normalize_path("/src/main.py") == "src/main.py"

    def test_normalizes_backslashes(self):
        assert normalize_path("src\\main.py") == "src/main.py"

    def test_strips_whitespace(self):
        assert normalize_path("  src/main.py  ") == "src/main.py"

    def test_empty_string(self):
        assert normalize_path("") == ""

    def test_chained_dot_slash(self):
        assert normalize_path("././src/main.py") == "src/main.py"


class TestScopeCovers:
    def test_empty_scope_returns_false(self):
        assert scope_covers([], "src/main.py") is False

    def test_empty_target_returns_true(self):
        assert scope_covers(["src/"], "") is True

    def test_exact_match_file(self):
        assert scope_covers(["src/main.py"], "src/main.py") is True

    def test_exact_match_directory(self):
        assert scope_covers(["src/"], "src/") is True

    def test_subdirectory_match(self):
        assert scope_covers(["src/"], "src/app/main.py") is True

    def test_nested_subdirectory_match(self):
        assert scope_covers(["src/"], "src/app/deep/file.py") is True

    def test_no_match_sibling_directory(self):
        assert scope_covers(["src/"], "tests/test_main.py") is False

    def test_no_match_parent_directory(self):
        assert scope_covers(["src/app/"], "src/main.py") is False

    def test_no_match_prefix_only(self):
        """src/ should NOT match srca/"""
        assert scope_covers(["src/"], "srca/main.py") is False

    def test_multiple_scopes(self):
        assert scope_covers(["src/", "tests/"], "tests/test_main.py") is True
        assert scope_covers(["src/", "tests/"], "docs/readme.md") is False

    def test_scope_without_trailing_slash(self):
        assert scope_covers(["src"], "src/main.py") is True

    def test_target_with_backslash(self):
        assert scope_covers(["src/"], "src\\main.py") is True

    def test_scope_with_dot_slash(self):
        assert scope_covers(["./src/"], "src/main.py") is True

    def test_bidirectional_prefix_bug_fixed(self):
        """src/app/ should NOT cover src/ (bidirectional prefix was the old bug)"""
        assert scope_covers(["src/app/"], "src/main.py") is False

    def test_file_scope_exact(self):
        assert scope_covers(["pyproject.toml"], "pyproject.toml") is True

    def test_file_scope_no_subdirectory(self):
        assert scope_covers(["pyproject.toml"], "pyproject.toml.bak") is False


class TestScopeCoversAll:
    def test_all_covered(self):
        assert scope_covers_all(["src/", "tests/"], ["src/main.py", "tests/test.py"]) is True

    def test_one_not_covered(self):
        assert scope_covers_all(["src/"], ["src/main.py", "docs/readme.md"]) is False

    def test_empty_targets(self):
        assert scope_covers_all(["src/"], []) is True

    def test_empty_scope_with_targets(self):
        assert scope_covers_all([], ["src/main.py"]) is False


class TestIsProtected:
    def test_git_directory(self):
        assert is_protected(".git/config", [".git/"]) is True

    def test_env_file(self):
        assert is_protected(".env", [".env"]) is True

    def test_pem_file(self):
        assert is_protected("certs/server.pem", ["*.pem"]) is True

    def test_not_protected(self):
        assert is_protected("src/main.py", [".git/", ".env", "*.pem"]) is False

    def test_workflows_directory(self):
        assert is_protected(".github/workflows/ci.yml", [".github/workflows/"]) is True

    def test_protected_with_backslash(self):
        assert is_protected(".git\\config", [".git/"]) is True
