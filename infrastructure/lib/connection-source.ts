import { type Artifact } from 'aws-cdk-lib/aws-codepipeline';
import { CodeStarConnectionsSourceAction, type Action } from 'aws-cdk-lib/aws-codepipeline-actions';
import { type IRole } from 'aws-cdk-lib/aws-iam';
import { CodePipelineSource, FileSet } from 'aws-cdk-lib/pipelines';

export interface ConnectionSourceProps {
  readonly owner: string;
  readonly repo: string;
  readonly branch: string;
  readonly connectionArn: string;
  readonly role: IRole;
}

/** Connection source with an explicit role supporting both IAM service prefixes. */
export class ConnectionSource extends CodePipelineSource {
  constructor(private readonly properties: ConnectionSourceProps) {
    super(`${properties.owner}/${properties.repo}`);
    this.configurePrimaryOutput(new FileSet('Source', this));
  }

  protected override getAction(output: Artifact, actionName: string, runOrder: number, variablesNamespace?: string): Action {
    return new CodeStarConnectionsSourceAction({
      ...this.properties,
      actionName,
      output,
      runOrder,
      triggerOnPush: true,
      ...(variablesNamespace === undefined ? {} : { variablesNamespace }),
    });
  }
}
