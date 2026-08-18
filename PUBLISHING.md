# Publishing Python Packages

The six public distributions are published from
`.github/workflows/publish-packages.yml` with PyPI Trusted Publishing. No
long-lived PyPI API token is stored in GitHub.

## Publishing switch

Publishing is disabled by default. Release and manually dispatched workflows
still build and validate every distribution, but the `Publish to PyPI` job runs
only when the repository variable `ENABLE_PYPI_PUBLISHING` is set to `true`.

To enable publishing, create or update that repository variable under
**Settings**, **Secrets and variables**, **Actions**, **Variables**. To pause
publishing again, delete the variable or set it to any value other than `true`.

## One-time setup

1. Create a GitHub environment named `pypi` for this repository. Add required
   reviewers if production publication should require approval.
2. In the PyPI account publishing settings, create one pending Trusted
   Publisher for each project:

   - `auto-forex-core`
   - `auto-forex-protobuf`
   - `auto-forex-snowball`
   - `auto-forex-aws`
   - `auto-forex-oanda`
   - `auto-forex-server`

3. Use the same publisher settings for each project:

   - Owner: `yuyash`
   - Repository: `auto-forex-v2`
   - Workflow: `publish-packages.yml`
   - Environment: `pypi`

Pending publishers allow the workflow to create a project on its first
publication. PyPI project names and released versions are immutable, so verify
this metadata before the first release.

## Release procedure

1. Wait for the automated package-version pull request to pass all package
   tests and be squash-merged by the version workflow.
2. Create a GitHub Release from the versioned commit on `main`.
3. Approve the `pypi` environment deployment if reviewers are configured.
4. Confirm the `Publish Python packages` workflow succeeds.

The workflow builds every public package without workspace source overrides,
validates wheel and sdist metadata, and tests both the base server and
`auto-forex-server[all]`. It then publishes in dependency order. A package
version that already exists on PyPI is skipped, making a rerun safe after a
partial release.

Never delete or replace a published artifact. Correct a release by increasing
the affected package version and publishing a new GitHub Release.
