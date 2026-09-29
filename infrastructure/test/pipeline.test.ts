import assert from 'node:assert/strict';
import { test } from 'node:test';
import { join } from 'node:path';
import { App } from 'aws-cdk-lib';
import { Match, Template } from 'aws-cdk-lib/assertions';
import { resolveConfiguration } from '../lib/config/environment';
import { PipelineStack } from '../lib/stacks/pipeline-stack';
import { bootstrapArguments, bootstrapTargets, pipelineBootstrapTarget } from '../scripts/bootstrap-targets';
import { pipelineDeployArguments } from '../scripts/deploy-pipeline';

const configuration = () => resolveConfiguration({ configFile: join(__dirname, 'fixtures/empty.yaml'), environment: {
  AUTO_FOREX_ACCOUNT_PIPELINE: '444444444444',
  AUTO_FOREX_ACCOUNT_DEV: '111111111111',
  AUTO_FOREX_ACCOUNT_PROD: '333333333333',
  AUTO_FOREX_GITHUB_OWNER: 'example',
  AUTO_FOREX_GITHUB_REPO: 'auto-forex',
  AUTO_FOREX_REGION: 'us-west-2',
} });

test('GitHub connection triggers main and deploys dev stages before production', () => {
  const config = configuration();
  const stack = new PipelineStack(new App(), 'PipelineTest', {
    env: { account: config.accounts.pipeline.accountId!, region: config.region }, configuration: config,
    deployApplications: true,
  });
  const template = Template.fromStack(stack);
  template.resourceCountIs('AWS::CodeConnections::Connection', 1);
  template.resourceCountIs('AWS::CodeConnections::Host', 0);
  template.hasResourceProperties('AWS::CodeConnections::Connection', { ProviderType: 'GitHub' });
  template.hasResourceProperties('AWS::CodePipeline::Pipeline', { PipelineType: 'V2' });
  template.hasResourceProperties('AWS::IAM::Policy', {
    PolicyDocument: { Statement: Match.arrayWith([
      Match.objectLike({ Action: 'codeconnections:UseConnection', Resource: { 'Fn::GetAtt': ['GitHubConnection', 'ConnectionArn'] } }),
      Match.objectLike({ Action: 'codestar-connections:UseConnection', Resource: { 'Fn::GetAtt': ['GitHubConnection', 'ConnectionArn'] } }),
    ]) },
  });
  const projects = Object.values(template.findResources('AWS::CodeBuild::Project'));
  const synth = projects.find((project) => project.Properties.Name === 'auto-forex-synth');
  assert.ok(synth);
  const spec = JSON.parse(synth.Properties.Source.BuildSpec);
  assert.equal(spec.artifacts['base-directory'], 'infrastructure/cdk.out');
  assert.equal(spec.phases.install['runtime-versions'].nodejs, 22);
  const commands: string[] = spec.phases.build.commands;
  assert.ok(commands.includes('cd "$CODEBUILD_SRC_DIR/infrastructure"'));
  assert.ok(commands.some((command) => command.includes('-c bootstrapComplete=true')));
  assert.ok(synth.Properties.Environment.EnvironmentVariables.some((entry: { Name: string; Value: string }) => entry.Name === 'AUTO_FOREX_ACCOUNT_DEV' && entry.Value === '111111111111'));
  assert.ok(!synth.Properties.Environment.EnvironmentVariables.some((entry: { Name: string }) => entry.Name.startsWith('AUTO_FOREX_PROFILE_')));
  const pipeline = Object.values(template.findResources('AWS::CodePipeline::Pipeline'))[0]!;
  const stages = pipeline.Properties.Stages as { Name: string; Actions: { Configuration: Record<string, unknown> }[] }[];
  const source = stages[0]!.Actions[0]!.Configuration;
  assert.equal(source.FullRepositoryId, 'example/auto-forex');
  assert.equal(source.BranchName, 'main');
  assert.equal(source.DetectChanges, true);
  const names = stages.map((stage) => stage.Name);
  assert.ok(names.indexOf('alpha') < names.indexOf('beta'));
  assert.ok(names.indexOf('beta') < names.indexOf('prod'));
  assert.ok(names.indexOf('alpha') > 0);
});

test('first installation has no cross-account deploy actions before target roles exist', () => {
  const config = configuration();
  const stack = new PipelineStack(new App(), 'InitialPipelineTest', {
    env: { account: config.accounts.pipeline.accountId!, region: config.region }, configuration: config,
  });
  const template = Template.fromStack(stack);
  const pipeline = Object.values(template.findResources('AWS::CodePipeline::Pipeline'))[0]!;
  assert.deepEqual(pipeline.Properties.Stages.map((stage: { Name: string }) => stage.Name), ['Source', 'Build', 'UpdatePipeline']);
  // The initial artifact key policy must not contain principals for as-yet
  // nonexistent target CDK deployment roles.
  const keyPolicies = JSON.stringify(template.findResources('AWS::KMS::Key'));
  assert.ok(!/cdk-hnb659fds-deploy-role-(111111111111|333333333333)/.test(keyPolicies));
});

test('bootstrap uses each local profile and trusts the pipeline account', () => {
  const config = configuration();
  const targets = bootstrapTargets(config);
  assert.equal(targets.length, 2);
  assert.equal(targets[0]!.profile, 'auto-forex-dev');
  const arguments_ = bootstrapArguments(targets[0]!);
  assert.equal(arguments_[1], 'bootstrap');
  assert.ok(arguments_.includes('aws://111111111111/us-west-2'));
  assert.ok(arguments_.includes('--trust'));
  assert.ok(arguments_.includes('444444444444'));
  assert.ok(arguments_.includes('--profile'));
  assert.ok(arguments_.includes('auto-forex-dev'));
  assert.ok(!arguments_.includes('deploy'));
  const pipelineArguments = bootstrapArguments(pipelineBootstrapTarget(config));
  assert.ok(pipelineArguments.includes('auto-forex-pipeline'));
  assert.ok(!pipelineArguments.includes('--trust'));
  assert.deepEqual(bootstrapTargets({ ...config, bootstrap: { ...config.bootstrap, enabled: false } }), []);
});

test('pipeline deployment always uses the configured pipeline profile', () => {
  const config = configuration();
  const initial = pipelineDeployArguments(config, false);
  assert.ok(initial.includes('auto-forex-pipeline'));
  assert.ok(!initial.includes('bootstrapComplete=true'));
  const full = pipelineDeployArguments(config, true);
  assert.ok(full.includes('bootstrapComplete=true'));
  assert.equal(full.at(-1), 'auto-forex-pipeline');
});
