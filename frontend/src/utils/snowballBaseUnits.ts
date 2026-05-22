import type { ConfigProperty, StrategyConfig } from '../types/strategy';
import { normalizeComparableValue } from './strategySchemaDependsOn';

export const SNOWBALL_AUTO_BASE_UNITS_REFERENCE_BALANCE = 1_000_000;

const AUTO_BASE_UNITS_TRIGGER_FIELDS = new Set([
  'base_units_auto_adjust_enabled',
  'base_units_balance_ratio',
  'base_units_step',
]);

function positiveFiniteNumber(value: unknown): number | null {
  const comparable = normalizeComparableValue(value);
  if (typeof comparable !== 'number' || !Number.isFinite(comparable)) {
    return null;
  }
  return comparable > 0 ? comparable : null;
}

function positiveStep(value: unknown): number {
  const parsed = positiveFiniteNumber(value);
  return parsed === null ? 1 : Math.max(1, Math.trunc(parsed));
}

function configValue(
  config: StrategyConfig,
  schemaProperties: Record<string, ConfigProperty> | undefined,
  field: string
): unknown {
  if (Object.prototype.hasOwnProperty.call(config, field)) {
    return config[field];
  }
  return schemaProperties?.[field]?.default;
}

export function calculateSnowballReferenceBaseUnits(
  balanceRatio: unknown,
  unitStep: unknown,
  referenceBalance = SNOWBALL_AUTO_BASE_UNITS_REFERENCE_BALANCE
): number | null {
  const ratio = positiveFiniteNumber(balanceRatio);
  if (ratio === null) return null;

  const step = positiveStep(unitStep);
  const rawUnits = referenceBalance / ratio;
  const steppedUnits = Math.floor(rawUnits / step) * step;
  return Math.max(step, steppedUnits);
}

export function syncSnowballReferenceBaseUnits(
  config: StrategyConfig,
  schemaProperties: Record<string, ConfigProperty> | undefined,
  changedField: string
): StrategyConfig {
  if (!AUTO_BASE_UNITS_TRIGGER_FIELDS.has(changedField)) {
    return config;
  }
  if (!schemaProperties?.base_units_auto_adjust_enabled) {
    return config;
  }
  if (
    normalizeComparableValue(
      configValue(config, schemaProperties, 'base_units_auto_adjust_enabled')
    ) !== true
  ) {
    return config;
  }

  const baseUnits = calculateSnowballReferenceBaseUnits(
    configValue(config, schemaProperties, 'base_units_balance_ratio'),
    configValue(config, schemaProperties, 'base_units_step')
  );
  if (baseUnits === null || config.base_units === baseUnits) {
    return config;
  }

  return {
    ...config,
    base_units: baseUnits,
  };
}
