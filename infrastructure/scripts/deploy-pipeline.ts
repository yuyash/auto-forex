import { execFileSync } from 'node:child_process';
import { resolve } from 'node:path';
import { resolveConfiguration, type EnvironmentConfiguration } from '../lib/config/environment';

export function pipelineDeployArguments(configuration: EnvironmentConfiguration, full: boolean): string[] {
  const args = [
    resolve('node_modules/aws-cdk/bin/cdk'),
    'deploy', 'AutoForexPipeline',
    '-c', 'target=pipeline',
  ];
  if (full) args.push('-c', 'bootstrapComplete=true');
  args.push('--profile', configuration.accounts.pipeline.profile);
  return args;
}

if (require.main === module) {
  const configuration = resolveConfiguration();
  execFileSync(process.execPath, pipelineDeployArguments(configuration, process.argv.includes('--full')), { stdio: 'inherit' });
}
