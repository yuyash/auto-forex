import { Stack, type StackProps } from 'aws-cdk-lib';
import { StringParameter } from 'aws-cdk-lib/aws-ssm';
import type { Construct } from 'constructs';
import { type ApplicationEnvironment } from '../config/environment';

export interface ApplicationStackProps extends StackProps {
  readonly environmentName: ApplicationEnvironment;
}

/** Shared workload boundary, instantiated separately for alpha, beta and prod. */
export class ApplicationStack extends Stack {
  constructor(scope: Construct, id: string, props: ApplicationStackProps) {
    super(scope, id, {
      ...props,
      description: 'auto-forex application environment',
      analyticsReporting: false,
    });

    new StringParameter(this, 'EnvironmentName', {
      parameterName: `/auto-forex/${props.environmentName}/deployment/environment`,
      stringValue: props.environmentName,
      description: 'Deployment environment for auto-forex application resources',
    });
    // Application API, queues, storage and Python 3.11 Lambdas are added here.
  }
}
