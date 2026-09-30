#!/usr/bin/env node
import { App, Tags } from 'aws-cdk-lib';
import { pipelineAccountEnvironment, PROJECT_NAME, resolveConfiguration } from '../lib/config/environment';
import { PipelineStack } from '../lib/stacks/pipeline-stack';

const app = new App();
const configuration = resolveConfiguration();
const target: string = app.node.tryGetContext('target') ?? 'pipeline';
if (!['pipeline'].includes(target)) {
  throw new Error('target must be pipeline.');
}
Tags.of(app).add('Project', PROJECT_NAME);

// Keep synthesis deterministic in CodeBuild, where context lookups are disabled.
for (const account of [configuration.accounts.dev.accountId, configuration.accounts.prod.accountId]) {
  if (account !== null) {
    app.node.setContext(
      `availability-zones:account=${account}:region=${configuration.region}`,
      [`${configuration.region}a`, `${configuration.region}b`],
    );
  }
}

new PipelineStack(app, 'AutoForexPipeline', {
  configuration,
  env: pipelineAccountEnvironment(configuration),
  deployApplications: app.node.tryGetContext('bootstrapComplete') === 'true',
});
app.synth();
