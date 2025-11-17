# Security Policy

## Supported Versions

We actively support the following versions of Dependabot Configurator:

| Version | Supported          |
| ------- | ------------------ |
| 1.0.x   | :white_check_mark: |

## Reporting a Vulnerability

We take security vulnerabilities seriously. If you discover a security vulnerability in Dependabot Configurator, please report it responsibly.

### How to Report

**Please do not report security vulnerabilities through public GitHub issues.**

As mentioned in our [responsible disclosure policy](https://redcanary.com/responsible-disclosure/) we do not have a bug bounty program or offer any compensation for vulnerability reports but we do appreciate you reporting issues!

1. **Email**: Send details to security@redcanary.com
2. **Private disclosure**: Use GitHub's private vulnerability reporting feature

### What to Include

When reporting a vulnerability, please include:

- **Description**: Clear description of the vulnerability
- **Impact**: Potential impact and attack scenarios
- **Reproduction**: Steps to reproduce the vulnerability
- **Environment**: Affected versions and configurations
- **Proof of Concept**: Code or screenshots demonstrating the issue (if applicable)

### Response Timeline

- **Acknowledgment**: We will acknowledge receipt within 48 hours
- **Initial Assessment**: We will provide an initial assessment within 5 business days
- **Updates**: We will provide regular updates on our progress
- **Resolution**: We aim to resolve critical vulnerabilities within 30 days

### Disclosure Policy

- We request that you give us reasonable time to investigate and fix the vulnerability before public disclosure
- We will coordinate with you on the timing of public disclosure
- We will credit you for the discovery (unless you prefer to remain anonymous)

## Security Best Practices

### For Users

When using Dependabot Configurator:

1. **Keep Updated**: Always use the latest version
2. **Secure Secrets**: Properly manage GitHub App credentials
3. **Review Changes**: Review all generated configurations before deployment
4. **Monitor Logs**: Monitor workflow execution logs for anomalies
5. **Limit Permissions**: Use minimal required permissions for GitHub Apps

### For Contributors

When contributing to Dependabot Configurator:

1. **Secure Coding**: Follow secure coding practices
2. **Input Validation**: Validate all inputs and environment variables
3. **Dependency Management**: Keep dependencies updated and secure
4. **Secret Handling**: Never commit secrets or credentials
5. **Code Review**: All changes require security-focused code review

## Security Features

### GitHub App Authentication

- Uses short-lived tokens (10 minutes maximum)
- Implements granular permissions
- Supports organization-level access control

### Action Security

- All GitHub Actions are pinned to SHA256 hashes
- Automated pinning via `pinact` tool
- Regular security updates for action dependencies

### Workflow Security

- Minimal required permissions for each job
- Secure handling of secrets and tokens
- Input validation for all workflow parameters

### Code Security

- Structured logging prevents information leakage
- Environment variable validation
- Secure file handling practices

## Known Security Considerations

### GitHub App Permissions

The GitHub App requires the following permissions:

- **Contents**: Write access for creating/updating files
- **Pull Requests**: Write access for creating pull requests
- **Issues**: Write access for managing labels

### Workflow Execution

- Workflows run with repository write permissions
- Self-hosted runners may have additional security considerations
- Generated configurations should be reviewed before deployment

### Dependencies

- Python dependencies managed via Poetry with lock files
- Regular dependency updates via Dependabot
- Security scanning of dependencies

## Security Updates

Security updates will be:

- Released as patch versions when possible
- Documented in release notes with severity levels
- Communicated through GitHub Security Advisories for critical issues

## Contact

For security-related questions or concerns, please contact the project maintainers through the appropriate channels mentioned above.

Thank you for helping keep Dependabot Configurator secure!
