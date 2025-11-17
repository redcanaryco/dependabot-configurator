#!/usr/bin/env python3
import argparse
import copy
import fnmatch
import glob
import os
from typing import Any

import structlog
from ruamel.yaml import YAML
from ruamel.yaml.comments import CommentedMap, CommentedSeq
from ruamel.yaml.scalarstring import DoubleQuotedScalarString, ScalarString

PACKAGE_MANAGERS: dict[str, list[str]] = {
    "bundler": ["**/Gemfile", "**/Gemfile.lock"],
    "cargo": ["**/Cargo.toml", "**/Cargo.lock"],
    "composer": ["**/composer.json", "**/composer.lock"],
    "docker": ["**/Dockerfile"],
    "elm": ["**/elm.json"],
    "github-actions": [".github/workflows/*.yml", ".github/workflows/*.yaml"],
    "gomod": ["**/go.mod", "**/go.sum"],
    "gradle": ["**/build.gradle", "**/build.gradle.kts"],
    "maven": ["**/pom.xml"],
    "npm": ["**/package.json", "**/package-lock.json", "**/yarn.lock"],
    "nuget": ["**/*.csproj", "**/packages.config"],
    "pip": [
        "**/requirements*.txt",  # Broadened pattern to catch requirements_prod.txt etc.
        "**/pyproject.toml",
        "**/poetry.lock",
        "**/Pipfile",
        "**/Pipfile.lock",
    ],
    "pub": ["**/pubspec.yaml", "**/pubspec.lock"],
    "swift": ["**/Package.swift"],
    "terraform": ["**/.terraform.lock.hcl"],
}

# Configure structlog for basic console output suitable for GitHub Actions
structlog.configure(
    processors=[
        structlog.stdlib.add_logger_name,
        structlog.stdlib.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.dict_tracebacks,
        structlog.processors.JSONRenderer(sort_keys=True),
    ],
    logger_factory=structlog.stdlib.LoggerFactory(),
    wrapper_class=structlog.stdlib.BoundLogger,
    cache_logger_on_first_use=True,
)
log = structlog.get_logger()


def str_to_bool(value: str | bool) -> bool:
    """
    Convert a string to a boolean.
    Necessary because of Argparse designs.
    https://stackoverflow.com/questions/15008758/parsing-boolean-values-with-argparse
    """
    if isinstance(value, bool):
        return value
    if isinstance(value, str) and value.lower() in {"true", "yes", "1"}:
        return True
    elif isinstance(value, str) and value.lower() in {"false", "no", "0"}:
        return False
    else:
        raise argparse.ArgumentTypeError(f"Invalid boolean value: {value}")


def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate dependabot.yaml")
    parser.add_argument(
        "--open-pull-requests-limit",
        type=int,
        required=True,
        help="Open pull requests limit",
    )
    parser.add_argument(
        "--main-branch",
        type=str,
        required=True,
        help="Name of the main branch",
    )
    parser.add_argument(
        "--repo-path",
        type=str,
        required=False,
        help="Path to scan to get caller repo correct",
        default="./",
    )
    parser.add_argument(
        "--transitive-security",
        type=str_to_bool,
        required=False,
        help="Whether to look for transitive dependencies for security updates",
        default=False,
    )
    return parser.parse_args()


def matches_ignore_pattern(filename: str, patterns: list[str]) -> bool:
    """
    Check if a filename matches any glob pattern in a list.

    Args:
        filename: The filename to check against patterns
        patterns: List of glob patterns to match against

    Returns:
        True if filename matches any pattern, False otherwise
    """
    for pattern in patterns:
        if fnmatch.fnmatch(filename, pattern):
            return True
    return False


def initialize_yaml(safe=True) -> YAML:
    yaml = YAML(typ="safe" if safe else None)
    yaml.default_flow_style = False
    yaml.indent(mapping=2, sequence=4, offset=2)
    yaml.width = (
        120  # Increased from 80 to prevent breaking GitHub Actions template syntax
    )
    return yaml


def load_configurator_settings(repo_path: str) -> dict[str, Any]:
    """
    Load configurator settings from `.configurator_settings.yml` if it exists.
    Returns a dictionary with ignore rules, registries, custom files, and other settings.

    Args:
        repo_path: Path to the repository root

    Returns:
        Dictionary containing dependencies, directories, file patterns, registries, and custom files
    """
    settings_file = f"{repo_path}.github/.configurator_settings.yml"
    yaml = initialize_yaml(safe=True)  # Explicitly use safe loading
    settings: dict[str, Any] = {
        "dependencies": [],
        "directories": [],
        "file_patterns": [],
        "registries": [],
        "custom_files": [],
    }

    if os.path.exists(settings_file):
        log.info("Loading configurator settings", file=settings_file)
        with open(settings_file, "r") as f:
            settings_entries: list[dict[str, Any]] | None = yaml.load(f) or []

            if settings_entries:
                for entry in settings_entries:
                    if "ignore-dependency" in entry:
                        settings["dependencies"].extend(entry["ignore-dependency"])
                    elif "ignore-directory" in entry:
                        settings["directories"].extend(entry["ignore-directory"])
                    elif "ignore-version-updates-for-files" in entry:
                        settings["file_patterns"].extend(
                            entry["ignore-version-updates-for-files"]
                        )
                    elif "registries" in entry:
                        settings["registries"].extend(entry["registries"])
                    elif "custom-files" in entry:
                        settings["custom_files"].extend(entry["custom-files"])

    if not any(settings.values()):
        log.info("No configurator settings found", file=settings_file)
    else:
        log.info(
            "Configurator settings loaded",
            file=settings_file,
            count_dependencies=len(settings["dependencies"]),
            count_directories=len(settings["directories"]),
            count_file_patterns=len(settings["file_patterns"]),
            count_registries=len(settings["registries"]),
            count_custom_files=len(settings["custom_files"]),
        )
    return settings


def recursive_delete_comment_attribs(d: Any) -> None:
    """
    Recursively delete comment attributes from a dictionary or list.
    """
    if isinstance(d, dict):
        for k, v in d.items():
            recursive_delete_comment_attribs(k)
            recursive_delete_comment_attribs(v)
    elif isinstance(d, list):
        for elem in d:
            recursive_delete_comment_attribs(elem)
    try:
        # Only handle ScalarString instances to remove comment attributes if present
        if isinstance(d, ScalarString):
            delattr(d, "comment")
    except AttributeError:
        pass


def get_directory_managers(
    repo_path: str, package_managers: dict[str, list[str]]
) -> dict[str, list[tuple[str, str]]]:
    """
    Get the package managers and their specific manifest files for each directory.
    Returns a dictionary mapping directory paths to a list of (manager, filename) tuples.

    Args:
        repo_path: Path to the repository root
        package_managers: Dictionary mapping package manager names to file patterns

    Returns:
        Dictionary mapping directory paths to list of (manager, filename) tuples
    """
    directory_managers: dict[str, list[tuple[str, str]]] = {}
    for manager, patterns in package_managers.items():
        for pattern in patterns:
            matches = glob.glob(repo_path + pattern, recursive=True)
            for match in matches:
                if not os.path.isfile(match):
                    continue
                dir_path = os.path.relpath(os.path.dirname(match), repo_path)
                dir_path = os.path.normpath(dir_path)
                dir_path = (
                    "/" if dir_path == "." else "/" + dir_path.replace(os.path.sep, "/")
                )
                # Store the manager and the specific filename found
                manager_file_tuple = (manager, os.path.basename(match))
                directory_managers.setdefault(dir_path, []).append(manager_file_tuple)
                log.debug(
                    "Detected package manager in directory",
                    manager=manager,
                    directory=dir_path,
                    file=os.path.basename(match),
                )
    return directory_managers


def add_custom_files_to_directory_managers(
    repo_path: str,
    custom_files: list[dict[str, str]],
    directory_managers: dict[str, list[tuple[str, str]]],
) -> None:
    """
    Process custom files from configuration and add them to the directory_managers structure.

    Args:
        repo_path: Path to the repository root
        custom_files: List of custom file configurations with path and manager
        directory_managers: Dictionary mapping directory paths to list of (manager, filename) tuples

    Returns:
        None - the directory_managers dict is modified in place
    """
    if not custom_files:
        return

    log.info("Processing custom file specifications", count=len(custom_files))

    valid_managers = set(PACKAGE_MANAGERS.keys())

    for custom_file in custom_files:
        # Validate required fields
        if "path" not in custom_file or "manager" not in custom_file:
            log.error(
                "Custom file entry missing required fields",
                entry=custom_file,
                required=["path", "manager"],
            )
            continue

        file_path = custom_file["path"]
        manager = custom_file["manager"]

        # Validate manager type
        if manager not in valid_managers:
            log.error(
                "Invalid package manager specified in custom file",
                manager=manager,
                path=file_path,
                valid_managers=list(valid_managers),
            )
            continue

        # Check if file exists
        full_path = os.path.join(repo_path, file_path.lstrip("/"))
        if not os.path.isfile(full_path):
            log.warning(
                "Custom file not found",
                path=file_path,
                full_path=full_path,
                manager=manager,
            )
            continue

        # Normalize directory path
        dir_path = os.path.relpath(os.path.dirname(full_path), repo_path)
        dir_path = os.path.normpath(dir_path)
        dir_path = "/" if dir_path == "." else "/" + dir_path.replace(os.path.sep, "/")

        # Store the manager and filename
        filename = os.path.basename(full_path)
        manager_file_tuple = (manager, filename)
        directory_managers.setdefault(dir_path, []).append(manager_file_tuple)

        log.info(
            "Added custom file to directory managers",
            manager=manager,
            directory=dir_path,
            file=filename,
        )


def create_dependabot_update_entry(
    manager: str,
    dir_path: str,
    schedule: dict[str, str],
    open_pr_limit: int,
    main_branch: str,
    ignore_directories: list[str],
    registry_map: dict[str, dict[str, Any]] | None = None,
) -> CommentedMap | None:
    """
    Create an update entry for the dependabot config if the directory is not in ignore_directories.

    Args:
        manager: Package manager name (e.g., 'pip', 'npm')
        dir_path: Directory path for the update entry
        schedule: Schedule configuration dictionary
        open_pr_limit: Maximum number of open pull requests
        main_branch: Name of the main branch
        ignore_directories: List of directories to ignore

    Returns:
        CommentedMap with update configuration, or None if directory should be ignored
    """
    # Skip creating entry if the directory path matches any ignore-directory paths
    normalized_dir_path = dir_path.strip("/")  # e.g., "backend" or ".github/workflows"
    for ignored_dir in ignore_directories:
        normalized_ignored_dir = ignored_dir.strip(
            "/"
        )  # e.g., "backend" or ".github/workflows"
        # Check for exact match or if dir_path is a subdirectory of ignored_dir
        if (
            normalized_dir_path == normalized_ignored_dir
            or normalized_dir_path.startswith(normalized_ignored_dir + "/")
        ):
            log.info(
                "Skipping directory due to ignore rule",
                directory=dir_path,
                manager=manager,
                rule=ignored_dir,
            )
            return None  # Return None if this directory should be ignored

    # Create the entry if directory is not ignored
    entry = CommentedMap(
        {
            "package-ecosystem": manager,
            "directory": dir_path,
            "schedule": schedule,
            "allow": [{"dependency-type": "direct"}],
            "open-pull-requests-limit": open_pr_limit,
            "groups": {
                f"{manager.replace('-', '_')}_updates": {
                    "applies-to": "version-updates",
                    "update-types": ["minor", "patch"],
                }
            },
            "target-branch": main_branch,
            "labels": ["version-update", "dependencies"],
        }
    )

    # Add registries if any apply to this package ecosystem
    if registry_map:
        applicable_registries = []
        for registry_name, registry_info in registry_map.items():
            applies_to = registry_info.get("applies-to", [])
            # If applies-to is empty, registry applies to all ecosystems
            # If applies-to contains this manager, registry applies
            if not applies_to or manager in applies_to:
                applicable_registries.append(registry_name)
                log.debug(
                    "Registry applies to update entry",
                    registry=registry_name,
                    manager=manager,
                    directory=dir_path,
                    applies_to=applies_to,
                )

        if applicable_registries:
            entry["registries"] = CommentedSeq(applicable_registries)
            log.info(
                "Added registries to version update entry",
                manager=manager,
                directory=dir_path,
                registries=applicable_registries,
            )

    return entry


def create_security_update_entry(
    manager: str,
    dir_path: str,
    schedule: dict[str, str],
    transitive_security: bool,
    registry_map: dict[str, dict[str, Any]] | None = None,
) -> CommentedMap:
    """
    Create a security update entry for the dependabot config.

    Args:
        manager: Package manager name (e.g., 'pip', 'npm')
        dir_path: Directory path for the update entry
        schedule: Schedule configuration dictionary
        transitive_security: Whether to enable transitive security updates

    Returns:
        CommentedMap with security update configuration
    """
    prodsec_group = {
        "applies-to": "security-updates",
        "update-types": ["minor", "patch"],
    }

    # Modify settings for transitive dependencies.
    allow_entry: dict[str, str] = (
        {"dependency-type": "all"}
        if transitive_security
        else {"dependency-type": "direct"}
    )

    entry = CommentedMap(
        {
            "package-ecosystem": manager,
            "directory": dir_path,
            "schedule": schedule,
            "allow": [allow_entry],
            "open-pull-requests-limit": 0,
            "labels": ["security-update", "dependencies"],
            "groups": {
                "prodsec": prodsec_group,
            },
        }
    )

    # Add registries if any apply to this package ecosystem
    if registry_map:
        applicable_registries = []
        for registry_name, registry_info in registry_map.items():
            applies_to = registry_info.get("applies-to", [])
            # If applies-to is empty, registry applies to all ecosystems
            # If applies-to contains this manager, registry applies
            if not applies_to or manager in applies_to:
                applicable_registries.append(registry_name)
                log.debug(
                    "Registry applies to security update entry",
                    registry=registry_name,
                    manager=manager,
                    directory=dir_path,
                    applies_to=applies_to,
                )

        if applicable_registries:
            entry["registries"] = CommentedSeq(applicable_registries)
            log.info(
                "Added registries to security update entry",
                manager=manager,
                directory=dir_path,
                registries=applicable_registries,
            )

    return entry


def add_ignores(
    updates: CommentedSeq, ignore_entries: dict[str, list[dict[str, str]]]
) -> None:
    """
    Add ignore entries for dependencies to the dependabot updates.
    This function processes only 'ignore-dependency' entries from the ignores dictionary.

    Args:
        updates: CommentedSeq of dependabot update entries
        ignore_entries: Dictionary containing ignore rules for dependencies
    """
    ignore_dependencies = ignore_entries["dependencies"]

    for ignore in ignore_dependencies:
        ignore_ecosystem = ignore.get("package-ecosystem")
        ignore_dependency = ignore.get("dependency-name")

        # Create a fresh `CommentedSeq` for `update-types` to avoid YAML anchors
        ignore_update_types = CommentedSeq(
            [str(item) for item in ignore.get("update-types", [])]
        )

        # Construct `ignore_entry` as a new `CommentedMap`
        ignore_entry = CommentedMap(
            {
                "dependency-name": str(ignore_dependency),
                "update-types": ignore_update_types,
            }
        )

        for update in updates:
            if (
                update.get("package-ecosystem") == ignore_ecosystem
                and "groups" in update
                and "prodsec" not in update["groups"]
            ):
                # Ensure `ignore` key exists and is a `CommentedSeq`
                update.setdefault("ignore", CommentedSeq())

                # Append a deep copy of `ignore_entry` to guarantee uniqueness
                update["ignore"].append(copy.deepcopy(ignore_entry))
                log.debug(
                    "Applied ignore dependency rule",
                    dependency=str(ignore_dependency),
                    ecosystem=ignore_ecosystem,
                    update_types=[str(ut) for ut in ignore_update_types],
                    target_update_ecosystem=update.get("package-ecosystem"),
                    target_update_directory=update.get("directory"),
                )


def add_registries(
    dependabot_config: CommentedMap, registry_configs: list[dict[str, Any]]
) -> dict[str, dict[str, Any]]:
    """
    Add registry configurations to the dependabot config.

    Args:
        dependabot_config: The main dependabot configuration
        registry_configs: List of registry configurations from settings file

    Returns:
        Dictionary mapping registry names to their configurations for use in update entries
    """
    if not registry_configs:
        return {}

    registries = CommentedMap()
    registry_map = {}  # For returning registry info to be used in update entries

    for registry in registry_configs:
        registry_name = registry.get("name")
        if not registry_name:
            log.warning(
                "Registry entry missing 'name' field, skipping", registry=registry
            )
            continue

        # Validate required fields
        required_fields = ["name", "type", "url"]
        if not all(field in registry for field in required_fields):
            log.error(
                "Registry missing required fields",
                registry=registry,
                required=required_fields,
            )
            continue

        registry_config = CommentedMap()
        registry_info = {}  # Store registry info for return

        for key, value in registry.items():
            if (
                key != "name" and key != "applies-to"
            ):  # Don't include name or applies-to in the config
                registry_config[key] = value
                registry_info[key] = value

        registries[registry_name] = registry_config
        registry_map[registry_name] = {
            "type": registry.get("type"),
            "applies-to": registry.get(
                "applies-to", []
            ),  # Package ecosystems this registry applies to
            "config": registry_info,
        }

        log.info(
            "Added registry configuration",
            name=registry_name,
            type=registry.get("type"),
            applies_to=registry.get("applies-to", []),
        )

    if registries:
        dependabot_config["registries"] = registries
        # Add comment for clarity
        dependabot_config.yaml_set_comment_before_after_key(
            "registries", before=" Registry configurations", indent=0
        )

    return registry_map


def save_dependabot_config(dependabot_config: CommentedMap, repo_path: str) -> None:
    """
    Save the generated dependabot configuration to the repository's .github directory.

    Args:
        dependabot_config: CommentedMap containing the complete dependabot configuration
        repo_path: Path to the repository root directory
    """
    yaml = initialize_yaml(safe=False)  # Use non-safe mode for writing with comments
    config_path = f"{repo_path}.github/dependabot.yml"
    log.info("Saving generated dependabot configuration", path=config_path)
    with open(config_path, "w") as f:
        yaml.dump(dependabot_config, f)


def main(parsed_args: argparse.Namespace | None = None) -> None:
    args = parsed_args if parsed_args is not None else parse_arguments()
    log.debug("Parsed arguments", args=vars(args))
    open_pr_limit = args.open_pull_requests_limit
    repo_path = os.path.join(args.repo_path, "")

    # Load configurator settings including ignores, registries, custom files, and other settings
    settings = load_configurator_settings(repo_path=repo_path)
    ignore_directories = settings["directories"]
    ignore_file_patterns = settings["file_patterns"]
    registry_configs = settings["registries"]
    custom_files = settings["custom_files"]

    # Auto-detect package managers in the repository
    directory_managers = get_directory_managers(repo_path, PACKAGE_MANAGERS)

    # Add any custom files specified in the configuration
    add_custom_files_to_directory_managers(repo_path, custom_files, directory_managers)

    github_dir_path = f"{repo_path}.github"
    os.makedirs(github_dir_path, exist_ok=True)
    log.debug("Ensured .github directory exists", path=github_dir_path)

    dependabot_config = CommentedMap()
    dependabot_config["version"] = 2
    dependabot_config["updates"] = updates = CommentedSeq()

    # Add registry configurations if any exist and get registry mapping
    registry_map = add_registries(dependabot_config, registry_configs)

    # Iterate through unique directories first
    for dir_path, manager_files in sorted(directory_managers.items()):
        # Get unique managers for this directory
        unique_managers = sorted(list(set(manager for manager, _ in manager_files)))

        # Iterate through unique managers in this directory
        for manager in unique_managers:
            # --- File Pattern Ignore Check (for skipping *only* version updates) ---
            # Check if *any* manifest file for this manager matches an ignore pattern
            files_to_check = [
                (mgr, fname) for mgr, fname in manager_files if mgr == manager
            ]
            skip_version_update_for_manager = False
            matched_pattern_for_log = None
            for (
                mgr_check,
                fname_check,
            ) in files_to_check:  # Iterate to find which pattern matched
                for pattern in ignore_file_patterns:
                    if matches_ignore_pattern(
                        fname_check, [pattern]
                    ):  # Check one pattern at a time
                        skip_version_update_for_manager = True
                        matched_pattern_for_log = pattern
                        break
                if skip_version_update_for_manager:
                    break

            if skip_version_update_for_manager:
                log.info(
                    "Skipping version updates for manager due to file pattern ignore",
                    manager=manager,
                    directory=dir_path,
                    file_pattern=matched_pattern_for_log,  # Add the pattern that caused the skip
                )

            # Create a fresh copy of the schedule dictionary
            schedule: dict[str, Any] = (
                # DoubleQuotedScalarString is used to ensure the time is treated as a string
                {
                    "interval": "weekly",
                    "day": "wednesday",
                    "time": DoubleQuotedScalarString("08:00"),
                    "timezone": "America/Chicago",
                }
                if manager == "docker"
                else {
                    "interval": "weekly",
                    "day": "monday",
                    "time": DoubleQuotedScalarString("08:00"),
                    "timezone": "America/Chicago",
                }
            )

            # Create version update entry only if limit > 0 and not skipped for this manager
            if open_pr_limit > 0 and not skip_version_update_for_manager:
                normal_entry = create_dependabot_update_entry(
                    manager,
                    dir_path,
                    schedule.copy(),
                    open_pr_limit,
                    args.main_branch,
                    ignore_directories,
                    registry_map,
                )
                # Note: normal_entry should NOT be None here because we checked ignore_directories above
                if normal_entry is not None:
                    updates.append(normal_entry)
                    key = len(updates) - 1
                    comment = f" {dir_path.strip('/') or '/'} {manager} version updates"
                    updates.yaml_set_comment_before_after_key(
                        key, before=comment, indent=2
                    )

            security_entry = create_security_update_entry(
                manager,
                dir_path,
                schedule.copy(),
                transitive_security=args.transitive_security,
                registry_map=registry_map,
            )
            updates.append(security_entry)
            key = len(updates) - 1
            comment = f" {dir_path.strip('/') or '/'} {manager} security updates"
            updates.yaml_set_comment_before_after_key(key, before=comment, indent=2)

    recursive_delete_comment_attribs(settings["dependencies"])
    if settings["dependencies"]:
        add_ignores(updates, settings)

    save_dependabot_config(dependabot_config, repo_path)


if __name__ == "__main__":
    main()
