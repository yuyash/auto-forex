import { describe, expect, it } from 'vitest';
import type { ConfigProperty } from '../types/strategy';
import {
  buildStrategyComparisonData,
  formatStrategyComparisonValue,
  resolveStrategyComparisonSnapshot,
} from './strategyConfigComparison';

const labels = { yes: 'はい', no: 'いいえ' };

describe('strategyConfigComparison', () => {
  it('uses current parameters instead of flattening duplicate snapshot branches', () => {
    const snapshot = resolveStrategyComparisonSnapshot({
      id: 'config-1',
      name: 'Live Config',
      strategy_type: 'snowball',
      parameters: { stop_loss_enabled: false },
      current: {
        name: 'Historical Config',
        strategy_type: 'snowball',
        parameters: { stop_loss_enabled: true },
      },
      initial: {
        strategy_type: 'snowball',
        parameters: { stop_loss_enabled: false },
      },
      revisions: [],
    });

    expect(snapshot.strategyType).toBe('snowball');
    expect(snapshot.parameters).toEqual({ stop_loss_enabled: true });
  });

  it('builds rows from effective strategy parameters and schema defaults', () => {
    const schemaProperties: Record<string, ConfigProperty> = {
      base_units_auto_adjust_enabled: {
        type: 'boolean',
        title: 'Auto Adjust Base Units',
        title_ja: '基本ユニット数の自動調整',
        default: false,
      },
      base_units_balance_ratio: {
        type: 'number',
        title: 'Balance Per Unit',
        title_ja: '1ユニットあたりの残高比率',
        default: 1000,
        dependsOn: {
          field: 'base_units_auto_adjust_enabled',
          values: [true],
        },
      },
      rebuild_entry_price_mode: {
        type: 'string',
        title: 'Rebuild Entry Price Mode',
        title_ja: '再建時のエントリー価格設定',
        enum_labels: {
          original_entry: 'Original Entry',
          stop_loss_exit: 'Stop Loss Exit',
        },
        enum_labels_ja: {
          original_entry: '元のエントリー',
          stop_loss_exit: 'ロスカット決済価格',
        },
        default: 'original_entry',
      },
    };

    const data = buildStrategyComparisonData({
      configs: [
        {
          id: 'config-1',
          name: 'Config A',
          strategy_type: 'snowball',
          parameters: {
            rebuild_take_profit_recovery_enabled: true,
            rebuild_entry_price_mode: 'original_entry',
          },
        },
        {
          id: 'config-2',
          name: 'Config B',
          strategy_type: 'snowball',
          parameters: {
            base_units_auto_adjust_enabled: true,
            base_units_balance_ratio: 2000,
            rebuild_entry_price_mode: 'stop_loss_exit',
          },
        },
      ],
      schemaPropertiesByType: new Map([['snowball', schemaProperties]]),
      language: 'ja-JP',
      labels,
    });

    expect(data.keys).toEqual([
      'base_units_auto_adjust_enabled',
      'base_units_balance_ratio',
      'rebuild_entry_price_mode',
    ]);
    expect(data.configs[0]).toEqual({
      base_units_auto_adjust_enabled: 'いいえ',
      rebuild_entry_price_mode: '元のエントリー',
    });
    expect(data.configs[1]).toEqual({
      base_units_auto_adjust_enabled: 'はい',
      base_units_balance_ratio: '2000',
      rebuild_entry_price_mode: 'ロスカット決済価格',
    });
    expect(data.labels.base_units_auto_adjust_enabled).toEqual({
      primary: '基本ユニット数の自動調整',
      secondary: 'Auto Adjust Base Units',
    });
    expect(data.labels.base_units_balance_ratio).toEqual({
      primary: '1ユニットあたりの残高比率',
      secondary: 'Balance Per Unit',
    });
  });

  it('falls back to English enum labels outside Japanese locales', () => {
    expect(
      formatStrategyComparisonValue(
        'stop_loss_exit',
        {
          type: 'string',
          title: 'Rebuild Entry Price Mode',
          enum_labels: {
            stop_loss_exit: 'Stop Loss Exit',
          },
          enum_labels_ja: {
            stop_loss_exit: 'ロスカット決済価格',
          },
        },
        'en-US',
        labels
      )
    ).toBe('Stop Loss Exit');
  });

  it('uses English labels without secondary text in English locales', () => {
    const data = buildStrategyComparisonData({
      configs: [
        {
          id: 'config-1',
          name: 'Config A',
          strategy_type: 'snowball',
          parameters: { base_units: 1000 },
        },
      ],
      schemaPropertiesByType: new Map([
        [
          'snowball',
          {
            base_units: {
              type: 'number',
              title: 'Base Units',
              title_ja: '基本ユニット数',
              default: 1000,
            },
          },
        ],
      ]),
      language: 'en_US',
      labels,
    });

    expect(data.labels.base_units).toEqual({ primary: 'Base Units' });
  });
});
