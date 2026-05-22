import { describe, expect, it } from 'vitest';
import type { ConfigProperty } from '../types/strategy';
import {
  calculateSnowballReferenceBaseUnits,
  syncSnowballReferenceBaseUnits,
} from './snowballBaseUnits';

const snowballSchemaProperties: Record<string, ConfigProperty> = {
  base_units: { type: 'integer', default: 1000 },
  base_units_auto_adjust_enabled: { type: 'boolean', default: false },
  base_units_balance_ratio: { type: 'number', default: 1000 },
  base_units_step: { type: 'integer', default: 100 },
};

describe('snowballBaseUnits', () => {
  it('calculates reference base units from balance ratio and step', () => {
    expect(calculateSnowballReferenceBaseUnits(500, 100)).toBe(2000);
    expect(calculateSnowballReferenceBaseUnits(2000, 100)).toBe(500);
    expect(calculateSnowballReferenceBaseUnits(700, 100)).toBe(1400);
  });

  it('syncs base_units when auto adjustment ratio changes', () => {
    const synced = syncSnowballReferenceBaseUnits(
      {
        base_units: 1000,
        base_units_auto_adjust_enabled: true,
        base_units_balance_ratio: 500,
        base_units_step: 100,
      },
      snowballSchemaProperties,
      'base_units_balance_ratio'
    );

    expect(synced.base_units).toBe(2000);
  });

  it('uses schema defaults when auto adjustment is enabled', () => {
    const synced = syncSnowballReferenceBaseUnits(
      {
        base_units_auto_adjust_enabled: true,
      },
      snowballSchemaProperties,
      'base_units_auto_adjust_enabled'
    );

    expect(synced.base_units).toBe(1000);
  });

  it('does not sync when auto adjustment is disabled', () => {
    const synced = syncSnowballReferenceBaseUnits(
      {
        base_units: 1500,
        base_units_auto_adjust_enabled: false,
        base_units_balance_ratio: 500,
        base_units_step: 100,
      },
      snowballSchemaProperties,
      'base_units_balance_ratio'
    );

    expect(synced.base_units).toBe(1500);
  });
});
