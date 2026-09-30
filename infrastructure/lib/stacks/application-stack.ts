import { ArnFormat, CfnOutput, Duration, RemovalPolicy, Stack, type StackProps } from 'aws-cdk-lib';
import {
  CfnApplication,
  CfnConfigurationProfile,
  CfnDeployment,
  CfnEnvironment,
  CfnHostedConfigurationVersion,
} from 'aws-cdk-lib/aws-appconfig';
import { HttpApi, HttpMethod } from 'aws-cdk-lib/aws-apigatewayv2';
import { HttpJwtAuthorizer } from 'aws-cdk-lib/aws-apigatewayv2-authorizers';
import { HttpLambdaIntegration } from 'aws-cdk-lib/aws-apigatewayv2-integrations';
import { ClientAttributes, UserPool, UserPoolOperation } from 'aws-cdk-lib/aws-cognito';
import { AttributeType, BillingMode, ProjectionType, Table, type ITable } from 'aws-cdk-lib/aws-dynamodb';
import { Platform } from 'aws-cdk-lib/aws-ecr-assets';
import { Peer, Port, SecurityGroup, SubnetType, Vpc, type IVpc } from 'aws-cdk-lib/aws-ec2';
import {
  AwsLogDriver,
  Cluster,
  ContainerImage,
  CpuArchitecture,
  FargateService,
  FargateTaskDefinition,
  OperatingSystemFamily,
  type ICluster,
} from 'aws-cdk-lib/aws-ecs';
import { PolicyStatement } from 'aws-cdk-lib/aws-iam';
import { Architecture, Code, Function, Runtime } from 'aws-cdk-lib/aws-lambda';
import { SqsEventSource } from 'aws-cdk-lib/aws-lambda-event-sources';
import { LogGroup, RetentionDays } from 'aws-cdk-lib/aws-logs';
import { Queue } from 'aws-cdk-lib/aws-sqs';
import { StringParameter } from 'aws-cdk-lib/aws-ssm';
import type { Construct } from 'constructs';
import { resolve } from 'node:path';
import { type ApplicationEnvironment } from '../config/environment';

export interface ApplicationStackProps extends StackProps {
  readonly environmentName: ApplicationEnvironment;
}

/** OANDA stream -> Fargate ARM -> SQS FIFO -> Lambda -> DynamoDB Prices. */
export class ApplicationStack extends Stack {
  constructor(scope: Construct, id: string, props: ApplicationStackProps) {
    super(scope, id, {
      ...props,
      description: 'auto-forex market price ingestion',
      analyticsReporting: false,
    });
    const environmentName = props.environmentName;
    const backendDirectory = resolve(__dirname, '../../../backend');

    new StringParameter(this, 'EnvironmentName', {
      parameterName: `/auto-forex/${environmentName}/deployment/environment`,
      stringValue: environmentName,
      description: 'Deployment environment for auto-forex application resources',
    });

    const pricesTable = (environmentName === 'beta'
      ? Table.fromTableName(this, 'Prices', 'Prices')
      : new Table(this, 'Prices', {
        tableName: 'Prices',
        partitionKey: { name: 'symbol', type: AttributeType.STRING },
        sortKey: { name: 'created_at', type: AttributeType.STRING },
        billingMode: BillingMode.PAY_PER_REQUEST,
        pointInTimeRecoverySpecification: { pointInTimeRecoveryEnabled: true },
        removalPolicy: RemovalPolicy.RETAIN,
      })) as ITable;

    let usersTable: ITable;
    if (environmentName === 'beta') {
      usersTable = Table.fromTableName(this, 'Users', 'Users');
    } else {
      const table = new Table(this, 'Users', {
        tableName: 'Users',
        partitionKey: { name: 'user_id', type: AttributeType.STRING },
        billingMode: BillingMode.PAY_PER_REQUEST,
        pointInTimeRecoverySpecification: { pointInTimeRecoveryEnabled: true },
        removalPolicy: RemovalPolicy.RETAIN,
      });
      table.addGlobalSecondaryIndex({
        indexName: 'stream_status-index',
        partitionKey: { name: 'stream_status', type: AttributeType.STRING },
        sortKey: { name: 'user_id', type: AttributeType.STRING },
        projectionType: ProjectionType.ALL,
      });
      usersTable = table as ITable;
    }

    const deadLetterQueue = new Queue(this, 'PriceDeadLetterQueue', {
      queueName: `auto-forex-${environmentName}-price-dlq.fifo`,
      fifo: true,
      retentionPeriod: Duration.days(14),
      enforceSSL: true,
    });
    const priceQueue = new Queue(this, 'PriceQueue', {
      queueName: `auto-forex-${environmentName}-prices.fifo`,
      fifo: true,
      contentBasedDeduplication: false,
      visibilityTimeout: Duration.minutes(1),
      retentionPeriod: Duration.days(4),
      enforceSSL: true,
      deadLetterQueue: { queue: deadLetterQueue, maxReceiveCount: 5 },
    });

    const priceConsumerName = `auto-forex-${environmentName}-price-consumer`;
    const priceConsumerLogGroup = new LogGroup(this, 'PriceConsumerLogs', {
      logGroupName: `/aws/lambda/${priceConsumerName}`,
      retention: RetentionDays.ONE_WEEK,
      removalPolicy: RemovalPolicy.DESTROY,
    });
    const priceConsumer = new Function(this, 'PriceConsumer', {
      functionName: priceConsumerName,
      runtime: Runtime.PYTHON_3_11,
      architecture: Architecture.ARM_64,
      handler: 'autoforex.handlers.prices.handler',
      code: Code.fromAsset(resolve(backendDirectory, 'src')),
      memorySize: 256,
      timeout: Duration.seconds(30),
      environment: { PRICES_TABLE_NAME: pricesTable.tableName },
      logGroup: priceConsumerLogGroup,
    });
    priceConsumer.addEventSource(new SqsEventSource(priceQueue, {
      batchSize: 10,
      reportBatchItemFailures: true,
    }));
    pricesTable.grantWriteData(priceConsumer);

    const userPool = new UserPool(this, 'UserPool', {
      userPoolName: `auto-forex-${environmentName}-users`,
      selfSignUpEnabled: true,
      autoVerify: { email: true },
      signInAliases: { email: true },
      standardAttributes: { email: { required: true, mutable: true } },
      removalPolicy: RemovalPolicy.RETAIN,
    });
    const clientAttributes = new ClientAttributes().withStandardAttributes({
      email: true,
      emailVerified: true,
    });
    const userPoolClient = userPool.addClient('ApplicationClient', {
      userPoolClientName: `auto-forex-${environmentName}`,
      generateSecret: false,
      disableOAuth: true,
      authFlows: { userPassword: true, userSrp: true },
      preventUserExistenceErrors: true,
      readAttributes: clientAttributes,
      writeAttributes: new ClientAttributes().withStandardAttributes({ email: true }),
    });
    const userRegistrationName = `auto-forex-${environmentName}-user-registration`;
    const userRegistration = new Function(this, 'UserRegistration', {
      functionName: userRegistrationName,
      runtime: Runtime.PYTHON_3_11,
      architecture: Architecture.ARM_64,
      handler: 'autoforex.handlers.users.handler',
      code: Code.fromAsset(resolve(backendDirectory, 'src')),
      memorySize: 128,
      timeout: Duration.seconds(10),
      environment: {
        USERS_TABLE_NAME: usersTable.tableName,
        DEPLOYMENT_ENVIRONMENT: environmentName,
      },
      logGroup: new LogGroup(this, 'UserRegistrationLogs', {
        logGroupName: `/aws/lambda/${userRegistrationName}`,
        retention: RetentionDays.ONE_WEEK,
        removalPolicy: RemovalPolicy.DESTROY,
      }),
    });
    usersTable.grantWriteData(userRegistration);
    userPool.addTrigger(UserPoolOperation.POST_CONFIRMATION, userRegistration);

    const api = new HttpApi(this, 'Api', {
      apiName: `auto-forex-${environmentName}`,
      createDefaultStage: true,
    });
    const jwtAuthorizer = new HttpJwtAuthorizer(
      'JwtAuthorizer',
      userPool.userPoolProviderUrl,
      { jwtAudience: [userPoolClient.userPoolClientId] },
    );
    const apiFunction = (id: string, handler: string): Function => new Function(this, id, {
      functionName: `auto-forex-${environmentName}-${id.toLowerCase()}`,
      runtime: Runtime.PYTHON_3_11,
      architecture: Architecture.ARM_64,
      handler,
      code: Code.fromAsset(resolve(backendDirectory, 'src')),
      memorySize: 128,
      timeout: Duration.seconds(10),
      environment: {
        USER_POOL_CLIENT_ID: userPoolClient.userPoolClientId,
        USERS_TABLE_NAME: usersTable.tableName,
        DEPLOYMENT_ENVIRONMENT: environmentName,
      },
      logGroup: new LogGroup(this, `${id}Logs`, {
        logGroupName: `/aws/lambda/auto-forex-${environmentName}-${id.toLowerCase()}`,
        retention: RetentionDays.ONE_WEEK,
        removalPolicy: RemovalPolicy.DESTROY,
      }),
    });

    const signUp = apiFunction('SignUp', 'autoforex.handlers.api.users.signup.handler');
    const login = apiFunction('Login', 'autoforex.handlers.api.auth.login.handler');
    const getCurrentUser = apiFunction('GetCurrentUser', 'autoforex.handlers.api.users.me.handler');
    const registerOandaToken = apiFunction(
      'RegisterOandaToken',
      'autoforex.handlers.api.users.oanda_token.handler',
    );
    usersTable.grantReadData(getCurrentUser);
    usersTable.grantReadWriteData(registerOandaToken);
    registerOandaToken.addToRolePolicy(new PolicyStatement({
      actions: [
        'secretsmanager:CreateSecret',
        'secretsmanager:PutSecretValue',
        'secretsmanager:TagResource',
      ],
      resources: [this.formatArn({
        service: 'secretsmanager',
        resource: 'secret',
        resourceName: `auto-forex/${environmentName}/oanda/*`,
        arnFormat: ArnFormat.COLON_RESOURCE_NAME,
      })],
    }));

    api.addRoutes({
      path: '/users/signup',
      methods: [HttpMethod.POST],
      integration: new HttpLambdaIntegration('SignUpIntegration', signUp),
    });
    api.addRoutes({
      path: '/auth/login',
      methods: [HttpMethod.POST],
      integration: new HttpLambdaIntegration('LoginIntegration', login),
    });
    api.addRoutes({
      path: '/users/me',
      methods: [HttpMethod.GET],
      integration: new HttpLambdaIntegration('GetCurrentUserIntegration', getCurrentUser),
      authorizer: jwtAuthorizer,
    });
    api.addRoutes({
      path: '/users/me/oanda-token',
      methods: [HttpMethod.PUT],
      integration: new HttpLambdaIntegration('RegisterOandaTokenIntegration', registerOandaToken),
      authorizer: jwtAuthorizer,
    });

    const appConfigApplication = new CfnApplication(this, 'StreamConfigApplication', {
      name: `auto-forex-${environmentName}`,
      description: 'OANDA price stream settings',
    });
    const appConfigEnvironment = new CfnEnvironment(this, 'StreamConfigEnvironment', {
      applicationId: appConfigApplication.ref,
      name: environmentName,
    });
    const configurationProfile = new CfnConfigurationProfile(this, 'StreamConfigurationProfile', {
      applicationId: appConfigApplication.ref,
      name: 'price-stream',
      locationUri: 'hosted',
      type: 'AWS.Freeform',
      validators: [{
        type: 'JSON_SCHEMA',
        content: JSON.stringify({
          type: 'object',
          additionalProperties: false,
          required: ['ingestion_enabled', 'reconnect_max_delay_seconds'],
          properties: {
            ingestion_enabled: { type: 'boolean' },
            reconnect_max_delay_seconds: { type: 'integer', minimum: 1, maximum: 300 },
          },
        }),
      }],
    });
    const initialConfiguration = new CfnHostedConfigurationVersion(this, 'InitialStreamConfiguration', {
      applicationId: appConfigApplication.ref,
      configurationProfileId: configurationProfile.ref,
      contentType: 'application/json',
      content: JSON.stringify({
        ingestion_enabled: false,
        reconnect_max_delay_seconds: 30,
      }),
      description: 'Safe disabled configuration; create a new hosted version to enable streaming.',
    });
    new CfnDeployment(this, 'InitialStreamConfigurationDeployment', {
      applicationId: appConfigApplication.ref,
      environmentId: appConfigEnvironment.ref,
      configurationProfileId: configurationProfile.ref,
      configurationVersion: initialConfiguration.ref,
      deploymentStrategyId: 'AppConfig.AllAtOnce',
    });

    const vpc = new Vpc(this, 'IngestionVpc', {
      vpcName: `auto-forex-${environmentName}`,
      availabilityZones: [`${this.region}a`, `${this.region}b`],
      natGateways: 0,
      subnetConfiguration: [{ name: 'public', subnetType: SubnetType.PUBLIC }],
    });
    const cluster = new Cluster(this, 'IngestionCluster', { vpc: vpc as IVpc });
    const taskDefinition = new FargateTaskDefinition(this, 'IngestionTask', {
      cpu: 256,
      memoryLimitMiB: 512,
      runtimePlatform: {
        cpuArchitecture: CpuArchitecture.ARM64,
        operatingSystemFamily: OperatingSystemFamily.LINUX,
      },
    });
    taskDefinition.addContainer('Ingestion', {
      containerName: 'price-ingestion',
      image: ContainerImage.fromAsset(backendDirectory, { platform: Platform.LINUX_ARM64 }),
      logging: new AwsLogDriver({
        streamPrefix: `auto-forex-${environmentName}`,
        logRetention: RetentionDays.ONE_WEEK,
      }),
      environment: {
        APPCONFIG_APPLICATION_ID: appConfigApplication.ref,
        APPCONFIG_ENVIRONMENT_ID: appConfigEnvironment.ref,
        APPCONFIG_PROFILE_ID: configurationProfile.ref,
        USERS_TABLE_NAME: usersTable.tableName,
        DEPLOYMENT_ENVIRONMENT: environmentName,
        PRICE_QUEUE_URL: priceQueue.queueUrl,
      },
      healthCheck: {
        command: ['CMD-SHELL', 'python -c "import os; os.kill(1, 0)"'],
        interval: Duration.seconds(30),
        timeout: Duration.seconds(5),
        retries: 3,
        startPeriod: Duration.seconds(30),
      },
    });
    priceQueue.grantSendMessages(taskDefinition.taskRole);
    taskDefinition.taskRole.addToPrincipalPolicy(new PolicyStatement({
      actions: ['dynamodb:Query'],
      resources: [`${usersTable.tableArn}/index/stream_status-index`],
    }));
    taskDefinition.taskRole.addToPrincipalPolicy(new PolicyStatement({
      actions: ['secretsmanager:GetSecretValue'],
      resources: [this.formatArn({
        service: 'secretsmanager',
        resource: 'secret',
        resourceName: `auto-forex/${environmentName}/oanda/*`,
        arnFormat: ArnFormat.COLON_RESOURCE_NAME,
      })],
    }));
    taskDefinition.taskRole.addToPrincipalPolicy(new PolicyStatement({
      actions: ['appconfig:StartConfigurationSession', 'appconfig:GetLatestConfiguration'],
      resources: [this.formatArn({
        service: 'appconfig',
        resource: 'application',
        resourceName: `${appConfigApplication.ref}/environment/${appConfigEnvironment.ref}/configuration/${configurationProfile.ref}`,
      })],
    }));

    const securityGroup = new SecurityGroup(this, 'IngestionSecurityGroup', {
      vpc: vpc as IVpc,
      allowAllOutbound: false,
      description: 'Outbound HTTPS only for OANDA and AWS public APIs',
    });
    securityGroup.addEgressRule(Peer.anyIpv4(), Port.tcp(443), 'HTTPS');
    new FargateService(this, 'IngestionService', {
      serviceName: `auto-forex-${environmentName}-price-ingestion`,
      cluster: cluster as ICluster,
      taskDefinition,
      desiredCount: 1,
      assignPublicIp: true,
      vpcSubnets: { subnetType: SubnetType.PUBLIC },
      securityGroups: [securityGroup],
      minHealthyPercent: 100,
      maxHealthyPercent: 200,
      circuitBreaker: { rollback: true },
    });

    new CfnOutput(this, 'UserPoolId', { value: userPool.userPoolId });
    new CfnOutput(this, 'UserPoolClientId', { value: userPoolClient.userPoolClientId });
    new CfnOutput(this, 'ApiUrl', { value: api.apiEndpoint });
    new CfnOutput(this, 'PriceQueueUrl', { value: priceQueue.queueUrl });
    new CfnOutput(this, 'PricesTableName', { value: pricesTable.tableName });
    new CfnOutput(this, 'UsersTableName', { value: usersTable.tableName });
    new CfnOutput(this, 'AppConfigApplicationId', { value: appConfigApplication.ref });
    new CfnOutput(this, 'AppConfigEnvironmentId', { value: appConfigEnvironment.ref });
    new CfnOutput(this, 'AppConfigProfileId', { value: configurationProfile.ref });
  }
}
