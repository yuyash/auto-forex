import { CfnOutput, Duration, RemovalPolicy, Stack, type StackProps } from 'aws-cdk-lib';
import { BuildSpec, LinuxBuildImage } from 'aws-cdk-lib/aws-codebuild';
import { CfnConnection } from 'aws-cdk-lib/aws-codeconnections';
import { PipelineType } from 'aws-cdk-lib/aws-codepipeline';
import { AccountPrincipal, PolicyStatement, Role } from 'aws-cdk-lib/aws-iam';
import { CodeBuildStep, CodePipeline, type IFileSetProducer } from 'aws-cdk-lib/pipelines';
import type { Construct } from 'constructs';
import {
  accountEnvironment,
  APPLICATION_ENVIRONMENTS,
  pipelineEnvironment,
  PROJECT_NAME,
  required,
  type EnvironmentConfiguration,
} from '../config/environment';
import { ApplicationStage } from '../stages/application-stage';
import packageMetadata from '../../package.json';
import { ConnectionSource } from '../connection-source';

export interface PipelineStackProps extends StackProps {
  readonly configuration: EnvironmentConfiguration;
  /** Enabled by CI after target bootstrap succeeds; false for first installation. */
  readonly deployApplications?: boolean;
}

/** GitHub main -> target bootstrap -> synthesis -> self-update -> alpha -> beta -> prod. */
export class PipelineStack extends Stack {
  constructor(scope: Construct, id: string, props: PipelineStackProps) {
    super(scope, id, {
      ...props,
      stackName: 'AutoForexPipeline',
      description: 'auto-forex GitHub delivery pipeline',
      analyticsReporting: false,
    });
    const configuration = props.configuration;
    const variables = pipelineEnvironment(configuration);
    const connection = new CfnConnection(this, 'GitHubConnection', {
      connectionName: `${PROJECT_NAME}-github`,
      providerType: 'GitHub',
      tags: [{ key: 'Project', value: PROJECT_NAME }],
    });
    connection.applyRemovalPolicy(RemovalPolicy.RETAIN);
    new CfnOutput(this, 'GitHubConnectionArn', { value: connection.attrConnectionArn });

    const sourceRole = new Role(this, 'SourceActionRole', {
      assumedBy: new AccountPrincipal(this.account),
    });
    // CDK's source action grants the legacy codestar-connections prefix. The
    // native CodeConnections resource also needs the current service prefix.
    sourceRole.addToPolicy(new PolicyStatement({
      actions: ['codeconnections:UseConnection'],
      resources: [connection.attrConnectionArn],
    }));
    const source = new ConnectionSource({
      owner: required(configuration.github.owner, 'AUTO_FOREX_GITHUB_OWNER'),
      repo: configuration.github.repo,
      branch: configuration.github.branch,
      connectionArn: connection.attrConnectionArn,
      role: sourceRole,
    });
    const synth = new CodeBuildStep('Synth', {
      // The upstream jsii interface models primaryOutput as an optional member;
      // Step exposes a getter returning FileSet | undefined. This assertion only
      // bridges that declaration mismatch under exactOptionalPropertyTypes.
      input: source as IFileSetProducer,
      projectName: 'auto-forex-synth',
      env: variables,
      buildEnvironment: { buildImage: LinuxBuildImage.STANDARD_7_0 },
      partialBuildSpec: BuildSpec.fromObject({ phases: { install: { 'runtime-versions': { nodejs: 22 } } } }),
      installCommands: ['cd "$CODEBUILD_SRC_DIR/infrastructure"', 'npm ci'],
      commands: [
        'cd "$CODEBUILD_SRC_DIR/infrastructure"',
        'npm run typecheck',
        'npm test',
        'npm run build',
        'npx cdk synth "**" --quiet --no-lookups -c target=pipeline -c bootstrapComplete=true',
      ],
      primaryOutputDirectory: 'infrastructure/cdk.out',
      timeout: Duration.hours(1),
    });
    const pipeline = new CodePipeline(this, 'Pipeline', {
      pipelineName: 'AutoForexPipeline',
      pipelineType: PipelineType.V2,
      synth: synth as IFileSetProducer,
      cliVersion: packageMetadata.devDependencies['aws-cdk'],
      crossAccountKeys: true,
      enableKeyRotation: true,
      codeBuildDefaults: {
        buildEnvironment: { buildImage: LinuxBuildImage.STANDARD_7_0 },
        partialBuildSpec: BuildSpec.fromObject({ phases: { install: { 'runtime-versions': { nodejs: 22 } } } }),
      },
    });
    // On first installation the target CDK roles do not exist yet. Add their
    // cross-account actions only in the assembly produced after bootstrap, so
    // the pipeline can create itself before it creates those target roles.
    if (props.deployApplications === true) {
      for (const environmentName of APPLICATION_ENVIRONMENTS) {
        pipeline.addStage(new ApplicationStage(this, environmentName, {
          environmentName,
          env: accountEnvironment(configuration, environmentName),
        }));
      }
    }
  }
}
