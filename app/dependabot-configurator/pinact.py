import argparse
import os
import re
import subprocess
import sys

import structlog

# Configure structlog for basic console output suitable for GitHub Actions
structlog.configure(
    processors=[
        structlog.stdlib.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
        # Use key-value formatting for better parsing in logs if needed
        structlog.processors.dict_tracebacks,
        structlog.processors.JSONRenderer(sort_keys=True),
    ],
    logger_factory=structlog.stdlib.LoggerFactory(),
    wrapper_class=structlog.stdlib.BoundLogger,
    cache_logger_on_first_use=True,
)
log = structlog.get_logger()


def parse_arguments() -> argparse.Namespace:
    """
    Parse command line arguments for the pinact script.

    Returns:
        Parsed command line arguments containing repo-path and force configuration
    """
    parser = argparse.ArgumentParser(description="Run pinact on valid workflows.")
    parser.add_argument(
        "--repo-path",
        type=str,
        default="./.github/workflows",
        help="Path to the repository workflows directory",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Force pinact to run on all workflows, even if actions are already pinned. "
        "Useful for updating already-pinned actions to latest versions.",
    )
    return parser.parse_args()


# The global 'args' object obtained by calling parse_arguments() at module level
# has been removed to prevent issues when importing this module for testing.
# Arguments should be parsed within the `if __name__ == "__main__":` block
# and passed explicitly to functions like cli_main.


def find_valid_workflows(base_path: str = "./.github/workflows") -> list[str]:
    """
    Finds workflow files (.yml or .yaml) in the specified base path, excluding those
    that appear to be using reusable workflows from the organization.

    Reusable org workflows are excluded because pinact will fail on them if they are private.

    Requires ORGANIZATION_PREFIX environment variable to determine which workflows to exclude. This is normally passed from the workflow file.

    Args:
        base_path: Path to search for workflow files

    Returns:
        List of valid workflow file paths that don't use organization reusable workflows

    Raises:
        ValueError: If ORGANIZATION_PREFIX environment variable is not set
    """
    valid_workflows: list[str] = []
    org_prefix = os.getenv("ORGANIZATION_PREFIX")

    if not org_prefix:
        log.error("ORGANIZATION_PREFIX environment variable is required but not set")
        raise ValueError("ORGANIZATION_PREFIX environment variable must be set")

    log.info("Searching for workflow files", base_path=base_path, org_prefix=org_prefix)

    try:
        for root, _, files in os.walk(base_path):
            for file in files:
                if file.endswith((".yml", ".yaml")):
                    file_path = os.path.join(root, file)
                    log.debug("Checking potential workflow file", path=file_path)
                    try:
                        with open(file_path, "r", encoding="utf-8") as f:
                            content = f.read()
                            # Check to exclude reusable workflows from the organization
                            exclusion_pattern = f"uses: {org_prefix}/"
                            if exclusion_pattern not in content:
                                log.debug("Found valid workflow file", path=file_path)
                                valid_workflows.append(file_path)
                            else:
                                log.debug(
                                    "Skipping reusable workflow",
                                    path=file_path,
                                    pattern=exclusion_pattern,
                                )
                    except Exception:
                        log.exception(
                            "Error reading workflow file, skipping", path=file_path
                        )
    except Exception:
        log.exception("Error walking directory", base_path=base_path)
        # Depending on severity, might want to exit or return empty list
        # For now, return what was found so far.
        # To do in the future: consider handling specific exceptions like PermissionError.

    log.info(
        "Finished searching for workflow files",
        count=len(valid_workflows),
        org_prefix=org_prefix,
    )
    return valid_workflows


def needs_pinning(workflow_path: str) -> bool:
    """
    Checks if a workflow file contains any 'uses:' lines that are not pinned to a SHA256 hash.

    Args:
        workflow_path: Path to the workflow file to check

    Returns:
        True if the workflow needs pinning (has unpinned actions), False otherwise
    """
    # Regex to find 'uses:' lines, accounting for optional leading hyphen in YAML lists.
    uses_pattern = re.compile(r"^\s*-?\s*uses:\s*(\S+)")
    sha_pin_pattern = re.compile(r"@[a-f0-9]{40}")
    file_needs_pinning = False

    log.debug("Checking workflow for pinning needs", workflow_path=workflow_path)
    try:
        with open(workflow_path, "r", encoding="utf-8") as f:
            lines = f.readlines()
            for line_num, line in enumerate(lines, 1):
                match = uses_pattern.search(line)
                if match:
                    action_reference = match.group(1).strip()
                    log.debug(
                        "Found 'uses' line",
                        workflow=workflow_path,
                        line=line_num,
                        action=action_reference,
                    )
                    if not sha_pin_pattern.search(action_reference):
                        log.info(
                            "Found unpinned action",
                            workflow=workflow_path,
                            line=line_num,
                            action=action_reference,
                        )
                        file_needs_pinning = True
                        break  # Stop checking once one unpinned action is found
                    else:
                        log.debug(
                            "Action is already pinned",
                            workflow=workflow_path,
                            line=line_num,
                            action=action_reference,
                        )

    except FileNotFoundError:
        log.error("Workflow file not found during check", path=workflow_path)
        return False  # Cannot determine status if file not found
    except Exception:
        log.exception(
            "Error reading or processing workflow file during check", path=workflow_path
        )
        return False  # Treat unexpected errors as unable to determine status

    if not file_needs_pinning:
        log.debug(
            "Finished check: No unpinned actions found", workflow_path=workflow_path
        )

    return file_needs_pinning


def run_pinact_on_workflows(workflows: list[str]) -> None:
    """
    Runs the 'pinact' command on a list of workflow file paths.
    Assumes 'pinact' is available in the PATH (as it should be in the GHA runner).
    Paths provided should be relative to the current working directory where the script is executed.

    Args:
        workflows: List of workflow file paths to process with pinact
    """
    success_count = 0
    failure_count = 0
    total_workflows = len(workflows)

    log.info("Starting pinact execution", total_workflows=total_workflows)

    for workflow_path in workflows:
        # Use the relative path provided by find_valid_workflows directly
        # as it's relative to the script's execution context in the runner.
        command = ["pinact", "run", "-u", workflow_path]
        log.info(
            "Attempting to pin workflow",
            workflow=workflow_path,
            command=" ".join(command),
        )

        try:
            # Execute pinact in the current working directory
            result = subprocess.run(
                command,
                check=True,  # Raise exception on non-zero exit code
                capture_output=True,
                text=True,
                timeout=120,  # Increased timeout for potentially slow operations
            )
            log.info(
                "pinact executed successfully",
                workflow=workflow_path,
                stdout=result.stdout.strip(),
            )
            if result.stderr:
                log.warning(
                    "pinact produced stderr output",
                    workflow=workflow_path,
                    stderr=result.stderr.strip(),
                )
            success_count += 1
        except subprocess.CalledProcessError as e:
            log.error(
                "pinact command failed",
                workflow=workflow_path,
                return_code=e.returncode,
                stdout=e.stdout.strip() if e.stdout else None,
                stderr=e.stderr.strip() if e.stderr else None,
            )
            failure_count += 1
        # Continue processing other files even if one fails
        except subprocess.TimeoutExpired:
            log.error("pinact command timed out", workflow=workflow_path, timeout=120)
            failure_count += 1
        except Exception:
            # Catch any other unexpected exceptions during subprocess execution
            log.exception(
                "An unexpected error occurred during pinact execution",
                workflow=workflow_path,
            )
            failure_count += 1

    log.info(
        "Pinact execution summary",
        success=success_count,
        failed=failure_count,
        total=total_workflows,
    )
    if failure_count > 0:
        log.warning("Some workflows failed to pin.")
        # Optionally, exit with error if any pinact run failed
        # sys.exit(1)


def cli_main(parsed_args: argparse.Namespace) -> int:
    """
    Main logic for the pinact script.

    Args:
        parsed_args: Parsed command line arguments containing configuration

    Returns:
        Exit code (0 for success, 1 for failure)
    """
    exit_code = 0
    try:
        force = getattr(parsed_args, "force", False)

        log.info(
            "Starting pinact script execution",
            repo_path_arg=parsed_args.repo_path,
            force=force,
        )
        # The repo_path argument is relative to the script's execution context
        repo_path = os.path.abspath(parsed_args.repo_path)
        log.info("Absolute workflow path calculated", repo_path_abs=repo_path)

        potential_workflows = find_valid_workflows(base_path=repo_path)
        log.info("Found potential workflows", count=len(potential_workflows))

        # If --force flag is set, pin all workflows regardless of current pin status
        # This is useful for updating already-pinned actions to their latest versions
        if force:
            log.info(
                "Force mode enabled: pinning all workflows regardless of current pin status"
            )
            workflows_to_pin = potential_workflows
        else:
            workflows_to_pin = [wf for wf in potential_workflows if needs_pinning(wf)]

        if workflows_to_pin:
            log.info(
                "Identified workflows requiring pinning",
                count=len(workflows_to_pin),
                paths=workflows_to_pin,
            )
            run_pinact_on_workflows(workflows_to_pin)
        else:
            log.info("No workflows require pinning.")

        log.info("Pinact script finished successfully.", exit_code=exit_code)

    except Exception:
        log.exception("An critical error occurred during script execution.")
        exit_code = 1  # Ensure non-zero exit code on unexpected failure
        # Log the exit code again in case of exception before exiting
        log.error("Exiting due to critical error.", exit_code=exit_code)
    return exit_code


if __name__ == "__main__":
    parsed_args = parse_arguments()
    final_exit_code = cli_main(parsed_args)
    sys.exit(final_exit_code)
