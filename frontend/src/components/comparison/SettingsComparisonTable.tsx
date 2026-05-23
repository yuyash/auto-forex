import { useMemo, useState } from 'react';
import { Alert, Box, Button, Chip, Paper, Typography } from '@mui/material';
import { useTranslation } from 'react-i18next';

export interface SettingsComparisonItem {
  id: string;
  title: string;
  subtitle?: string;
  settings: Record<string, unknown>;
}

interface SettingsComparisonTableProps {
  items: SettingsComparisonItem[];
  labelMap?: Map<string, string>;
  keyOrder?: string[];
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return value != null && typeof value === 'object' && !Array.isArray(value);
}

function stableValue(value: unknown): unknown {
  if (Array.isArray(value)) return value.map(stableValue);
  if (!isRecord(value)) return value;
  return Object.fromEntries(
    Object.keys(value)
      .sort()
      .map((key) => [key, stableValue(value[key])])
  );
}

function stringifyValue(
  value: unknown,
  labels: { yes: string; no: string }
): string {
  if (value == null || value === '') return '-';
  if (typeof value === 'boolean') return value ? labels.yes : labels.no;
  if (typeof value === 'number' || typeof value === 'bigint') {
    return String(value);
  }
  if (typeof value === 'string') return value;
  return JSON.stringify(stableValue(value), null, 2);
}

function flattenSettings(
  value: Record<string, unknown>,
  labels: { yes: string; no: string },
  prefix = ''
): Record<string, string> {
  const result: Record<string, string> = {};
  for (const [key, rawValue] of Object.entries(value)) {
    if (rawValue === undefined || rawValue === null || rawValue === '') {
      continue;
    }
    const path = prefix ? `${prefix}.${key}` : key;
    if (isRecord(rawValue)) {
      const nested = flattenSettings(rawValue, labels, path);
      if (Object.keys(nested).length === 0) {
        result[path] = stringifyValue(rawValue, labels);
      } else {
        Object.assign(result, nested);
      }
    } else {
      result[path] = stringifyValue(rawValue, labels);
    }
  }
  return result;
}

function titleCaseKey(key: string): string {
  return key
    .replace(/^parameters\./, '')
    .replace(/^debug_options\./, '')
    .replace(/_/g, ' ')
    .replace(/\b\w/g, (char) => char.toUpperCase());
}

function orderIndex(key: string, keyOrder: string[]): number {
  const exactIndex = keyOrder.indexOf(key);
  if (exactIndex >= 0) return exactIndex;
  const prefixIndex = keyOrder.findIndex((candidate) =>
    key.startsWith(`${candidate}.`)
  );
  return prefixIndex >= 0 ? prefixIndex : Number.MAX_SAFE_INTEGER;
}

function resolveSettingLabel(
  key: string,
  labelMap: Map<string, string> | undefined
): string {
  const directLabel = labelMap?.get(key);
  if (directLabel) return directLabel;

  const parts = key.split('.');
  for (let index = parts.length - 1; index > 0; index -= 1) {
    const prefix = parts.slice(0, index).join('.');
    const prefixLabel = labelMap?.get(prefix);
    if (prefixLabel) {
      return `${prefixLabel} / ${titleCaseKey(parts.slice(index).join('.'))}`;
    }
  }

  return titleCaseKey(key);
}

export function SettingsComparisonTable({
  items,
  labelMap,
  keyOrder = [],
}: SettingsComparisonTableProps) {
  const { t } = useTranslation('common');
  const [showDiffOnly, setShowDiffOnly] = useState(false);
  const booleanLabels = useMemo(
    () => ({
      yes: t('labels.yes'),
      no: t('labels.no'),
    }),
    [t]
  );

  const flattenedItems = useMemo(
    () => items.map((item) => flattenSettings(item.settings, booleanLabels)),
    [booleanLabels, items]
  );

  const allKeys = useMemo(() => {
    const keys = new Set<string>();
    for (const settings of flattenedItems) {
      for (const key of Object.keys(settings)) keys.add(key);
    }
    return [...keys].sort((left, right) => {
      const leftOrder = orderIndex(left, keyOrder);
      const rightOrder = orderIndex(right, keyOrder);
      if (leftOrder !== rightOrder) return leftOrder - rightOrder;
      return left.localeCompare(right);
    });
  }, [flattenedItems, keyOrder]);

  const diffKeys = useMemo(
    () =>
      new Set(
        allKeys.filter((key) => {
          const values = flattenedItems.map((settings) => settings[key] ?? '-');
          return values.some((value) => value !== values[0]);
        })
      ),
    [allKeys, flattenedItems]
  );

  const visibleKeys = showDiffOnly
    ? allKeys.filter((key) => diffKeys.has(key))
    : allKeys;

  if (items.length < 2) {
    return (
      <Alert severity="info">
        {t('comparison.selectAtLeastTwo', {
          defaultValue: 'Select at least two items to compare.',
        })}
      </Alert>
    );
  }

  if (allKeys.length === 0) {
    return (
      <Alert severity="info">
        {t('comparison.noSettings', {
          defaultValue: 'No settings are available for comparison.',
        })}
      </Alert>
    );
  }

  return (
    <Paper variant="outlined" sx={{ overflow: 'hidden' }}>
      <Box
        sx={{
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          gap: 1,
          p: 1,
          borderBottom: 1,
          borderColor: 'divider',
          flexWrap: 'wrap',
        }}
      >
        <Box sx={{ display: 'flex', alignItems: 'center', gap: 0.75 }}>
          <Chip
            size="small"
            label={t('comparison.differenceCount', {
              count: diffKeys.size,
              defaultValue: '{{count}} differences',
            })}
            color={diffKeys.size > 0 ? 'warning' : 'default'}
            variant={diffKeys.size > 0 ? 'filled' : 'outlined'}
          />
          <Typography variant="body2" color="text.secondary">
            {t('comparison.selectedCount', {
              count: items.length,
              defaultValue: '{{count}} selected',
            })}
          </Typography>
        </Box>
        <Button
          size="small"
          variant="outlined"
          onClick={() => setShowDiffOnly((value) => !value)}
        >
          {showDiffOnly
            ? t('comparison.showAll', { defaultValue: 'Show all' })
            : t('comparison.showDifferencesOnly', {
                defaultValue: 'Show differences only',
              })}
        </Button>
      </Box>

      <Box sx={{ overflowX: 'auto' }}>
        <Box
          component="table"
          sx={{
            minWidth: 240 + items.length * 220,
            width: '100%',
            borderCollapse: 'collapse',
            '& th, & td': {
              borderBottom: 1,
              borderRight: 1,
              borderColor: 'divider',
              px: 1,
              py: 0.75,
              verticalAlign: 'top',
              fontSize: '0.8125rem',
            },
            '& th': {
              bgcolor: 'action.hover',
              fontWeight: 600,
            },
            '& tr:last-of-type td': {
              borderBottom: 0,
            },
            '& th:last-of-type, & td:last-of-type': {
              borderRight: 0,
            },
          }}
        >
          <thead>
            <tr>
              <th style={{ minWidth: 220, textAlign: 'left' }}>
                {t('comparison.setting', { defaultValue: 'Setting' })}
              </th>
              {items.map((item) => (
                <th key={item.id} style={{ minWidth: 220, textAlign: 'left' }}>
                  <Typography variant="subtitle2" sx={{ lineHeight: 1.2 }}>
                    {item.title}
                  </Typography>
                  {item.subtitle ? (
                    <Typography
                      variant="caption"
                      color="text.secondary"
                      sx={{ display: 'block', mt: 0.25 }}
                    >
                      {item.subtitle}
                    </Typography>
                  ) : null}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {visibleKeys.length === 0 ? (
              <tr>
                <td colSpan={items.length + 1}>
                  <Typography color="text.secondary">
                    {t('comparison.noDifferences')}
                  </Typography>
                </td>
              </tr>
            ) : (
              visibleKeys.map((key) => {
                const isDifferent = diffKeys.has(key);
                return (
                  <tr key={key}>
                    <td
                      style={{
                        backgroundColor: isDifferent
                          ? 'rgba(255, 193, 7, 0.12)'
                          : undefined,
                      }}
                    >
                      <Typography
                        variant="body2"
                        fontWeight={isDifferent ? 700 : 500}
                      >
                        {resolveSettingLabel(key, labelMap)}
                      </Typography>
                      <Typography
                        variant="caption"
                        color="text.secondary"
                        sx={{
                          display: 'block',
                          fontFamily: 'monospace',
                          overflowWrap: 'anywhere',
                        }}
                      >
                        {key}
                      </Typography>
                    </td>
                    {flattenedItems.map((settings, index) => (
                      <td
                        key={`${items[index].id}-${key}`}
                        style={{
                          backgroundColor: isDifferent
                            ? 'rgba(255, 193, 7, 0.08)'
                            : undefined,
                        }}
                      >
                        <Typography
                          variant="body2"
                          sx={{
                            fontFamily: 'monospace',
                            fontSize: '0.75rem',
                            whiteSpace: 'pre-wrap',
                            overflowWrap: 'anywhere',
                          }}
                        >
                          {settings[key] ?? '-'}
                        </Typography>
                      </td>
                    ))}
                  </tr>
                );
              })
            )}
          </tbody>
        </Box>
      </Box>
    </Paper>
  );
}
