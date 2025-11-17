import argparse
from pathlib import Path

# Import functions from the generate script
# Assuming app/dependabot-configurator is on sys.path when tests are run
import generate
import structlog
from ruamel.yaml import YAML

# Initialize YAML parsers
yaml_loader = YAML(typ="safe")
yaml_dumper = YAML()  # Use default round-trip dumper for writing ignore file
yaml_dumper.indent(mapping=2, sequence=4, offset=2)


# Helper to create configurator settings file
def create_config_file(repo_path: Path, config_rules: list):
    """Creates a .configurator_settings.yml file in the mock repo."""
    config_file_path = repo_path / ".github" / ".configurator_settings.yml"
    config_file_path.parent.mkdir(parents=True, exist_ok=True)
    with open(config_file_path, "w") as f:
        yaml_dumper.dump(config_rules, f)


def test_basic_pip_detection(tmp_path: Path):
    """
    Tests that a simple requirements.txt in the root is detected
    and generates the correct pip entries.
    """
    # Arrange: Create a mock repository with requirements.txt
    (tmp_path / "requirements.txt").touch()

    # Act: Run the generator script
    args = argparse.Namespace(
        repo_path=str(tmp_path),
        open_pull_requests_limit=1,
        main_branch="main",
        transitive_security=False,
    )
    generate.main(args)

    # Assert: Check the generated dependabot.yml
    generated_config_path = tmp_path / ".github" / "dependabot.yml"
    assert generated_config_path.exists(), "dependabot.yml was not created"

    with open(generated_config_path, "r") as f:
        config = yaml_loader.load(f)  # Use yaml_loader

    assert "version" in config
    assert config["version"] == 2
    assert "updates" in config
    assert isinstance(config["updates"], list)
    assert len(config["updates"]) == 2, "Expected 2 update entries (version + security)"

    # Check version update entry
    version_entry = config["updates"][0]
    assert version_entry["package-ecosystem"] == "pip"
    assert version_entry["directory"] == "/"
    assert version_entry["open-pull-requests-limit"] == 1
    assert "prodsec" not in version_entry.get(
        "groups", {}
    )  # Security group should not be in version entry

    # Check security update entry
    security_entry = config["updates"][1]
    assert security_entry["package-ecosystem"] == "pip"
    assert security_entry["directory"] == "/"
    assert security_entry["open-pull-requests-limit"] == 0
    assert "prodsec" in security_entry.get("groups", {})


def test_registry_configuration_basic(tmp_path: Path):
    """
    Tests that registry configurations are properly added to the dependabot config.
    """
    # Arrange: Create a pip file and registry configuration
    (tmp_path / "requirements.txt").touch()

    registry_rules = [
        {
            "registries": [
                {
                    "name": "github",
                    "type": "git",
                    "url": "https://github.com/",
                    "username": "svc-github-circleci-rc",
                    "password": "${{ secrets.REPO_ACCESS_TOKEN }}",
                }
            ]
        }
    ]
    create_config_file(tmp_path, registry_rules)

    # Act
    args = argparse.Namespace(
        repo_path=str(tmp_path),
        open_pull_requests_limit=1,
        main_branch="main",
        transitive_security=False,
    )
    generate.main(args)

    # Assert
    generated_config_path = tmp_path / ".github" / "dependabot.yml"
    assert generated_config_path.exists()
    with open(generated_config_path, "r") as f:
        config = yaml_loader.load(f)

    # Check that registries section exists
    assert "registries" in config
    assert "github" in config["registries"]

    github_registry = config["registries"]["github"]
    assert github_registry["type"] == "git"
    assert github_registry["url"] == "https://github.com/"
    assert github_registry["username"] == "svc-github-circleci-rc"
    assert github_registry["password"] == "${{ secrets.REPO_ACCESS_TOKEN }}"

    # Ensure 'name' is not included in the registry config (it's the key)
    assert "name" not in github_registry


def test_registry_configuration_multiple_registries(tmp_path: Path):
    """
    Tests that multiple registry configurations are properly handled.
    """
    # Arrange: Create a pip file and multiple registry configurations
    (tmp_path / "requirements.txt").touch()

    registry_rules = [
        {
            "registries": [
                {
                    "name": "github",
                    "type": "git",
                    "url": "https://github.com/",
                    "username": "github-user",
                    "password": "${{ secrets.GITHUB_TOKEN }}",
                },
                {
                    "name": "npm-registry",
                    "type": "npm-registry",
                    "url": "https://npm.pkg.github.com",
                    "token": "${{ secrets.NPM_TOKEN }}",
                },
            ]
        }
    ]
    create_config_file(tmp_path, registry_rules)

    # Act
    args = argparse.Namespace(
        repo_path=str(tmp_path),
        open_pull_requests_limit=1,
        main_branch="main",
        transitive_security=False,
    )
    generate.main(args)

    # Assert
    generated_config_path = tmp_path / ".github" / "dependabot.yml"
    assert generated_config_path.exists()
    with open(generated_config_path, "r") as f:
        config = yaml_loader.load(f)

    # Check that both registries exist
    assert "registries" in config
    assert "github" in config["registries"]
    assert "npm-registry" in config["registries"]

    # Check github registry
    github_registry = config["registries"]["github"]
    assert github_registry["type"] == "git"
    assert github_registry["url"] == "https://github.com/"
    assert github_registry["username"] == "github-user"
    assert github_registry["password"] == "${{ secrets.GITHUB_TOKEN }}"

    # Check npm registry
    npm_registry = config["registries"]["npm-registry"]
    assert npm_registry["type"] == "npm-registry"
    assert npm_registry["url"] == "https://npm.pkg.github.com"
    assert npm_registry["token"] == "${{ secrets.NPM_TOKEN }}"


def test_registry_configuration_missing_name(tmp_path: Path):
    """
    Tests that registry configurations without a name are skipped with a warning.
    """
    # Arrange: Create a pip file and registry configuration without name
    (tmp_path / "requirements.txt").touch()

    registry_rules = [
        {
            "registries": [
                {
                    "type": "git",
                    "url": "https://github.com/",
                    "username": "github-user",
                    "password": "${{ secrets.GITHUB_TOKEN }}",
                }
            ]
        }
    ]
    create_config_file(tmp_path, registry_rules)

    # Act
    args = argparse.Namespace(
        repo_path=str(tmp_path),
        open_pull_requests_limit=1,
        main_branch="main",
        transitive_security=False,
    )
    with structlog.testing.capture_logs() as captured_logs:
        generate.main(args)

    # Assert
    generated_config_path = tmp_path / ".github" / "dependabot.yml"
    assert generated_config_path.exists()
    with open(generated_config_path, "r") as f:
        config = yaml_loader.load(f)

    # Assert warning log message
    assert any(
        log["event"] == "Registry entry missing 'name' field, skipping"
        for log in captured_logs
    ), "Warning log for missing name field not found"

    # Check that no registries section exists (since the registry was skipped)
    assert "registries" not in config


def test_registry_configuration_missing_required_fields(tmp_path: Path):
    """
    Tests that registry configurations missing required fields are skipped with an error.
    """
    # Arrange: Create a pip file and registry configuration missing required fields
    (tmp_path / "requirements.txt").touch()

    registry_rules = [
        {
            "registries": [
                {
                    "name": "incomplete-registry",
                    "type": "git",
                    # Missing 'url' field
                    "username": "github-user",
                    "password": "${{ secrets.GITHUB_TOKEN }}",
                }
            ]
        }
    ]
    create_config_file(tmp_path, registry_rules)

    # Act
    args = argparse.Namespace(
        repo_path=str(tmp_path),
        open_pull_requests_limit=1,
        main_branch="main",
        transitive_security=False,
    )
    with structlog.testing.capture_logs() as captured_logs:
        generate.main(args)

    # Assert
    generated_config_path = tmp_path / ".github" / "dependabot.yml"
    assert generated_config_path.exists()
    with open(generated_config_path, "r") as f:
        config = yaml_loader.load(f)

    # Assert error log message
    assert any(
        log["event"] == "Registry missing required fields" for log in captured_logs
    ), "Error log for missing required fields not found"

    # Check that no registries section exists (since the registry was skipped)
    assert "registries" not in config


def test_registry_configuration_no_registries(tmp_path: Path):
    """
    Tests that when no registry configurations are provided, no registries section is added.
    """
    # Arrange: Create a pip file without registry configurations
    (tmp_path / "requirements.txt").touch()

    # Act
    args = argparse.Namespace(
        repo_path=str(tmp_path),
        open_pull_requests_limit=1,
        main_branch="main",
        transitive_security=False,
    )
    generate.main(args)

    # Assert
    generated_config_path = tmp_path / ".github" / "dependabot.yml"
    assert generated_config_path.exists()
    with open(generated_config_path, "r") as f:
        config = yaml_loader.load(f)

    # Check that no registries section exists
    assert "registries" not in config


def test_registry_configuration_docker_registry(tmp_path: Path):
    """
    Tests that Docker registry configurations work correctly.
    """
    # Arrange: Create a Dockerfile and Docker registry configuration
    (tmp_path / "Dockerfile").touch()

    registry_rules = [
        {
            "registries": [
                {
                    "name": "docker-hub",
                    "type": "docker-registry",
                    "url": "https://index.docker.io",
                    "username": "docker-user",
                    "password": "${{ secrets.DOCKER_PASSWORD }}",
                }
            ]
        }
    ]
    create_config_file(tmp_path, registry_rules)

    # Act
    args = argparse.Namespace(
        repo_path=str(tmp_path),
        open_pull_requests_limit=1,
        main_branch="main",
        transitive_security=False,
    )
    with structlog.testing.capture_logs() as captured_logs:
        generate.main(args)

    # Assert
    generated_config_path = tmp_path / ".github" / "dependabot.yml"
    assert generated_config_path.exists()
    with open(generated_config_path, "r") as f:
        config = yaml_loader.load(f)

    # Check that registries section exists with Docker registry
    assert "registries" in config
    assert "docker-hub" in config["registries"]

    docker_registry = config["registries"]["docker-hub"]
    assert docker_registry["type"] == "docker-registry"
    assert docker_registry["url"] == "https://index.docker.io"
    assert docker_registry["username"] == "docker-user"
    assert docker_registry["password"] == "${{ secrets.DOCKER_PASSWORD }}"

    # Assert log message for adding Docker registry
    assert any(
        log["event"] == "Added registry configuration"
        and log["name"] == "docker-hub"
        and log["type"] == "docker-registry"
        for log in captured_logs
    ), "Log for adding Docker registry configuration not found"


def test_ignore_directory_still_creates_security_updates(tmp_path: Path):
    """
    Tests that an ignore-directory rule prevents version updates
    but still creates security updates for managers in that directory.
    """
    # Arrange: Create bundler in a nested directory, ignore the parent directory
    gem_dir = tmp_path / "vendor" / "gems" / "mygem"
    gem_dir.mkdir(parents=True, exist_ok=True)
    (gem_dir / "Gemfile").touch()  # Bundler in /vendor/gems/mygem

    # Ignore /vendor/gems/ (which should cover /vendor/gems/mygem)
    ignore_rules = [{"ignore-directory": ["/vendor/gems/"]}]
    create_config_file(tmp_path, ignore_rules)

    # Act
    args = argparse.Namespace(
        repo_path=str(tmp_path),
        open_pull_requests_limit=1,  # Non-zero to attempt version updates
        main_branch="main",
        transitive_security=False,
    )
    generate.main(args)

    # Assert
    generated_config_path = tmp_path / ".github" / "dependabot.yml"
    assert generated_config_path.exists()
    with open(generated_config_path, "r") as f:
        config = yaml_loader.load(f)

    version_update_found = False
    security_update_found = False

    for update_entry in config.get("updates", []):
        if (
            update_entry.get("package-ecosystem") == "bundler"
            and update_entry.get("directory") == "/vendor/gems/mygem"
        ):
            if update_entry.get("open-pull-requests-limit", -1) > 0:
                version_update_found = True
            elif update_entry.get("open-pull-requests-limit", -1) == 0:
                security_update_found = True

    assert not version_update_found, (
        "Version update entry found for bundler in ignored directory /vendor/gems/mygem"
    )
    assert security_update_found, (
        "Security update entry NOT found for bundler in ignored directory /vendor/gems/mygem"
    )

    # Additionally, ensure only one entry (the security one) exists for this manager/dir
    bundler_entries = [
        e
        for e in config.get("updates", [])
        if e.get("package-ecosystem") == "bundler"
        and e.get("directory") == "/vendor/gems/mygem"
    ]
    assert len(bundler_entries) == 1, (
        "Expected exactly one entry (security) for bundler in /vendor/gems/mygem"
    )


def test_docker_detection(tmp_path: Path):
    """
    Tests that a Dockerfile in the root is detected and generates
    the correct docker entries with the specific weekly schedule.
    """
    # Arrange: Create a Dockerfile
    (tmp_path / "Dockerfile").touch()

    # Act
    args = argparse.Namespace(
        repo_path=str(tmp_path),
        open_pull_requests_limit=1,
        main_branch="main",
        transitive_security=False,
    )
    with structlog.testing.capture_logs() as captured_logs:
        generate.main(args)

    # Assert
    generated_config_path = tmp_path / ".github" / "dependabot.yml"
    assert generated_config_path.exists()
    with open(generated_config_path, "r") as f:
        config = yaml_loader.load(f)

    # Assert log messages
    assert any(
        log["event"] == "Detected package manager in directory"  # Corrected event name
        and log["manager"] == "docker"
        and log["directory"] == "/"
        for log in captured_logs
    ), "Log for docker detection in root not found"

    assert len(config["updates"]) == 2, "Expected 2 entries (version + security)"

    # Check version entry
    version_entry = config["updates"][0]
    assert version_entry["package-ecosystem"] == "docker"
    assert version_entry["directory"] == "/"
    assert version_entry["open-pull-requests-limit"] == 1
    assert version_entry["schedule"]["interval"] == "weekly"
    assert (
        version_entry["schedule"]["day"] == "wednesday"
    )  # Check specific docker schedule

    # Check security entry
    security_entry = config["updates"][1]
    assert security_entry["package-ecosystem"] == "docker"
    assert security_entry["directory"] == "/"
    assert security_entry["open-pull-requests-limit"] == 0
    assert security_entry["schedule"]["interval"] == "weekly"
    assert (
        security_entry["schedule"]["day"] == "wednesday"
    )  # Check specific docker schedule


def test_gomod_detection(tmp_path: Path):
    """
    Tests that a go.mod file in the root is detected and generates
    the correct gomod entries.
    """
    # Arrange: Create a go.mod file
    (tmp_path / "go.mod").touch()

    # Act
    args = argparse.Namespace(
        repo_path=str(tmp_path),
        open_pull_requests_limit=1,
        main_branch="main",
        transitive_security=False,
    )
    with structlog.testing.capture_logs() as captured_logs:
        generate.main(args)

    # Assert
    generated_config_path = tmp_path / ".github" / "dependabot.yml"
    assert generated_config_path.exists()
    with open(generated_config_path, "r") as f:
        config = yaml_loader.load(f)

    # Assert log messages
    assert any(
        log["event"] == "Detected package manager in directory"  # Corrected event name
        and log["manager"] == "gomod"
        and log["directory"] == "/"
        for log in captured_logs
    ), "Log for gomod detection in root not found"

    assert len(config["updates"]) == 2, "Expected 2 entries (version + security)"

    # Check version entry
    version_entry = config["updates"][0]
    assert version_entry["package-ecosystem"] == "gomod"
    assert version_entry["directory"] == "/"
    assert version_entry["open-pull-requests-limit"] == 1
    assert version_entry["schedule"]["interval"] == "weekly"  # Default schedule

    # Check security entry
    security_entry = config["updates"][1]
    assert security_entry["package-ecosystem"] == "gomod"
    assert security_entry["directory"] == "/"
    assert security_entry["open-pull-requests-limit"] == 0
    assert security_entry["schedule"]["interval"] == "weekly"  # Default schedule


def test_empty_repository(tmp_path: Path):
    """
    Tests that running on an empty repository produces a valid config
    with version 2 but an empty updates list.
    """
    # Arrange: An empty directory (tmp_path)

    # Act
    args = argparse.Namespace(
        repo_path=str(tmp_path),
        open_pull_requests_limit=1,
        main_branch="main",
        transitive_security=False,
    )
    # No specific logs are asserted in this test currently, so capture_logs is not needed.
    generate.main(args)

    # Assert
    generated_config_path = tmp_path / ".github" / "dependabot.yml"
    assert generated_config_path.exists()
    with open(generated_config_path, "r") as f:
        config = yaml_loader.load(f)

    # Assert log messages
    # Removed: log["event"] == "No package managers detected" as it's not explicitly logged.
    # The functional check is the empty updates list.

    assert config["version"] == 2
    assert "updates" in config
    assert isinstance(config["updates"], list)
    assert len(config["updates"]) == 0, "Expected empty updates list for empty repo"


def test_all_managers_ignored_by_directory(tmp_path: Path):
    """
    Tests that if the only detected manager is in an ignored directory,
    the updates list is empty.
    """
    # Arrange: Create pip file in backend/, ignore backend/
    backend_dir = tmp_path / "backend"
    backend_dir.mkdir()
    (backend_dir / "requirements.txt").touch()

    ignore_rules = [{"ignore-directory": ["/backend/"]}]
    create_config_file(tmp_path, ignore_rules)

    # Act
    args = argparse.Namespace(
        repo_path=str(tmp_path),
        open_pull_requests_limit=1,
        main_branch="main",
        transitive_security=False,
    )
    with structlog.testing.capture_logs() as captured_logs:
        generate.main(args)

    # Assert
    generated_config_path = tmp_path / ".github" / "dependabot.yml"
    assert generated_config_path.exists()
    with open(generated_config_path, "r") as f:
        config = yaml_loader.load(f)

    # Assert log messages
    assert any(
        log["event"] == "Skipping directory due to ignore rule"
        and log["directory"] == "/backend"
        and log["manager"] == "pip"  # This manager key is present in this specific log
        for log in captured_logs
    ), "Log for skipping backend directory not found"
    # Removed: log["event"] == "No eligible package managers found after applying ignores"
    # The functional check is the empty updates list.

    assert config["version"] == 2
    assert "updates" in config
    assert isinstance(config["updates"], list)
    # Security updates are still created for ignored directories
    assert len(config["updates"]) == 1, (
        "Expected 1 entry (security update) when all managers are in an ignored directory"
    )
    security_entry = config["updates"][0]
    assert security_entry["package-ecosystem"] == "pip"
    assert security_entry["directory"] == "/backend"
    assert security_entry["open-pull-requests-limit"] == 0
    assert "prodsec" in security_entry.get("groups", {})


def test_open_pr_limit_zero(tmp_path: Path):
    """
    Tests that setting open_pr_limit=0 results in only security update entries.
    """
    # Arrange: Create a pip file
    (tmp_path / "requirements.txt").touch()

    # Act: Run with open_pr_limit=0
    args = argparse.Namespace(
        repo_path=str(tmp_path),
        open_pull_requests_limit=0,  # Key change for this test
        main_branch="main",
        transitive_security=False,
    )
    with structlog.testing.capture_logs() as captured_logs:
        generate.main(args)

    # Assert
    generated_config_path = tmp_path / ".github" / "dependabot.yml"
    assert generated_config_path.exists()
    with open(generated_config_path, "r") as f:
        config = yaml_loader.load(f)

    # Assert log messages
    assert any(
        log["event"] == "Detected package manager in directory"  # Corrected event name
        and log["manager"] == "pip"
        and log["directory"] == "/"
        for log in captured_logs
    ), "Log for pip detection in root not found"
    # Check that version update was skipped due to open_pr_limit=0
    # This might be an implicit behavior (no entry created) or an explicit log.
    # For now, we rely on the config assertion.

    # Should only have ONE entry: the security update
    assert len(config["updates"]) == 1, "Expected only 1 entry (security update)"

    security_entry = config["updates"][0]
    assert security_entry["package-ecosystem"] == "pip"
    assert security_entry["directory"] == "/"
    assert security_entry["open-pull-requests-limit"] == 0
    assert "prodsec" in security_entry.get("groups", {})


def test_transitive_security_true(tmp_path: Path):
    """
    Tests that setting transitive_security=True sets the correct 'allow'
    value in the security update entry.
    """
    # Arrange: Create a pip file
    (tmp_path / "requirements.txt").touch()

    # Act: Run with transitive_security=True
    args = argparse.Namespace(
        repo_path=str(tmp_path),
        open_pull_requests_limit=1,
        main_branch="main",
        transitive_security=True,  # Key change for this test
    )
    with structlog.testing.capture_logs() as captured_logs:
        generate.main(args)

    # Assert
    generated_config_path = tmp_path / ".github" / "dependabot.yml"
    assert generated_config_path.exists()
    with open(generated_config_path, "r") as f:
        config = yaml_loader.load(f)

    # Assert log messages
    assert any(
        log["event"] == "Detected package manager in directory"  # Corrected event name
        and log["manager"] == "pip"
        and log["directory"] == "/"
        for log in captured_logs
    ), "Log for pip detection in root not found"

    # Should have two entries
    assert len(config["updates"]) == 2, "Expected 2 entries (version + security)"

    # Find the security entry
    security_entry = None
    for entry in config["updates"]:
        if entry["open-pull-requests-limit"] == 0:
            security_entry = entry
            break

    assert security_entry is not None, "Security update entry not found"
    assert security_entry["package-ecosystem"] == "pip"
    assert security_entry["directory"] == "/"
    assert "allow" in security_entry
    assert security_entry["allow"] == [
        {"dependency-type": "all"}
    ]  # Check for transitive
    assert "labels" in security_entry
    assert security_entry["labels"] == ["security-update", "dependencies"]


def test_multiple_directories(tmp_path: Path):
    """
    Tests detection of managers in different directories (root and sub).
    """
    # Arrange: Create pip in root and npm in frontend/
    (tmp_path / "requirements.txt").touch()
    frontend_dir = tmp_path / "frontend"
    frontend_dir.mkdir()
    (frontend_dir / "package.json").touch()

    # Act
    args = argparse.Namespace(
        repo_path=str(tmp_path),
        open_pull_requests_limit=1,
        main_branch="main",
        transitive_security=False,
    )
    with structlog.testing.capture_logs() as captured_logs:
        generate.main(args)

    # Assert
    generated_config_path = tmp_path / ".github" / "dependabot.yml"
    assert generated_config_path.exists()
    with open(generated_config_path, "r") as f:
        config = yaml_loader.load(f)  # Use yaml_loader

    # Assert log messages
    assert any(
        log["event"] == "Detected package manager in directory"  # Corrected event name
        and log["manager"] == "pip"
        and log["directory"] == "/"
        for log in captured_logs
    ), "Log for pip detection in root not found"
    assert any(
        log["event"] == "Detected package manager in directory"  # Corrected event name
        and log["manager"] == "npm"
        and log["directory"] == "/frontend"
        for log in captured_logs
    ), "Log for npm detection in /frontend not found"

    assert len(config["updates"]) == 4, (
        "Expected 4 entries (pip + npm, version + security each)"
    )

    # Check entries (order might vary, so check ecosystems and directories)
    found_pip_root = False
    found_npm_frontend = False
    for entry in config["updates"]:
        if entry["package-ecosystem"] == "pip" and entry["directory"] == "/":
            found_pip_root = True
        elif entry["package-ecosystem"] == "npm" and entry["directory"] == "/frontend":
            found_npm_frontend = True

    assert found_pip_root, "Pip entry for root directory not found"
    assert found_npm_frontend, "Npm entry for /frontend directory not found"


def test_no_duplicate_entries(tmp_path: Path):
    """
    Tests that multiple files for the same manager in one directory
    do not create duplicate entries (e.g., multiple workflow files).
    """
    # Arrange: Create two workflow files
    workflows_dir = tmp_path / ".github" / "workflows"
    workflows_dir.mkdir(parents=True)
    (workflows_dir / "ci.yml").touch()
    (workflows_dir / "deploy.yml").touch()

    # Act
    args = argparse.Namespace(
        repo_path=str(tmp_path),
        open_pull_requests_limit=1,
        main_branch="main",
        transitive_security=False,
    )
    with structlog.testing.capture_logs() as captured_logs:
        generate.main(args)

    # Assert
    generated_config_path = tmp_path / ".github" / "dependabot.yml"
    assert generated_config_path.exists()
    with open(generated_config_path, "r") as f:
        config = yaml_loader.load(f)  # Use yaml_loader

    # Assert log messages
    assert any(
        log["event"] == "Detected package manager in directory"  # Corrected event name
        and log["manager"] == "github-actions"
        and log["directory"] == "/.github/workflows"
        for log in captured_logs
    ), "Log for github-actions detection not found"
    # Check that it's logged only once for the manager, not per file
    detected_gha_logs = [
        log
        for log in captured_logs
        if log["event"] == "Detected package manager in directory"
        and log["manager"] == "github-actions"  # Corrected event name
    ]
    # The log "Detected package manager in directory" is emitted for each file found.
    # Since two workflow files (ci.yml, deploy.yml) are created, we expect two such log entries.
    assert len(detected_gha_logs) == 2, (
        "github-actions manager should be detected for each file (2 files)"
    )

    assert len(config["updates"]) == 2, (
        "Expected only 2 entries for github-actions (version + security)"
    )

    # Check entries are for github-actions
    assert config["updates"][0]["package-ecosystem"] == "github-actions"
    assert config["updates"][0]["directory"] == "/.github/workflows"
    assert config["updates"][1]["package-ecosystem"] == "github-actions"
    assert config["updates"][1]["directory"] == "/.github/workflows"


def test_ignore_directory(tmp_path: Path):
    """
    Tests that the ignore-directory rule prevents entries from being created
    for the specified directory.
    """
    # Arrange: Create pip in root and backend/, ignore backend/
    (tmp_path / "requirements.txt").touch()  # Pip in root
    backend_dir = tmp_path / "backend"
    backend_dir.mkdir()
    (backend_dir / "requirements.txt").touch()  # Pip in backend

    ignore_rules = [{"ignore-directory": ["/backend/"]}]
    create_config_file(tmp_path, ignore_rules)

    # Act
    args = argparse.Namespace(
        repo_path=str(tmp_path),
        open_pull_requests_limit=1,
        main_branch="main",
        transitive_security=False,
    )
    with structlog.testing.capture_logs() as captured_logs:
        generate.main(args)

    # Assert
    generated_config_path = tmp_path / ".github" / "dependabot.yml"
    assert generated_config_path.exists()
    with open(generated_config_path, "r") as f:
        config = yaml_loader.load(f)

    # Should have entries for root pip (version + security) and a security entry for backend pip
    assert len(config["updates"]) == 3, "Expected 3 entries: root (v+s) and backend (s)"

    found_root_version = False
    found_root_security = False
    found_backend_security = False
    found_backend_version = False

    for entry in config["updates"]:
        if entry["directory"] == "/":
            if entry["open-pull-requests-limit"] > 0:
                assert entry["package-ecosystem"] == "pip"
                found_root_version = True
            elif entry["open-pull-requests-limit"] == 0:
                assert entry["package-ecosystem"] == "pip"
                found_root_security = True
        elif entry["directory"] == "/backend":
            if entry["open-pull-requests-limit"] == 0:  # Only security for backend
                assert entry["package-ecosystem"] == "pip"
                found_backend_security = True
            elif entry["open-pull-requests-limit"] > 0:
                found_backend_version = True

    assert found_root_version, "Root pip version update not found"
    assert found_root_security, "Root pip security update not found"
    assert found_backend_security, "Backend pip security update not found"
    assert not found_backend_version, (
        "Backend pip version update was found but should be ignored"
    )

    # Assert specific log message for skipping backend
    found_log = False
    for log_entry in captured_logs:
        if (
            log_entry["event"] == "Skipping directory due to ignore rule"
            and log_entry["directory"] == "/backend"
            and log_entry["manager"] == "pip"
            and log_entry["rule"] == "/backend/"
        ):
            found_log = True
            break
    assert found_log, "Expected log message for skipping ignored directory not found"


def test_ignore_dependency(tmp_path: Path):
    """
    Tests that the ignore-dependency rule adds the correct ignore block
    to the version update entry.
    """
    # Arrange: Create pip in root, ignore 'requests' package
    (tmp_path / "requirements.txt").touch()

    ignore_rules = [
        {
            "ignore-dependency": [
                {
                    "package-ecosystem": "pip",
                    "dependency-name": "requests",
                    "update-types": ["version-update:semver-major"],
                }
            ]
        }
    ]
    create_config_file(tmp_path, ignore_rules)

    # Act
    args = argparse.Namespace(
        repo_path=str(tmp_path),
        open_pull_requests_limit=1,
        main_branch="main",
        transitive_security=False,
    )
    generate.main(args)

    # Assert
    generated_config_path = tmp_path / ".github" / "dependabot.yml"
    assert generated_config_path.exists()
    with open(generated_config_path, "r") as f:
        config = yaml_loader.load(f)

    assert len(config["updates"]) == 2, "Expected 2 entries for root pip"

    # Find the version update entry (should be first if only one manager)
    version_entry = None
    security_entry = None
    for entry in config["updates"]:
        if entry["open-pull-requests-limit"] == 1:
            version_entry = entry
        elif entry["open-pull-requests-limit"] == 0:
            security_entry = entry

    assert version_entry is not None, "Version update entry not found"
    assert security_entry is not None, "Security update entry not found"

    # Check ignore block in version entry
    assert "ignore" in version_entry
    assert isinstance(version_entry["ignore"], list)
    assert len(version_entry["ignore"]) == 1
    assert version_entry["ignore"][0]["dependency-name"] == "requests"
    assert version_entry["ignore"][0]["update-types"] == ["version-update:semver-major"]

    # Check ignore block NOT in security entry
    assert "ignore" not in security_entry


def test_ignore_version_updates_for_files_specific(tmp_path: Path):
    """
    Tests that ignore-version-updates-for-files (specific filename)
    prevents the version update entry but keeps the security entry.
    """
    # Arrange: Create requirements.txt and requirements_prod.txt, ignore _prod
    (tmp_path / "requirements.txt").touch()
    (
        tmp_path / "requirements_prod.txt"
    ).touch()  # This should be ignored for version updates

    ignore_rules = [{"ignore-version-updates-for-files": ["requirements_prod.txt"]}]
    create_config_file(tmp_path, ignore_rules)

    # Act
    args = argparse.Namespace(
        repo_path=str(tmp_path),
        open_pull_requests_limit=1,
        main_branch="main",
        transitive_security=False,
    )
    with structlog.testing.capture_logs() as captured_logs:
        generate.main(args)

    # Assert
    generated_config_path = tmp_path / ".github" / "dependabot.yml"
    assert generated_config_path.exists()
    with open(generated_config_path, "r") as f:
        config = yaml_loader.load(f)

    # Assert log messages
    assert any(
        log["event"]
        == "Skipping version updates for manager due to file pattern ignore"
        and log["manager"] == "pip"
        and log["directory"] == "/"
        and log["file_pattern"] == "requirements_prod.txt"
        for log in captured_logs
    ), "Log for skipping version updates for requirements_prod.txt not found"

    # Should only have ONE entry: the security update
    assert len(config["updates"]) == 1, (
        f"Expected only 1 entry (security update), got {len(config['updates'])}"
    )

    security_entry = config["updates"][0]
    assert security_entry["package-ecosystem"] == "pip"
    assert security_entry["directory"] == "/"
    assert (
        security_entry["open-pull-requests-limit"] == 0
    )  # Security updates have limit 0
    assert "prodsec" in security_entry.get("groups", {})


def test_ignore_version_updates_for_files_glob(tmp_path: Path):
    """
    Tests that ignore-version-updates-for-files (glob pattern)
    prevents the version update entry but keeps the security entry.
    """
    # Arrange: Create requirements.txt and requirements_dev.txt, ignore *_dev.txt
    (tmp_path / "requirements.txt").touch()
    (
        tmp_path / "requirements_dev.txt"
    ).touch()  # This should be ignored for version updates

    ignore_rules = [{"ignore-version-updates-for-files": ["*_dev.txt"]}]
    create_config_file(tmp_path, ignore_rules)

    # Act
    args = argparse.Namespace(
        repo_path=str(tmp_path),
        open_pull_requests_limit=1,
        main_branch="main",
        transitive_security=False,
    )
    with structlog.testing.capture_logs() as captured_logs:
        generate.main(args)

    # Assert
    generated_config_path = tmp_path / ".github" / "dependabot.yml"
    assert generated_config_path.exists()
    with open(generated_config_path, "r") as f:
        config = yaml_loader.load(f)

    # Assert log messages
    assert any(
        log["event"]
        == "Skipping version updates for manager due to file pattern ignore"
        and log["manager"] == "pip"
        and log["directory"] == "/"
        and log["file_pattern"] == "*_dev.txt"
        for log in captured_logs
    ), "Log for skipping version updates for *_dev.txt not found"

    # Similar to the specific file test, only the security entry should remain.
    assert len(config["updates"]) == 1, (
        f"Expected only 1 entry (security update), got {len(config['updates'])}"
    )

    security_entry = config["updates"][0]
    assert security_entry["package-ecosystem"] == "pip"
    assert security_entry["directory"] == "/"
    assert security_entry["open-pull-requests-limit"] == 0
    assert "prodsec" in security_entry.get("groups", {})


def test_registry_assignment_to_specific_ecosystems(tmp_path: Path):
    """
    Test Phase 3: Registry assignment to specific package ecosystems.
    """
    # Arrange: Create files for multiple package managers
    (tmp_path / "requirements.txt").write_text("requests==2.25.1\n")
    (tmp_path / "package.json").write_text('{"dependencies": {"lodash": "^4.17.21"}}\n')
    (tmp_path / "Dockerfile").write_text("FROM python:3.9\n")

    # Create configurator settings with ecosystem-specific registries
    registry_rules = [
        {
            "registries": [
                {
                    "name": "pypi-mirror",
                    "type": "python-index",
                    "url": "https://pypi.example.com/simple",
                    "username": "pypi-user",
                    "password": "${{ secrets.PYPI_PASSWORD }}",
                    "applies-to": ["pip"],
                },
                {
                    "name": "npm-registry",
                    "type": "npm-registry",
                    "url": "https://npm.example.com",
                    "token": "${{ secrets.NPM_TOKEN }}",
                    "applies-to": ["npm"],
                },
                {
                    "name": "docker-hub",
                    "type": "docker-registry",
                    "url": "https://index.docker.io",
                    "username": "docker-user",
                    "password": "${{ secrets.DOCKER_PASSWORD }}",
                    "applies-to": ["docker"],
                },
                {
                    "name": "universal-registry",
                    "type": "git",
                    "url": "https://github.com",
                    "username": "git-user",
                    "password": "${{ secrets.GIT_TOKEN }}",
                },
            ]
        }
    ]
    create_config_file(tmp_path, registry_rules)

    # Act
    args = argparse.Namespace(
        repo_path=str(tmp_path),
        open_pull_requests_limit=5,
        main_branch="main",
        transitive_security=False,
    )
    with structlog.testing.capture_logs() as captured_logs:
        generate.main(args)

    # Assert
    generated_config_path = tmp_path / ".github" / "dependabot.yml"
    assert generated_config_path.exists()
    with open(generated_config_path, "r") as f:
        config = yaml_loader.load(f)

    # Verify all registries are present
    assert "registries" in config
    assert "pypi-mirror" in config["registries"]
    assert "npm-registry" in config["registries"]
    assert "docker-hub" in config["registries"]
    assert "universal-registry" in config["registries"]

    # Verify pip updates have correct registries
    pip_updates = [u for u in config["updates"] if u["package-ecosystem"] == "pip"]
    assert len(pip_updates) == 2  # version and security updates
    for update in pip_updates:
        assert "registries" in update
        # Should have pypi-mirror (specific to pip) and universal-registry (applies to all)
        assert "pypi-mirror" in update["registries"]
        assert "universal-registry" in update["registries"]
        assert "npm-registry" not in update["registries"]
        assert "docker-hub" not in update["registries"]

    # Verify npm updates have correct registries
    npm_updates = [u for u in config["updates"] if u["package-ecosystem"] == "npm"]
    assert len(npm_updates) == 2  # version and security updates
    for update in npm_updates:
        assert "registries" in update
        # Should have npm-registry (specific to npm) and universal-registry (applies to all)
        assert "npm-registry" in update["registries"]
        assert "universal-registry" in update["registries"]
        assert "pypi-mirror" not in update["registries"]
        assert "docker-hub" not in update["registries"]

    # Verify docker updates have correct registries
    docker_updates = [
        u for u in config["updates"] if u["package-ecosystem"] == "docker"
    ]
    assert len(docker_updates) == 2  # version and security updates
    for update in docker_updates:
        assert "registries" in update
        # Should have docker-hub (specific to docker) and universal-registry (applies to all)
        assert "docker-hub" in update["registries"]
        assert "universal-registry" in update["registries"]
        assert "pypi-mirror" not in update["registries"]
        assert "npm-registry" not in update["registries"]

    # Verify log messages for registry assignment
    assert any(
        log["event"] == "Added registries to version update entry"
        and log["manager"] == "pip"
        and "pypi-mirror" in log["registries"]
        and "universal-registry" in log["registries"]
        for log in captured_logs
    ), "Log for adding registries to pip version update not found"

    assert any(
        log["event"] == "Added registries to security update entry"
        and log["manager"] == "npm"
        and "npm-registry" in log["registries"]
        and "universal-registry" in log["registries"]
        for log in captured_logs
    ), "Log for adding registries to npm security update not found"


def test_registry_assignment_universal_only(tmp_path: Path):
    """
    Test registry assignment when only universal registries are configured.
    """
    # Arrange: Create files for multiple package managers
    (tmp_path / "requirements.txt").write_text("requests==2.25.1\n")
    (tmp_path / "package.json").write_text('{"dependencies": {"lodash": "^4.17.21"}}\n')

    # Create configurator settings with only universal registries (no applies-to)
    registry_rules = [
        {
            "registries": [
                {
                    "name": "universal-git",
                    "type": "git",
                    "url": "https://github.com",
                    "username": "git-user",
                    "password": "${{ secrets.GIT_TOKEN }}",
                },
                {
                    "name": "universal-proxy",
                    "type": "git",
                    "url": "https://proxy.example.com",
                    "username": "proxy-user",
                    "password": "${{ secrets.PROXY_TOKEN }}",
                },
            ]
        }
    ]
    create_config_file(tmp_path, registry_rules)

    # Act
    args = argparse.Namespace(
        repo_path=str(tmp_path),
        open_pull_requests_limit=5,
        main_branch="main",
        transitive_security=False,
    )
    generate.main(args)

    # Assert
    generated_config_path = tmp_path / ".github" / "dependabot.yml"
    assert generated_config_path.exists()
    with open(generated_config_path, "r") as f:
        config = yaml_loader.load(f)

    # Verify all updates have both universal registries
    for update in config["updates"]:
        assert "registries" in update
        assert "universal-git" in update["registries"]
        assert "universal-proxy" in update["registries"]
        assert len(update["registries"]) == 2


def test_registry_assignment_no_matching_ecosystems(tmp_path: Path):
    """
    Test registry assignment when registries don't match any detected ecosystems.
    """
    # Arrange: Create pip file but configure only npm registry
    (tmp_path / "requirements.txt").write_text("requests==2.25.1\n")

    registry_rules = [
        {
            "registries": [
                {
                    "name": "npm-only",
                    "type": "npm-registry",
                    "url": "https://npm.example.com",
                    "token": "${{ secrets.NPM_TOKEN }}",
                    "applies-to": ["npm"],
                }
            ]
        }
    ]
    create_config_file(tmp_path, registry_rules)

    # Act
    args = argparse.Namespace(
        repo_path=str(tmp_path),
        open_pull_requests_limit=5,
        main_branch="main",
        transitive_security=False,
    )
    generate.main(args)

    # Assert
    generated_config_path = tmp_path / ".github" / "dependabot.yml"
    assert generated_config_path.exists()
    with open(generated_config_path, "r") as f:
        config = yaml_loader.load(f)

    # Verify pip updates don't have any registries (since npm-only doesn't apply to pip)
    pip_updates = [u for u in config["updates"] if u["package-ecosystem"] == "pip"]
    assert len(pip_updates) == 2  # version and security updates
    for update in pip_updates:
        assert "registries" not in update  # No registries should be assigned


def test_registry_assignment_mixed_specific_and_universal(tmp_path: Path):
    """
    Test registry assignment with a mix of ecosystem-specific and universal registries.
    """
    # Arrange: Create pip file
    (tmp_path / "requirements.txt").write_text("requests==2.25.1\n")

    registry_rules = [
        {
            "registries": [
                {
                    "name": "pip-specific",
                    "type": "python-index",
                    "url": "https://pypi.example.com/simple",
                    "username": "pypi-user",
                    "password": "${{ secrets.PYPI_PASSWORD }}",
                    "applies-to": ["pip"],
                },
                {
                    "name": "universal-one",
                    "type": "git",
                    "url": "https://github.com",
                    "username": "git-user",
                    "password": "${{ secrets.GIT_TOKEN }}",
                },
                {
                    "name": "npm-specific",
                    "type": "npm-registry",
                    "url": "https://npm.example.com",
                    "token": "${{ secrets.NPM_TOKEN }}",
                    "applies-to": ["npm"],
                },
                {
                    "name": "universal-two",
                    "type": "git",
                    "url": "https://gitlab.com",
                    "username": "gitlab-user",
                    "password": "${{ secrets.GITLAB_TOKEN }}",
                },
            ]
        }
    ]
    create_config_file(tmp_path, registry_rules)

    # Act
    args = argparse.Namespace(
        repo_path=str(tmp_path),
        open_pull_requests_limit=5,
        main_branch="main",
        transitive_security=False,
    )
    generate.main(args)

    # Assert
    generated_config_path = tmp_path / ".github" / "dependabot.yml"
    assert generated_config_path.exists()
    with open(generated_config_path, "r") as f:
        config = yaml_loader.load(f)

    # Verify pip updates have pip-specific and both universal registries
    pip_updates = [u for u in config["updates"] if u["package-ecosystem"] == "pip"]
    assert len(pip_updates) == 2  # version and security updates
    for update in pip_updates:
        assert "registries" in update
        assert "pip-specific" in update["registries"]
        assert "universal-one" in update["registries"]
        assert "universal-two" in update["registries"]
        assert "npm-specific" not in update["registries"]
        assert len(update["registries"]) == 3
