import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { JSON_SCHEMA, load } from 'js-yaml';
import type { Environment } from 'aws-cdk-lib';

export const PROJECT_NAME = 'auto-forex';
export const APPLICATION_ENVIRONMENTS = ['alpha', 'beta', 'prod'] as const;
export type ApplicationEnvironment = (typeof APPLICATION_ENVIRONMENTS)[number];
export const AWS_ACCOUNTS = ['dev', 'prod', 'pipeline'] as const;
export type AwsAccount = (typeof AWS_ACCOUNTS)[number];

const ENVIRONMENT_ACCOUNT: Readonly<Record<ApplicationEnvironment, Exclude<AwsAccount, 'pipeline'>>> = {
  alpha: 'dev',
  beta: 'dev',
  prod: 'prod',
};

type Variables = Readonly<Record<string, string | undefined>>;
type Mapping = Record<string, unknown>;

interface AccountConfiguration {
  readonly accountId: string | null;
  /** Local AWS CLI profile. It is never passed to CodeBuild. */
  readonly profile: string;
}

export interface EnvironmentConfiguration {
  readonly region: string;
  readonly accounts: Readonly<Record<AwsAccount, AccountConfiguration>>;
  readonly bootstrap: {
    readonly enabled: boolean;
    readonly executionPolicyArn: string;
  };
  readonly github: {
    readonly owner: string | null;
    readonly repo: string;
    readonly branch: string;
  };
}

function mapping(value: unknown, name: string): Mapping {
  if (value === undefined || value === null) return {};
  if (typeof value !== 'object' || Array.isArray(value)) throw new Error(`${name} must be a YAML mapping.`);
  return value as Mapping;
}

function expandVariables(value: unknown, variables: Variables): unknown {
  if (typeof value === 'string') {
    return value.replace(/\$\{([A-Za-z_][A-Za-z0-9_]*)(?::-([^}]*))?\}/g,
      (_match: string, name: string, fallback: string | undefined) => {
        const resolved = variables[name] || fallback;
        if (resolved === undefined) throw new Error(`Missing environment variable ${name} referenced by YAML.`);
        return resolved;
      });
  }
  if (Array.isArray(value)) return value.map((item) => expandVariables(item, variables));
  if (value !== null && typeof value === 'object') {
    return Object.fromEntries(Object.entries(value).map(([key, item]) => [key, expandVariables(item, variables)]));
  }
  return value;
}

function readYaml(file: string): Mapping {
  return mapping(load(readFileSync(file, 'utf8'), { schema: JSON_SCHEMA }), file);
}

function accountId(value: string | null, name: string): string | null {
  if (value !== null && !/^\d{12}$/.test(value)) throw new Error(`${name} must be a 12-digit AWS account ID.`);
  return value;
}

/** Environment variables override YAML values, followed by built-in defaults. */
export function resolveConfiguration(options: {
  readonly environment?: Variables;
  readonly configFile?: string;
} = {}): EnvironmentConfiguration {
  const variables = options.environment ?? process.env;
  const selectedFile = options.configFile ?? variables.AUTO_FOREX_CONFIG_FILE;
  const file = resolve(selectedFile ?? 'config/environments.yaml');
  let raw: Mapping;
  try {
    raw = readYaml(file);
  } catch (error) {
    if (!selectedFile && (error as NodeJS.ErrnoException).code === 'ENOENT') raw = {};
    else throw error;
  }

  const value = (key: string, yamlValue: unknown, fallback: unknown = null): unknown =>
    variables[key]?.trim() || expandVariables(
      yamlValue === undefined || yamlValue === null || yamlValue === '' ? fallback : yamlValue,
      variables,
    );
  const text = (key: string, yamlValue: unknown, fallback: string | null = null): string | null => {
    const result = value(key, yamlValue, fallback);
    if (result === null) return null;
    if (typeof result !== 'string') throw new Error(`${key} must be a string; quote account IDs in YAML.`);
    return result.trim() || fallback;
  };
  const flag = (key: string, yamlValue: unknown, fallback: boolean): boolean => {
    const result = value(key, yamlValue, fallback);
    if (result === true || result === 'true') return true;
    if (result === false || result === 'false') return false;
    throw new Error(`${key} must be true or false.`);
  };

  const rawAccounts = mapping(raw.accounts, 'accounts');
  const accounts = Object.fromEntries(AWS_ACCOUNTS.map((name) => {
    const account = mapping(rawAccounts[name], `accounts.${name}`);
    const prefix = `AUTO_FOREX_ACCOUNT_${name.toUpperCase()}`;
    const profileKey = `AUTO_FOREX_PROFILE_${name.toUpperCase()}`;
    const id = accountId(text(prefix, account.accountId), prefix);
    const profile = text(profileKey, account.profile, `auto-forex-${name}`)!;
    if (!/^[A-Za-z0-9_+=,.@-]+$/.test(profile)) throw new Error(`${profileKey} is not a valid AWS CLI profile name.`);
    return [name, { accountId: id, profile }];
  })) as EnvironmentConfiguration['accounts'];

  const configuredIds = AWS_ACCOUNTS.map((name) => accounts[name].accountId).filter((id): id is string => id !== null);
  if (new Set(configuredIds).size !== configuredIds.length) throw new Error('dev, prod, and pipeline must use different AWS accounts.');

  const bootstrap = mapping(raw.bootstrap, 'bootstrap');
  const github = mapping(raw.github, 'github');
  const configuration: EnvironmentConfiguration = {
    region: text('AUTO_FOREX_REGION', raw.region, 'us-west-2')!,
    accounts,
    bootstrap: {
      enabled: flag('AUTO_FOREX_BOOTSTRAP_ENABLED', bootstrap.enabled, true),
      executionPolicyArn: text('AUTO_FOREX_BOOTSTRAP_EXECUTION_POLICY_ARN', bootstrap.executionPolicyArn, 'arn:aws:iam::aws:policy/AdministratorAccess')!,
    },
    github: {
      owner: text('AUTO_FOREX_GITHUB_OWNER', github.owner),
      repo: text('AUTO_FOREX_GITHUB_REPO', github.repo, PROJECT_NAME)!,
      branch: text('AUTO_FOREX_GITHUB_BRANCH', github.branch, 'main')!,
    },
  };
  if (!/^[a-z]{2}(?:-[a-z]+)+-\d$/.test(configuration.region)) throw new Error('AUTO_FOREX_REGION is not a valid AWS region name.');
  if (!/^arn:aws:iam::(?:aws|\d{12}):policy\/[\w+=,.@\/-]+$/.test(configuration.bootstrap.executionPolicyArn)) throw new Error('Invalid bootstrap execution policy ARN.');
  if (configuration.github.owner !== null && !/^[A-Za-z0-9](?:[A-Za-z0-9-]{0,38})$/.test(configuration.github.owner)) throw new Error('Invalid GitHub owner.');
  if (!/^[A-Za-z0-9_.-]+$/.test(configuration.github.repo)) throw new Error('Invalid GitHub repository name.');
  if (!configuration.github.branch || /[\s~^:?*\[\\]/.test(configuration.github.branch)) throw new Error('Invalid GitHub branch.');
  return configuration;
}

export function required(value: string | null, name: string): string {
  if (value === null) throw new Error(`Set ${name} in the environment or its YAML field.`);
  return value;
}

export function accountEnvironment(configuration: EnvironmentConfiguration, environmentName: ApplicationEnvironment): Environment {
  const accountName = ENVIRONMENT_ACCOUNT[environmentName];
  return {
    account: required(configuration.accounts[accountName].accountId, `AUTO_FOREX_ACCOUNT_${accountName.toUpperCase()}`),
    region: configuration.region,
  };
}

export function pipelineAccountEnvironment(configuration: EnvironmentConfiguration): Environment {
  return {
    account: required(configuration.accounts.pipeline.accountId, 'AUTO_FOREX_ACCOUNT_PIPELINE'),
    region: configuration.region,
  };
}

/** Carry deployment coordinates into CI; never pass local profile names or credentials. */
export function pipelineEnvironment(configuration: EnvironmentConfiguration): Record<string, string> {
  const variables: Record<string, string> = {
    AUTO_FOREX_REGION: configuration.region,
    AUTO_FOREX_GITHUB_OWNER: required(configuration.github.owner, 'AUTO_FOREX_GITHUB_OWNER'),
    AUTO_FOREX_GITHUB_REPO: configuration.github.repo,
    AUTO_FOREX_GITHUB_BRANCH: configuration.github.branch,
    AUTO_FOREX_BOOTSTRAP_ENABLED: String(configuration.bootstrap.enabled),
    AUTO_FOREX_BOOTSTRAP_EXECUTION_POLICY_ARN: configuration.bootstrap.executionPolicyArn,
  };
  for (const name of AWS_ACCOUNTS) {
    variables[`AUTO_FOREX_ACCOUNT_${name.toUpperCase()}`] = required(configuration.accounts[name].accountId, `AUTO_FOREX_ACCOUNT_${name.toUpperCase()}`);
  }
  return variables;
}
