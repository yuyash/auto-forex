import assert from 'node:assert/strict';
import { test } from 'node:test';
import { App } from 'aws-cdk-lib';
import { Match, Template } from 'aws-cdk-lib/assertions';
import { ApplicationStack } from '../lib/stacks/application-stack';

function template(environmentName: 'alpha' | 'beta' | 'prod' = 'alpha'): Template {
  const stack = new ApplicationStack(new App(), `Application${environmentName}`, {
    environmentName,
    env: { account: '111111111111', region: 'us-west-2' },
  });
  return Template.fromStack(stack);
}

test('price ingestion uses ARM Fargate, FIFO SQS, Lambda and Prices DynamoDB', () => {
  const value = template();
  value.resourceCountIs('AWS::DynamoDB::Table', 2);
  value.hasResourceProperties('AWS::DynamoDB::Table', {
    TableName: 'Prices',
    BillingMode: 'PAY_PER_REQUEST',
    KeySchema: [
      { AttributeName: 'symbol', KeyType: 'HASH' },
      { AttributeName: 'created_at', KeyType: 'RANGE' },
    ],
  });
  value.hasResourceProperties('AWS::DynamoDB::Table', {
    TableName: 'Users',
    BillingMode: 'PAY_PER_REQUEST',
    KeySchema: [{ AttributeName: 'user_id', KeyType: 'HASH' }],
    GlobalSecondaryIndexes: [Match.objectLike({
      IndexName: 'stream_status-index',
      KeySchema: [
        { AttributeName: 'stream_status', KeyType: 'HASH' },
        { AttributeName: 'user_id', KeyType: 'RANGE' },
      ],
    })],
  });
  value.resourceCountIs('AWS::SQS::Queue', 2);
  value.hasResourceProperties('AWS::SQS::Queue', {
    QueueName: 'auto-forex-alpha-prices.fifo',
    FifoQueue: true,
  });
  value.hasResourceProperties('AWS::ECS::TaskDefinition', {
    Cpu: '256',
    Memory: '512',
    RuntimePlatform: { CpuArchitecture: 'ARM64', OperatingSystemFamily: 'LINUX' },
  });
  value.hasResourceProperties('AWS::ECS::Service', {
    DesiredCount: 1,
    NetworkConfiguration: {
      AwsvpcConfiguration: Match.objectLike({ AssignPublicIp: 'ENABLED' }),
    },
  });
  value.hasResourceProperties('AWS::Lambda::Function', {
    Architectures: ['arm64'],
    Runtime: 'python3.11',
    Handler: 'autoforex.handlers.prices.handler',
  });
  value.hasResourceProperties('AWS::Lambda::Function', {
    Architectures: ['arm64'],
    Runtime: 'python3.11',
    Handler: 'autoforex.handlers.users.handler',
  });
  value.hasResourceProperties('AWS::Cognito::UserPool', {
    LambdaConfig: Match.objectLike({ PostConfirmation: Match.anyValue() }),
  });
});

test('AppConfig contains only operational settings and Cognito has no broker secret attribute', () => {
  const value = template();
  value.resourceCountIs('AWS::AppConfig::Application', 1);
  value.resourceCountIs('AWS::AppConfig::ConfigurationProfile', 1);
  value.resourceCountIs('AWS::AppConfig::Deployment', 1);
  value.hasResourceProperties('AWS::AppConfig::HostedConfigurationVersion', {
    Content: Match.serializedJson({
      ingestion_enabled: false,
      reconnect_max_delay_seconds: 30,
    }),
  });
  const pools = value.findResources('AWS::Cognito::UserPool');
  assert.ok(!JSON.stringify(pools).includes('oandaSecretArn'));
  assert.ok(!JSON.stringify(value.toJSON()).includes('cognito-idp:AdminGetUser'));
});

test('beta imports the shared dev Prices and Users tables instead of creating duplicates', () => {
  const value = template('beta');
  value.resourceCountIs('AWS::DynamoDB::Table', 0);
  assert.ok(JSON.stringify(value.toJSON()).includes('table/Users/index/stream_status-index'));
});

test('HTTP API exposes public auth routes and JWT-protected user routes', () => {
  const value = template();
  value.resourceCountIs('AWS::ApiGatewayV2::Api', 1);
  value.resourceCountIs('AWS::ApiGatewayV2::Authorizer', 1);
  value.hasResourceProperties('AWS::ApiGatewayV2::Authorizer', {
    AuthorizerType: 'JWT',
    IdentitySource: ['$request.header.Authorization'],
    JwtConfiguration: {
      Audience: Match.anyValue(),
      Issuer: Match.anyValue(),
    },
  });
  value.hasResourceProperties('AWS::ApiGatewayV2::Route', {
    RouteKey: 'POST /users/signup',
    AuthorizationType: 'NONE',
  });
  value.hasResourceProperties('AWS::ApiGatewayV2::Route', {
    RouteKey: 'POST /auth/login',
    AuthorizationType: 'NONE',
  });
  value.hasResourceProperties('AWS::ApiGatewayV2::Route', {
    RouteKey: 'GET /users/me',
    AuthorizationType: 'JWT',
  });
  value.hasResourceProperties('AWS::ApiGatewayV2::Route', {
    RouteKey: 'PUT /users/me/oanda-token',
    AuthorizationType: 'JWT',
  });
  for (const handler of [
    'autoforex.handlers.api.users.signup.handler',
    'autoforex.handlers.api.auth.login.handler',
    'autoforex.handlers.api.users.me.handler',
    'autoforex.handlers.api.users.oanda_token.handler',
  ]) {
    value.hasResourceProperties('AWS::Lambda::Function', { Handler: handler });
  }
});
