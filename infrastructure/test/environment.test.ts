import assert from 'node:assert/strict';
import { mkdtempSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { test } from 'node:test';
import { accountEnvironment, pipelineAccountEnvironment, pipelineEnvironment, resolveConfiguration } from '../lib/config/environment';

function withYaml(contents: string, run: (file: string) => void): void {
  const dir = mkdtempSync(join(tmpdir(), 'auto-forex-config-'));
  const file = join(dir, 'config.yaml');
  writeFileSync(file, contents);
  try { run(file); } finally { rmSync(dir, { recursive: true, force: true }); }
}

test('environment values override YAML; YAML overrides profile defaults', () => {
  withYaml('region: eu-west-1\naccounts:\n  dev:\n    accountId: "012345678901"\n', (configFile) => {
    const fromYaml = resolveConfiguration({ configFile, environment: {} });
    assert.equal(fromYaml.region, 'eu-west-1');
    assert.equal(fromYaml.accounts.dev.accountId, '012345678901');
    assert.equal(fromYaml.accounts.dev.profile, 'auto-forex-dev');
    const overridden = resolveConfiguration({ configFile, environment: {
      AUTO_FOREX_REGION: 'us-east-2',
      AUTO_FOREX_ACCOUNT_DEV: '111111111111',
      AUTO_FOREX_PROFILE_DEV: 'custom-dev',
    } });
    assert.equal(overridden.region, 'us-east-2');
    assert.equal(overridden.accounts.dev.accountId, '111111111111');
    assert.equal(overridden.accounts.dev.profile, 'custom-dev');
  });
});

test('YAML interpolation supports environment values and defaults without executing code', () => {
  withYaml('region: ${REGION:-us-west-2}\naccounts:\n  dev:\n    accountId: "${DEV_ACCOUNT}"\n', (configFile) => {
    assert.throws(() => resolveConfiguration({ configFile, environment: {} }), /Missing environment variable DEV_ACCOUNT/);
    const config = resolveConfiguration({ configFile, environment: { DEV_ACCOUNT: '012345678901' } });
    assert.equal(config.accounts.dev.accountId, '012345678901');
    assert.equal(config.region, 'us-west-2');
  });
});

test('configuration rejects malformed YAML, unquoted IDs, invalid flags and duplicate accounts', () => {
  for (const contents of ['[', '[]', 'accounts:\n  dev:\n    accountId: 123456789012\n']) {
    withYaml(contents, (configFile) => assert.throws(() => resolveConfiguration({ configFile, environment: {} })));
  }
  withYaml('{}', (configFile) => {
    assert.throws(() => resolveConfiguration({ configFile, environment: { AUTO_FOREX_BOOTSTRAP_ENABLED: 'yes' } }), /true or false/);
    assert.throws(() => resolveConfiguration({ configFile, environment: { AUTO_FOREX_ACCOUNT_DEV: '1234' } }), /12-digit/);
    assert.throws(() => resolveConfiguration({ configFile, environment: {
      AUTO_FOREX_ACCOUNT_DEV: '111111111111',
      AUTO_FOREX_ACCOUNT_PROD: '111111111111',
    } }), /different AWS accounts/);
  });
});

test('deployment environments map alpha and beta to dev, and prod to prod', () => {
  withYaml('{}', (configFile) => {
    const configuration = resolveConfiguration({ configFile, environment: {
      AUTO_FOREX_ACCOUNT_DEV: '111111111111',
      AUTO_FOREX_ACCOUNT_PROD: '222222222222',
      AUTO_FOREX_ACCOUNT_PIPELINE: '333333333333',
      AUTO_FOREX_GITHUB_OWNER: 'example',
    } });
    assert.equal(accountEnvironment(configuration, 'alpha').account, '111111111111');
    assert.equal(accountEnvironment(configuration, 'beta').account, '111111111111');
    assert.equal(accountEnvironment(configuration, 'prod').account, '222222222222');
    assert.equal(pipelineAccountEnvironment(configuration).account, '333333333333');
    const ci = pipelineEnvironment(configuration);
    assert.equal(ci.AUTO_FOREX_ACCOUNT_DEV, '111111111111');
    assert.equal(ci.AUTO_FOREX_PROFILE_DEV, undefined);
  });
});

test('explicit configuration files must exist and deployment account IDs are required', () => {
  assert.throws(() => resolveConfiguration({ configFile: '/does-not-exist/auto-forex.yaml', environment: {} }), /ENOENT/);
  withYaml('{}', (configFile) => {
    const configuration = resolveConfiguration({ configFile, environment: {} });
    assert.throws(() => accountEnvironment(configuration, 'alpha'), /AUTO_FOREX_ACCOUNT_DEV/);
    assert.throws(() => pipelineEnvironment(configuration), /AUTO_FOREX_GITHUB_OWNER/);
  });
});
