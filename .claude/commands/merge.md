# /merge — CI Shepherd: Fix, Push, Watch, Merge

Automate the full merge workflow: stage and commit any unstaged changes, push, create or find the PR, watch CI, fix lint/test failures, and merge when green.

## Arguments
- `$ARGUMENTS` — Optional: PR number, branch name, or empty (auto-detect current branch's PR)

## Workflow

### 1. Detect Context
- Determine current branch and base branch (master/main)
- If a PR number is given in `$ARGUMENTS`, use that
- Otherwise, find or create a PR for the current branch

### 2. Stage & Push
- Check for unstaged/uncommitted changes
- If there are changes: stage them, commit with a descriptive message, push
- If clean: just ensure we're pushed to remote

### 3. Watch CI Loop
Enter a loop (max 10 iterations to prevent infinite loops):

  a. **Poll CI status** — use `gh pr checks <PR> --watch` with a timeout, or poll `gh pr view --json statusCheckRollup` every 30 seconds until all checks complete

  b. **If all checks pass** → break out of loop, proceed to merge

  c. **If checks fail** → analyze the failure:
     - Run `gh run view <run-id> --log-failed` to get the error output
     - Identify the failing step (Black, isort, flake8, pytest, etc.)
     - **For lint failures (Black/isort/flake8):**
       - Run the formatter/linter locally: `cd backend && python -m black . && python -m isort . && python -m flake8 .`
       - Fix any flake8 issues that are in files we changed (unused imports, docstring style, line length)
       - Commit fixes with message "Fix lint: <description>"
       - Push and restart the CI watch loop
     - **For test failures (pytest):**
       - Read the failing test output
       - Identify the root cause
       - Fix the code or test
       - Run `python -m pytest -x` locally to verify
       - Commit fixes with message "Fix test: <description>"
       - Push and restart the CI watch loop
     - **For unknown/unfixable failures:**
       - Report the error to the user and stop

### 4. Merge
- Once all checks are green, merge the PR: `gh pr merge <PR> --merge --delete-branch`
- Report success with the merge URL

## Important Rules
- Never force-push or amend commits
- Always run local lint/test before pushing fixes
- Maximum 10 fix-push-watch iterations to prevent infinite loops
- If the same error occurs twice in a row, stop and report to the user
- Always show the user what's happening at each stage
- Commit messages should end with the Co-Authored-By trailer
