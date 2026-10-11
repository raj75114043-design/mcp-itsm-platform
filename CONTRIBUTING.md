# Contributing

1. `pip install -r requirements-dev.txt`
2. New tool: add an argument model and `ToolSpec` (scope, risk class, `untrusted_output` if it returns human-written text).
3. `make lint test eval`. If the tool contract changes intentionally, run `make contract` and explain it in the PR.
4. Security-suite failures and any `injection_followed` / `unapproved_pages_sent` above zero block a merge.
