# Contributing to Dependabot Configurator

Thank you for your interest in contributing to the Dependabot Configurator! This document provides guidelines for contributing to this project.

## Table of Contents

- [Getting Started](#getting-started)
- [Development Setup](#development-setup)
- [Making Changes](#making-changes)
- [Testing](#testing)
- [Submitting Changes](#submitting-changes)
- [Reporting Issues](#reporting-issues)

## Getting Started

1. Fork the repository on GitHub
2. Clone your fork locally
3. Create a new branch for your changes
4. Make your changes
5. Test your changes
6. Submit a pull request

## Development Setup

### Prerequisites

- Python 3.12 or higher
- Poetry for dependency management
- Git

### Installation

1. Clone the repository:

   ```bash
   git clone https://github.com/your-org/dependabot-configurator.git
   cd dependabot-configurator
   ```

2. Install pre-commit hooks:
   ```bash
   poetry run pre-commit install
   ```
3. Install dependencies:
   ```bash
   cd app/dependabot-configurator
   poetry install
   ```

## Making Changes

### Code Style

- Follow PEP 8 for Python code
- Use modern type hints (e.g., `list[str]` instead of `List[str]`)
- Add comprehensive docstrings to all functions and classes
- Use double quotes for strings
- Maintain 2 blank lines between functions

### Customization Guidelines

When making changes to workflow files, ensure all customization points are clearly marked with `# CUSTOMIZE:` comments that include:

- Clear instructions on what needs to be changed
- Examples of the expected format
- Context about why the customization is needed

### Environment Variables

- Use `ORGANIZATION_PREFIX` for organization-specific configuration
- Ensure all environment variables have proper error handling
- Document required environment variables in README

## Testing

### Running Tests

```bash
cd app/dependabot-configurator
poetry run pytest tests/ -v
```

### Test Coverage

- Maintain high test coverage for all new code
- Add tests for both success and failure scenarios
- Mock external dependencies appropriately

### Linting

```bash
cd app/dependabot-configurator
poetry run ruff check .
```

## Submitting Changes

### Pull Request Process

1. Ensure your code passes all tests and linting
2. Update documentation as needed
3. Add a clear description of your changes
4. Reference any related issues
5. Ensure your branch is up to date with main

### Pull Request Template

Please include:

- **Description**: What changes were made and why
- **Testing**: How the changes were tested
- **Documentation**: Any documentation updates needed
- **Breaking Changes**: Any breaking changes and migration path

### Commit Messages

Use clear, descriptive commit messages:

- Use present tense ("Add feature" not "Added feature")
- Use imperative mood ("Move cursor to..." not "Moves cursor to...")
- Limit first line to 72 characters
- Reference issues and pull requests when applicable

## Reporting Issues

### Bug Reports

When reporting bugs, please include:

- Clear description of the issue
- Steps to reproduce
- Expected vs actual behavior
- Environment details (OS, Python version, etc.)
- Relevant logs or error messages

### Feature Requests

For feature requests, please include:

- Clear description of the desired functionality
- Use case and business justification
- Proposed implementation approach (if applicable)
- Any potential breaking changes

### Security Issues

For security-related issues, please:

- Do not open public issues
- Email security concerns to the maintainers
- Provide detailed information about the vulnerability
- Allow time for the issue to be addressed before disclosure

## Development Guidelines

### Architecture Principles

- **Hub-based Customization**: Organizations fork and customize rather than complex parameter passing
- **Clear Separation**: Maintain clear boundaries between configuration generation and workflow execution
- **Security First**: All GitHub Actions should be pinned to SHA hashes
- **Comprehensive Logging**: Use structured logging for debugging and monitoring

### Adding New Package Managers

When adding support for new package managers:

1. Add patterns to `PACKAGE_MANAGERS` dictionary
2. Add appropriate test cases
3. Update documentation
4. Consider any special scheduling requirements

### Workflow Changes

When modifying workflows:

1. Test with both public and self-hosted runners
2. Ensure all customization points are marked
3. Validate security implications
4. Update related documentation

## Questions?

If you have questions about contributing, please:

- Check existing issues and discussions
- Review the documentation
- Open a discussion for general questions
- Open an issue for specific problems

Thank you for contributing to Dependabot Configurator!
