import { execFileSync } from 'node:child_process';
import { resolve } from 'node:path';
import { required, resolveConfiguration, type AwsAccount, type EnvironmentConfiguration } from '../lib/config/environment';

export interface BootstrapTarget {
  readonly name: AwsAccount;
  readonly accountId: string;
  readonly profile: string;
  readonly region: string;
  readonly executionPolicyArn: string;
  readonly trustedAccountId?: string;
}

export function bootstrapTargets(configuration: EnvironmentConfiguration): BootstrapTarget[] {
  if (!configuration.bootstrap.enabled) return [];
  const pipelineAccountId = required(configuration.accounts.pipeline.accountId, 'AUTO_FOREX_ACCOUNT_PIPELINE');
  return (['dev', 'prod'] as const).map((name) => ({
    name,
    accountId: required(configuration.accounts[name].accountId, `AUTO_FOREX_ACCOUNT_${name.toUpperCase()}`),
    profile: configuration.accounts[name].profile,
    region: configuration.region,
    executionPolicyArn: configuration.bootstrap.executionPolicyArn,
    trustedAccountId: pipelineAccountId,
  }));
}

export function pipelineBootstrapTarget(configuration: EnvironmentConfiguration): BootstrapTarget {
  return {
    name: 'pipeline',
    accountId: required(configuration.accounts.pipeline.accountId, 'AUTO_FOREX_ACCOUNT_PIPELINE'),
    profile: configuration.accounts.pipeline.profile,
    region: configuration.region,
    executionPolicyArn: configuration.bootstrap.executionPolicyArn,
  };
}

export function bootstrapArguments(target: BootstrapTarget): string[] {
  const args = [
    resolve('node_modules/aws-cdk/bin/cdk'),
    'bootstrap', `aws://${target.accountId}/${target.region}`,
    '--profile', target.profile,
    '--termination-protection',
    '--cloudformation-execution-policies', target.executionPolicyArn,
  ];
  if (target.trustedAccountId !== undefined) args.push('--trust', target.trustedAccountId);
  return args;
}

if (require.main === module) {
  const configuration = resolveConfiguration();
  const targets = process.argv[2] === 'pipeline' ? [pipelineBootstrapTarget(configuration)] : bootstrapTargets(configuration);
  for (const target of targets) execFileSync(process.execPath, bootstrapArguments(target), { stdio: 'inherit' });
}
