import argparse
import os
import subprocess
from pathlib import Path
from unittest import mock

# Import pinact directly, assuming app/dependabot-configurator is on sys.path
import pinact
import structlog


# Helper function to create mock workflow files
def create_mock_workflow(path: Path, content: str):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)


# --- Tests for find_valid_workflows ---
@mock.patch.dict(os.environ, {"ORGANIZATION_PREFIX": "testorg"})
def test_find_valid_workflows_finds_yml_and_yaml(tmp_path: Path):
    workflows_dir = tmp_path / ".github" / "workflows"
    create_mock_workflow(workflows_dir / "ci.yml", "name: CI")
    create_mock_workflow(workflows_dir / "deploy.yaml", "name: Deploy")
    create_mock_workflow(workflows_dir / "not_a_workflow.txt", "name: Text")

    found = pinact.find_valid_workflows(base_path=str(workflows_dir))
    assert len(found) == 2
    assert str(workflows_dir / "ci.yml") in found
    assert str(workflows_dir / "deploy.yaml") in found


@mock.patch.dict(os.environ, {"ORGANIZATION_PREFIX": "redcanaryco"})
def test_find_valid_workflows_excludes_redcanary_reusable(tmp_path: Path):
    workflows_dir = tmp_path / ".github" / "workflows"
    create_mock_workflow(
        workflows_dir / "ci.yml", "name: CI\nuses: actions/checkout@v3"
    )
    create_mock_workflow(
        workflows_dir / "reusable.yml",
        "name: Reusable\nuses: redcanaryco/some-action@v1",
    )
    found = pinact.find_valid_workflows(base_path=str(workflows_dir))
    assert len(found) == 1
    assert str(workflows_dir / "ci.yml") in found
    assert str(workflows_dir / "reusable.yml") not in found


@mock.patch.dict(os.environ, {"ORGANIZATION_PREFIX": "testorg"})
def test_find_valid_workflows_empty_directory(tmp_path: Path):
    workflows_dir = tmp_path / ".github" / "workflows"
    workflows_dir.mkdir(parents=True, exist_ok=True)
    found = pinact.find_valid_workflows(base_path=str(workflows_dir))
    assert len(found) == 0


@mock.patch.dict(os.environ, {"ORGANIZATION_PREFIX": "testorg"})
def test_find_valid_workflows_non_existent_directory(tmp_path: Path):
    non_existent_dir = tmp_path / "does_not_exist"
    found = pinact.find_valid_workflows(base_path=str(non_existent_dir))
    assert len(found) == 0


@mock.patch.dict(os.environ, {"ORGANIZATION_PREFIX": "testorg"})
@mock.patch("builtins.open", side_effect=IOError("Test read error"))
@mock.patch("os.walk")
def test_find_valid_workflows_read_error(mock_os_walk, mock_open, tmp_path: Path):
    workflows_dir_str = str(tmp_path / ".github" / "workflows")
    mock_os_walk.return_value = [(workflows_dir_str, [], ["error.yml"])]

    with structlog.testing.capture_logs() as captured_logs:
        found = pinact.find_valid_workflows(base_path=workflows_dir_str)

    assert len(found) == 0
    assert any(
        "Error reading workflow file, skipping" in log["event"]
        and log["path"] == os.path.join(workflows_dir_str, "error.yml")
        for log in captured_logs
    )


def test_find_valid_workflows_missing_env_var(tmp_path: Path):
    workflows_dir = tmp_path / ".github" / "workflows"
    workflows_dir.mkdir(parents=True, exist_ok=True)

    # Ensure ORGANIZATION_PREFIX is not set
    with mock.patch.dict(os.environ, {}, clear=True):
        with structlog.testing.capture_logs() as captured_logs:
            try:
                pinact.find_valid_workflows(base_path=str(workflows_dir))
                assert False, "Expected ValueError to be raised"
            except ValueError as e:
                assert "ORGANIZATION_PREFIX environment variable must be set" in str(e)

        assert any(
            "ORGANIZATION_PREFIX environment variable is required but not set"
            in log["event"]
            for log in captured_logs
        )


# --- Tests for needs_pinning ---
def test_needs_pinning_unpinned_action(tmp_path: Path):
    wf_path = tmp_path / "unpinned.yml"
    create_mock_workflow(
        wf_path, "jobs:\n  build:\n    steps:\n      - uses: actions/checkout@v3"
    )
    assert pinact.needs_pinning(str(wf_path)) is True


def test_needs_pinning_all_pinned(tmp_path: Path):
    wf_path = tmp_path / "pinned.yml"
    create_mock_workflow(
        wf_path,
        "jobs:\n  build:\n    steps:\n      - uses: actions/checkout@a123456789012345678901234567890123456789",
    )
    assert pinact.needs_pinning(str(wf_path)) is False


def test_needs_pinning_mixed_actions(tmp_path: Path):
    wf_path = tmp_path / "mixed.yml"
    create_mock_workflow(
        wf_path,
        "jobs:\n  build:\n    steps:\n      - uses: actions/setup-python@b123456789012345678901234567890123456789\n      - uses: actions/checkout@v3",
    )
    assert pinact.needs_pinning(str(wf_path)) is True


def test_needs_pinning_no_uses_lines(tmp_path: Path):
    wf_path = tmp_path / "no_uses.yml"
    create_mock_workflow(wf_path, "name: No Actions")
    assert pinact.needs_pinning(str(wf_path)) is False


def test_needs_pinning_commented_out_uses(tmp_path: Path):
    wf_path = tmp_path / "commented.yml"
    create_mock_workflow(
        wf_path, "jobs:\n  build:\n    steps:\n      # - uses: actions/checkout@v3"
    )
    assert pinact.needs_pinning(str(wf_path)) is False


def test_needs_pinning_file_not_found(tmp_path: Path):
    wf_path = tmp_path / "non_existent.yml"
    with structlog.testing.capture_logs() as captured_logs:
        assert pinact.needs_pinning(str(wf_path)) is False
    assert any(
        "Workflow file not found during check" in log["event"] for log in captured_logs
    )


# --- Tests for run_pinact_on_workflows ---
@mock.patch("subprocess.run")
def test_run_pinact_on_workflows_calls_subprocess(mock_run, tmp_path: Path):
    mock_run.return_value = subprocess.CompletedProcess(
        args=[], returncode=0, stdout="Pinned", stderr=""
    )
    wf_path = str(tmp_path / "workflow.yml")  # Ensure wf_path is a string
    pinact.run_pinact_on_workflows([wf_path])
    mock_run.assert_called_once_with(
        ["pinact", "run", "-u", wf_path],
        check=True,
        capture_output=True,
        text=True,
        timeout=120,
    )


@mock.patch("subprocess.run")
def test_run_pinact_on_workflows_handles_called_process_error(mock_run, tmp_path: Path):
    mock_run.side_effect = subprocess.CalledProcessError(
        1, ["pinact"], stderr="Error output"
    )
    wf_path = str(tmp_path / "workflow_fail.yml")  # Ensure wf_path is a string
    with structlog.testing.capture_logs() as captured_logs:
        pinact.run_pinact_on_workflows([wf_path])
    mock_run.assert_called_once()
    assert any("pinact command failed" in log["event"] for log in captured_logs)
    assert any(
        log.get("stderr") == "Error output"
        for log in captured_logs
        if "pinact command failed" in log["event"]
    )


@mock.patch("subprocess.run")
def test_run_pinact_on_workflows_handles_timeout(mock_run, tmp_path: Path):
    mock_run.side_effect = subprocess.TimeoutExpired(["pinact"], timeout=0.1)
    wf_path = str(tmp_path / "workflow_timeout.yml")  # Ensure wf_path is a string
    with structlog.testing.capture_logs() as captured_logs:
        pinact.run_pinact_on_workflows([wf_path])
    mock_run.assert_called_once()
    assert any("pinact command timed out" in log["event"] for log in captured_logs)


@mock.patch("subprocess.run")
def test_run_pinact_on_workflows_empty_list(mock_run):
    pinact.run_pinact_on_workflows([])
    mock_run.assert_not_called()


# --- Tests for main script execution (cli_main) ---
@mock.patch("pinact.find_valid_workflows")
@mock.patch("pinact.needs_pinning")
@mock.patch("pinact.run_pinact_on_workflows")
def test_cli_main_workflows_found_and_pinned(
    mock_run_pinact_wrapper, mock_needs_pinning, mock_find_workflows, tmp_path: Path
):
    args = argparse.Namespace(repo_path=str(tmp_path))
    workflow_file_path = str(tmp_path / "wf1.yml")
    mock_find_workflows.return_value = [workflow_file_path]
    mock_needs_pinning.return_value = True

    exit_code = pinact.cli_main(args)

    mock_find_workflows.assert_called_once_with(base_path=str(tmp_path))
    mock_needs_pinning.assert_called_once_with(workflow_file_path)
    mock_run_pinact_wrapper.assert_called_once_with([workflow_file_path])
    assert exit_code == 0


@mock.patch("pinact.find_valid_workflows")
@mock.patch("pinact.needs_pinning")
@mock.patch("pinact.run_pinact_on_workflows")
def test_cli_main_all_workflows_already_pinned(
    mock_run_pinact_wrapper, mock_needs_pinning, mock_find_workflows, tmp_path: Path
):
    args = argparse.Namespace(repo_path=str(tmp_path))
    wf1_path = str(tmp_path / "wf1.yml")
    wf2_path = str(tmp_path / "wf2.yml")
    mock_find_workflows.return_value = [wf1_path, wf2_path]
    mock_needs_pinning.return_value = False

    with structlog.testing.capture_logs() as captured_logs:
        exit_code = pinact.cli_main(args)

    mock_find_workflows.assert_called_once_with(base_path=str(tmp_path))
    assert mock_needs_pinning.call_count == 2
    mock_needs_pinning.assert_any_call(wf1_path)
    mock_needs_pinning.assert_any_call(wf2_path)
    mock_run_pinact_wrapper.assert_not_called()
    assert any("No workflows require pinning." in log["event"] for log in captured_logs)
    assert exit_code == 0


@mock.patch("pinact.find_valid_workflows")
@mock.patch("pinact.needs_pinning")
@mock.patch("pinact.run_pinact_on_workflows")
def test_cli_main_no_workflows_found(
    mock_run_pinact_wrapper, mock_needs_pinning, mock_find_workflows, tmp_path: Path
):
    args = argparse.Namespace(repo_path=str(tmp_path))
    mock_find_workflows.return_value = []

    with structlog.testing.capture_logs() as captured_logs:
        exit_code = pinact.cli_main(args)

    mock_find_workflows.assert_called_once_with(base_path=str(tmp_path))
    mock_needs_pinning.assert_not_called()
    mock_run_pinact_wrapper.assert_not_called()
    assert any("No workflows require pinning." in log["event"] for log in captured_logs)
    assert exit_code == 0


@mock.patch("pinact.find_valid_workflows", side_effect=Exception("Test find error"))
def test_cli_main_handles_exception_in_find_workflows(
    mock_find_workflows, tmp_path: Path
):
    args = argparse.Namespace(repo_path=str(tmp_path))
    with structlog.testing.capture_logs() as captured_logs:
        exit_code = pinact.cli_main(args)
    assert exit_code == 1
    assert any(
        "An critical error occurred during script execution." in log["event"]
        for log in captured_logs
    )


@mock.patch("pinact.find_valid_workflows")
@mock.patch("pinact.needs_pinning", side_effect=Exception("Test needs_pinning error"))
def test_cli_main_handles_exception_in_needs_pinning(
    mock_needs_pinning, mock_find_workflows, tmp_path: Path
):
    args = argparse.Namespace(repo_path=str(tmp_path))
    mock_find_workflows.return_value = [str(tmp_path / "wf1.yml")]
    with structlog.testing.capture_logs() as captured_logs:
        exit_code = pinact.cli_main(args)
    assert exit_code == 1
    assert any(
        "An critical error occurred during script execution." in log["event"]
        for log in captured_logs
    )


@mock.patch("pinact.find_valid_workflows")
@mock.patch("pinact.needs_pinning")
@mock.patch(
    "pinact.run_pinact_on_workflows", side_effect=Exception("Test run_pinact error")
)
def test_cli_main_handles_exception_in_run_pinact(
    mock_run_pinact, mock_needs_pinning, mock_find_workflows, tmp_path: Path
):
    args = argparse.Namespace(repo_path=str(tmp_path))
    mock_find_workflows.return_value = [str(tmp_path / "wf1.yml")]
    mock_needs_pinning.return_value = True
    with structlog.testing.capture_logs() as captured_logs:
        exit_code = pinact.cli_main(args)
    assert exit_code == 1
    assert any(
        "An critical error occurred during script execution." in log["event"]
        for log in captured_logs
    )
