import { describe, expect, it } from 'vitest';
import type { Strategy } from '../services/api/strategies';
import { buildParameterLabelMap } from './strategySchemaLabels';

const strategies: Strategy[] = [
  {
    id: 'snowball',
    name: 'Snowball',
    class_name: 'SnowballStrategy',
    description: '',
    config_schema: {
      type: 'object',
      properties: {
        stop_loss_enabled: {
          type: 'boolean',
          title: 'Enable Stop Loss',
          title_ja: 'ロスカットを有効化',
        },
        unknown_locale: {
          type: 'number',
          title: 'English Fallback',
        },
      },
    },
  },
];

describe('strategySchemaLabels', () => {
  it('resolves regional language tags to base localized labels', () => {
    const labels = buildParameterLabelMap(strategies, 'snowball', 'ja-JP');

    expect(labels.get('stop_loss_enabled')).toBe('ロスカットを有効化');
    expect(labels.get('unknown_locale')).toBe('English Fallback');
  });

  it('resolves underscore language tags to base localized labels', () => {
    const labels = buildParameterLabelMap(strategies, 'snowball', 'ja_JP');

    expect(labels.get('stop_loss_enabled')).toBe('ロスカットを有効化');
  });
});
