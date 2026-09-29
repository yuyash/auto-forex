import { Stage, Tags, type StageProps } from 'aws-cdk-lib';
import type { Construct } from 'constructs';
import { type ApplicationEnvironment } from '../config/environment';
import { ApplicationStack } from '../stacks/application-stack';

export interface ApplicationStageProps extends StageProps {
  readonly environmentName: ApplicationEnvironment;
}

export class ApplicationStage extends Stage {
  constructor(scope: Construct, id: string, props: ApplicationStageProps) {
    super(scope, id, props);
    Tags.of(this).add('Environment', props.environmentName);

    const pascalCaseEnvironment = props.environmentName.charAt(0).toUpperCase() + props.environmentName.slice(1);
    new ApplicationStack(this, 'Application', {
      environmentName: props.environmentName,
      stackName: `AutoForex${pascalCaseEnvironment}Application`,
    });
  }
}
