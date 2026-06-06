---
name: "python-code-checker"
description: "Comprehensive Python code quality checker. Invoke when user asks to check code, run linters, fix errors, or needs to reduce runtime errors. Includes Pylint, Flake8, MyPy, Bandit, Ruff, and AI hallucination detection tools."
---

# Python Code Checker

A comprehensive skill for checking Python code quality, preventing errors, and detecting AI-generated code issues.

## When to Invoke

**Activate this skill when:**
- User asks to "check code", "run linter", or "fix errors"
- User wants to "reduce runtime errors" or "improve code quality"
- User needs to "check for bugs" or "validate Python code"
- User asks to "verify AI-generated code" or "detect hallucinations"
- Before running tests or deploying code
- During code review or pre-commit checks

## Installation

Before using this skill, install the required tools:

```bash
pip install pylint flake8 mypy bandit ruff openfactcheck
```

## Usage

### 1. Quick Quality Check

Run multiple linters together for comprehensive checking:

```bash
# Run all basic checks
pylint your_module.py
flake8 your_module.py
mypy your_module.py
```

### 2. Code Style Check with Flake8

Check for PEP 8 violations and common errors:

```bash
flake8 your_module.py --max-line-length=120 --extend-ignore=E203,W503
```

### 3. Type Checking with MyPy

Ensure type safety and catch type-related errors:

```bash
mypy your_module.py --strict
```

### 4. Security Check with Bandit

Detect common security issues:

```bash
bandit -r your_project/ -f json
```

### 5. Fast Linting with Ruff

Ultra-fast Python linter written in Rust:

```bash
ruff check your_module.py
ruff check your_project/ --fix  # Auto-fix issues
```

### 6. AI Hallucination Detection

Check AI-generated code for potential hallucinations:

```bash
# Using OpenFactCheck
pip install openfactcheck
python -c "
from openfactcheck import OpenFactCheck
ofc = OpenFactCheck()
result = ofc.check('your_text_or_code')
print(result)
"
```

### 7. Comprehensive Check Script

Create a shell script for full quality checks:

```bash
#!/bin/bash
# check_quality.sh

echo "Running comprehensive code quality checks..."

echo "1. Flake8 (style check)..."
flake8 your_module.py || true

echo "2. Pylint (detailed analysis)..."
pylint your_module.py || true

echo "3. MyPy (type checking)..."
mypy your_module.py || true

echo "4. Bandit (security check)..."
bandit -r your_project/ || true

echo "5. Ruff (fast linting)..."
ruff check your_module.py || true

echo "Quality checks completed!"
```

## Integration

### Pre-commit Hook

Add to `.pre-commit-config.yaml`:

```yaml
repos:
  - repo: local
    hooks:
      - id: python-quality
        name: Python Quality Check
        entry: bash check_quality.sh
        language: system
        files: \.py$
```

### VS Code Settings

Add to `.vscode/settings.json`:

```json
{
  "python.linting.enabled": true,
  "python.linting.pylintEnabled": true,
  "python.linting.flake8Enabled": true,
  "python.linting.mypyEnabled": true,
  "python.linting.banditEnabled": true,
  "python.formatting.provider": "black"
}
```

## Tool Comparison

| Tool | Purpose | Speed | Best For |
|------|---------|-------|----------|
| Pylint | Comprehensive analysis | Slow | Deep code review |
| Flake8 | Style + errors | Fast | CI/CD pipelines |
| MyPy | Type checking | Medium | Type safety |
| Bandit | Security | Medium | Security audit |
| Ruff | Fast linting | Very Fast | Quick checks |
| OpenFactCheck | AI hallucination | Slow | AI code validation |

## Common Issues and Fixes

### Import Errors
```bash
# Fix missing imports
pip install --upgrade pylint mypy
```

### Type Checking Strict Mode
```bash
# Relax strict type checking
mypy your_module.py --ignore-missing-imports
```

### Security Warnings
```bash
# Ignore specific security issues
bandit -r your_project/ -x B413,B318
```

## Best Practices

1. **Run checks before commits**: Use pre-commit hooks
2. **Start with Ruff**: Fast feedback loop
3. **Add MyPy gradually**: Improves type coverage over time
4. **Check AI-generated code**: Always validate with hallucination detection
5. **Fix security issues first**: Prioritize Bandit findings
6. **Use incremental checks**: Don't check entire codebase every time

## Example Workflow

```python
# your_module.py
def calculate_total(items: list) -> float:
    total = 0.0
    for item in items:
        total += item.price * item.quantity
    return total

# Run checks
$ ruff check your_module.py  # Fast check
$ mypy your_module.py         # Type check
$ pylint your_module.py       # Full analysis
```

## Notes

- Use `|| true` in scripts to continue on errors
- Start with one tool, add others progressively
- Configure tools in `pyproject.toml` or `setup.cfg`
- Check project-specific rules in `.pylintrc`, `mypy.ini`
- AI hallucination detection is for AI-generated code validation
