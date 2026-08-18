# auto-forex-v2

This is a web application for algorithmic forex trading.

## Published packages

The public Python distributions share the `autoforex` import namespace:

| Distribution | Import | Purpose |
| --- | --- | --- |
| `auto-forex-core` | `autoforex.core` | Domain models and execution engine |
| `auto-forex-protobuf` | `autoforex.protobuf` | Versioned gRPC contracts |
| `auto-forex-snowball` | `autoforex.snowball` | Snowball strategy |
| `auto-forex-aws` | `autoforex.aws` | Optional AWS adapters |
| `auto-forex-oanda` | `autoforex.oanda` | Optional OANDA adapter |
| `auto-forex-server` | `autoforex.server` | Long-running gRPC server |

Install the server without cloud or broker adapters:

```bash
pip install auto-forex-server
```

Select optional features explicitly:

```bash
pip install "auto-forex-server[aws]"
pip install "auto-forex-server[oanda]"
pip install "auto-forex-server[aws,oanda,postgresql]"
```

`auto-forex-core`, `auto-forex-protobuf`, and `auto-forex-snowball` are
installed automatically with the server. Optional features fail with an
actionable installation command when their extra is not installed.

## Development

Synchronize every package into the shared environment:

```bash
uv sync --all-packages
```

Run a command for one package:

```bash
uv run --all-packages --directory src/core pytest
```

## Continuous integration

Pull requests run package tests as separate unit, integration, and E2E jobs.
Packages whose tests are not split into subdirectories currently run their
`tests` directory as unit tests.

The OANDA E2E job runs both read-only and mutating tests in CI. It requires
`OANDA_ACCOUNT_ID` (or `OANDA_ACCOUNT_NAME`) and `OANDA_ACCESS_TOKEN` secrets.
`OANDA_ENVIRONMENT` defaults to `practice`, and `OANDA_MUTATING_E2E_UNITS`
defaults to `1`. The workflow fails before testing when credentials are missing
or the environment is not `practice`.

The `oanda` package E2E suite must exercise every public OANDA Gateway endpoint.
An endpoint coverage test compares the Gateway clients with the endpoint
declarations on E2E tests so that adding an endpoint without E2E coverage fails
CI.

After all package tests pass on a push to `main`, every package with changes
under `src/<package>` receives a patch version bump. The workflow updates that
package's `pyproject.toml` and `uv.lock` on
`automation/package-version-bumps`, then creates or updates a pull request.
The same workflow starts package tests for the exact version commit, waits for
them to pass, and squash-merges that unchanged commit automatically. Keeping
test dispatch, completion tracking, and merging in one workflow avoids relying
on chained workflow events from `github-actions[bot]`.
Under **Settings > Actions > General**, enable read and write workflow
permissions and allow GitHub Actions to create pull requests.

Protect `main` with a ruleset that requires pull requests. The version workflow
only pushes to its automation branch and never pushes directly to `main`.

GitHub Releases build and validate all public package distributions. Publishing
to PyPI is disabled unless the repository variable
`ENABLE_PYPI_PUBLISHING` is explicitly set to `true`. See
[PUBLISHING.md](PUBLISHING.md) for the one-time setup, enablement, and release
procedure.
