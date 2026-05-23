/**
 * ExecutionComparisonDialog
 *
 * Full-screen dialog that compares multiple task executions side-by-side.
 * Shows: task config diff, strategy config diff, result metrics diff,
 * and overlaid time-series metric charts.
 */

import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import {
  Alert,
  AppBar,
  Box,
  CircularProgress,
  Dialog,
  Grid,
  IconButton,
  LinearProgress,
  Paper,
  Slide,
  Tab,
  Tabs,
  ToggleButton,
  ToggleButtonGroup,
  Toolbar,
  Tooltip,
  Typography,
} from '@mui/material';
import type { TransitionProps } from '@mui/material/transitions';
import {
  Close as CloseIcon,
  ExpandMore as ExpandMoreIcon,
  ExpandLess as ExpandLessIcon,
  Refresh as RefreshIcon,
} from '@mui/icons-material';
import { LineChart } from '@mui/x-charts/LineChart';
import React from 'react';
import type { TaskExecution } from '../../../types/execution';
import type { TaskType } from '../../../types/common';
import type { MoneyAmountLike } from '../../../types/money';
import type { ConfigProperty } from '../../../types/strategy';
import {
  fetchPaginatedMetrics,
  type MetricPoint,
} from '../../../utils/fetchMetrics';
import { useStrategies } from '../../../hooks/useStrategies';
import {
  buildParameterLabelMap,
  resolveParameterLabel,
} from '../../../utils/strategySchemaLabels';
import {
  buildStrategyComparisonData,
  resolveStrategyComparisonSnapshot,
  type StrategyComparisonLabel,
} from '../../../utils/strategyConfigComparison';
import { buildTaskComparisonLabelMap } from './taskSettingDefinitions';
import { computeAutoInterval } from '../../../utils/autoGranularity';
import {
  formatAppNumber,
  formatMoneyAmount,
  formatMoneyPayload,
  formatAppPercent,
} from '../../../utils/numberFormat';
import { useDateTimeFormatter } from '../../../hooks/useDateTimeFormatter';

/** Palette for up to 10 executions */
const EXEC_COLORS = [
  '#1976d2',
  '#d32f2f',
  '#2e7d32',
  '#f57c00',
  '#7b1fa2',
  '#00838f',
  '#c2185b',
  '#455a64',
  '#6d4c41',
  '#00695c',
];

const INTERVAL_OPTIONS = [
  { value: 0, label: 'Auto' },
  { value: 1, label: '1m' },
  { value: 5, label: '5m' },
  { value: 15, label: '15m' },
  { value: 60, label: '1h' },
  { value: 240, label: '4h' },
  { value: 1440, label: '1d' },
] as const;

const CHART_METRICS: {
  key: string;
  format?: 'pct' | 'int' | 'currency';
}[] = [
  { key: 'current_balance', format: 'currency' },
  { key: 'total_pnl', format: 'currency' },
  { key: 'realized_pnl', format: 'currency' },
  { key: 'unrealized_pnl', format: 'currency' },
  { key: 'total_return', format: 'pct' },
  { key: 'margin_ratio', format: 'pct' },
  { key: 'open_positions', format: 'int' },
  { key: 'closed_positions', format: 'int' },
  { key: 'total_trades', format: 'int' },
  { key: 'win_rate', format: 'pct' },
  { key: 'winning_trades', format: 'int' },
  { key: 'losing_trades', format: 'int' },
  { key: 'ticks_processed', format: 'int' },
];

const COMPARISON_METRIC_KEYS = CHART_METRICS.map((metric) => metric.key);

const RATIO_KEYS = new Set(['margin_ratio']);
const CHART_HEIGHT = 220;

interface ExecutionComparisonDialogProps {
  open: boolean;
  onClose: () => void;
  executions: TaskExecution[];
  taskId: string;
  taskType: TaskType;
}

const SlideUp = React.forwardRef(function Transition(
  props: TransitionProps & { children: React.ReactElement },
  ref: React.Ref<unknown>
) {
  return <Slide direction="up" ref={ref} {...props} />;
});

function formatYLabel(v: number, format?: 'pct' | 'int' | 'currency'): string {
  if (format === 'pct') return formatAppPercent(v, 2);
  if (format === 'currency')
    return formatAppNumber(v, {
      minimumFractionDigits: 2,
      maximumFractionDigits: 2,
    });
  if (format === 'int')
    return formatAppNumber(Math.round(v), { maximumFractionDigits: 0 });
  return formatAppNumber(v, {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  });
}

function formatTickLabel(
  date: Date,
  rangeMs: number,
  formatDate: (value: Date | string | null | undefined) => string,
  formatDateTime: (
    value: Date | string | null | undefined,
    options?: { includeSeconds?: boolean; includeTimezone?: boolean }
  ) => string
): string {
  const DAY = 86_400_000;
  if (rangeMs <= DAY) {
    return formatDateTime(date, {
      includeSeconds: false,
      includeTimezone: false,
    });
  }
  if (rangeMs <= 7 * DAY) {
    return formatDateTime(date, {
      includeSeconds: false,
      includeTimezone: false,
    });
  }
  return formatDate(date);
}

/** Flatten a nested object into dot-separated key-value pairs. */
function flattenObject(
  obj: Record<string, unknown>,
  labels: { yes: string; no: string },
  prefix = ''
): Record<string, string> {
  const result: Record<string, string> = {};
  for (const [k, v] of Object.entries(obj)) {
    const key = prefix ? `${prefix}.${k}` : k;
    if (v != null && typeof v === 'object' && !Array.isArray(v)) {
      Object.assign(
        result,
        flattenObject(v as Record<string, unknown>, labels, key)
      );
    } else {
      result[key] = formatGenericComparisonValue(v, labels);
    }
  }
  return result;
}

function formatGenericComparisonValue(
  value: unknown,
  labels: { yes: string; no: string }
): string {
  if (value == null || value === '') return '-';
  if (typeof value === 'boolean') return value ? labels.yes : labels.no;
  if (Array.isArray(value)) return value.join(', ');
  return String(value);
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return value != null && typeof value === 'object' && !Array.isArray(value);
}

function resolveTaskComparisonConfig(
  config: Record<string, unknown>
): Record<string, unknown> {
  const current = config.current;
  const baseConfig = isRecord(current)
    ? current
    : Object.fromEntries(
        Object.entries(config).filter(
          ([key]) => !['initial', 'current', 'revisions'].includes(key)
        )
      );

  const result = { ...baseConfig };
  if (config.config_hash !== undefined) {
    result.config_hash = config.config_hash;
  }
  if (config.segment_index !== undefined) {
    result.segment_index = config.segment_index;
  }
  return result;
}

function titleCaseConfigKey(key: string): string {
  return key
    .replace(/^parameters\./, '')
    .replace(/\./g, ' ')
    .replace(/_/g, ' ')
    .replace(/\b\w/g, (c) => c.toUpperCase());
}

function resolveStrategyComparisonLabel(
  label: StrategyComparisonLabel | undefined,
  fallbackMap: Map<string, string> | undefined,
  key: string
): StrategyComparisonLabel {
  if (label) return label;
  if (fallbackMap) return { primary: resolveParameterLabel(fallbackMap, key) };
  return { primary: titleCaseConfigKey(key) };
}

function resolveTaskComparisonLabel(
  labelMap: Map<string, string> | undefined,
  key: string
): StrategyComparisonLabel {
  const directLabel = labelMap?.get(key);
  if (directLabel) return { primary: directLabel };

  const parts = key.split('.');
  for (let index = parts.length - 1; index > 0; index -= 1) {
    const prefix = parts.slice(0, index).join('.');
    const prefixLabel = labelMap?.get(prefix);
    if (prefixLabel) {
      return {
        primary: `${prefixLabel} / ${titleCaseConfigKey(
          parts.slice(index).join('.')
        )}`,
      };
    }
  }

  return { primary: titleCaseConfigKey(key) };
}

/** Result metric keys to display in the results comparison. */
const RESULT_KEYS = [
  'total_return',
  'total_pnl',
  'total_pnl_quote',
  'realized_pnl_quote',
  'unrealized_pnl_quote',
  'total_trades',
  'winning_trades',
  'losing_trades',
  'win_rate',
  'max_drawdown',
  'sharpe_ratio',
  'profit_factor',
  'average_win',
  'average_loss',
  'pnl_currency',
  'quote_currency',
];

function isMoneyAmountLike(value: unknown): value is MoneyAmountLike {
  return (
    value != null &&
    typeof value === 'object' &&
    'amount' in value &&
    'currency' in value
  );
}

function moneyPayload(value: unknown): MoneyAmountLike | null {
  if (!isMoneyAmountLike(value) || value.amount == null) return null;
  return value;
}

function metricMoney(
  metrics: Record<string, unknown> | null | undefined,
  key: string
): MoneyAmountLike | null {
  if (!metrics) return null;
  if (key.endsWith('_quote')) {
    return (
      moneyPayload(metrics[`${key}_money`]) ??
      moneyPayload(metrics[`${key}_display_money`])
    );
  }
  const displayMoney = moneyPayload(metrics[`${key}_display_money`]);
  if (displayMoney) return displayMoney;
  const directMoney = moneyPayload(metrics[`${key}_money`]);
  if (directMoney) return directMoney;
  if (key === 'total_pnl') {
    return (
      moneyPayload(metrics.total_pnl_display_money) ??
      moneyPayload(metrics.total_pnl_money)
    );
  }
  if (key === 'realized_pnl' || key === 'unrealized_pnl') {
    return (
      moneyPayload(metrics[`${key}_display_money`]) ??
      moneyPayload(metrics[`${key}_money`])
    );
  }
  return null;
}

function metricOverlayValue(
  metrics: Record<string, unknown>,
  key: string,
  format?: 'pct' | 'int' | 'currency'
): number | null {
  if (format === 'currency') {
    const money = metricMoney(metrics, key);
    const amount = Number(money?.amount);
    if (Number.isFinite(amount)) return amount;
  }
  const val = metrics[key];
  if (val == null || val === '') return null;
  const num = Number(val);
  if (!Number.isFinite(num)) return null;
  const scale = RATIO_KEYS.has(key) ? 100 : 1;
  return num * scale;
}

/** Truncate execution number to first 8 characters for display. */
function shortExecId(exec: TaskExecution): string {
  const id = String(exec.execution_number);
  return id.length > 8 ? id.slice(0, 8) : id;
}

function timestampMs(value: unknown): number | null {
  if (typeof value !== 'string' || value.trim() === '') return null;
  const ms = new Date(value).getTime();
  return Number.isFinite(ms) ? ms : null;
}

function executionMetricsRange(exec: TaskExecution): {
  startMs: number;
  endMs: number;
} | null {
  const cfg = exec.task_config as Record<string, unknown> | null;
  const startMs =
    timestampMs(cfg?.start_time) ??
    timestampMs(exec.started_at) ??
    timestampMs(exec.created_at);
  const endMs =
    timestampMs(cfg?.end_time) ?? timestampMs(exec.completed_at) ?? Date.now();
  if (startMs == null || endMs <= startMs) return null;
  return { startMs, endMs };
}

function comparisonMetricsInterval(
  executions: TaskExecution[],
  selectedInterval: number
): number {
  if (selectedInterval >= 1) return selectedInterval;

  let minMs = Infinity;
  let maxMs = -Infinity;
  for (const exec of executions) {
    const range = executionMetricsRange(exec);
    if (!range) continue;
    minMs = Math.min(minMs, range.startMs);
    maxMs = Math.max(maxMs, range.endMs);
  }

  if (Number.isFinite(minMs) && Number.isFinite(maxMs) && maxMs > minMs) {
    return computeAutoInterval((maxMs - minMs) / 1000);
  }

  return 1;
}

export function ExecutionComparisonDialog({
  open,
  onClose,
  executions,
  taskId,
  taskType,
}: ExecutionComparisonDialogProps) {
  const { t, i18n } = useTranslation('common');
  const [tabIndex, setTabIndex] = useState(0);
  const [interval, setInterval_] = useState(0);
  const [metricsData, setMetricsData] = useState<Map<string, MetricPoint[]>>(
    new Map()
  );
  const [metricsLoading, setMetricsLoading] = useState(false);
  const [metricsError, setMetricsError] = useState<string | null>(null);
  const mountedRef = useRef(true);
  const metricsLoadKeyRef = useRef<string | null>(null);
  const metricsRequestSeqRef = useRef(0);
  const { strategies } = useStrategies();

  // Sort executions by execution_number for consistent ordering
  const sorted = useMemo(
    () =>
      [...executions].sort((a, b) => {
        const aStr = String(a.execution_number);
        const bStr = String(b.execution_number);
        return aStr.localeCompare(bStr);
      }),
    [executions]
  );

  // shortExecId is defined at module level

  const metricsLoadKey = useMemo(
    () =>
      `${taskType}:${taskId}:${interval}:${sorted.map((exec) => exec.id).join('|')}`,
    [interval, sorted, taskId, taskType]
  );

  const strategyComparisonContext = useMemo(() => {
    const labelMap = new Map<string, string>();
    const schemaPropertiesByType = new Map<
      string,
      Record<string, ConfigProperty>
    >();
    const strategyTypes = new Set(
      sorted
        .map(
          (exec) =>
            resolveStrategyComparisonSnapshot(exec.strategy_config).strategyType
        )
        .filter(Boolean)
    );

    for (const strategyType of strategyTypes) {
      const parameterLabels = buildParameterLabelMap(
        strategies,
        strategyType,
        i18n.language
      );
      for (const [key, label] of parameterLabels) {
        labelMap.set(key, label);
      }

      const strategy = strategies.find((item) => item.id === strategyType);
      const schema = strategy?.config_schema as
        | { properties?: Record<string, ConfigProperty> }
        | undefined;
      if (schema?.properties) {
        schemaPropertiesByType.set(strategyType, schema.properties);
      }
    }

    return { labelMap, schemaPropertiesByType };
  }, [sorted, strategies, i18n.language]);

  // Fetch metrics for all executions.
  // For Auto mode (interval=0), compute a single interval from the union
  // time range across ALL compared executions so charts share the same
  // granularity.  For backtests, the data period comes from
  // task_config.start_time / end_time; for trading tasks, from
  // started_at / completed_at (or now if still running).
  const fetchAllMetrics = useCallback(async () => {
    const requestSeq = ++metricsRequestSeqRef.current;
    setMetricsLoading(true);
    setMetricsError(null);
    setMetricsData(new Map<string, MetricPoint[]>());
    try {
      const sharedInterval = comparisonMetricsInterval(sorted, interval);

      await Promise.all(
        sorted.map(async (exec) => {
          const page = await fetchPaginatedMetrics({
            taskId,
            taskType,
            executionRunId: exec.id,
            interval: sharedInterval,
            metricKeys: COMPARISON_METRIC_KEYS,
            pageSize: 500,
            maxPages: 10,
            onProgress: ({ accumulatedResults }) => {
              if (
                !mountedRef.current ||
                requestSeq !== metricsRequestSeqRef.current
              ) {
                return;
              }
              setMetricsData((current) => {
                const next = new Map(current);
                next.set(exec.id, accumulatedResults);
                return next;
              });
            },
          });
          if (
            mountedRef.current &&
            requestSeq === metricsRequestSeqRef.current
          ) {
            setMetricsData((current) => {
              const next = new Map(current);
              next.set(exec.id, page.results);
              return next;
            });
          }
        })
      );
    } catch {
      if (mountedRef.current && requestSeq === metricsRequestSeqRef.current) {
        setMetricsError(t('comparison.error'));
      }
    } finally {
      if (mountedRef.current && requestSeq === metricsRequestSeqRef.current) {
        setMetricsLoading(false);
      }
    }
  }, [sorted, taskId, taskType, interval, t]);

  const handleRefreshMetrics = useCallback(async () => {
    metricsLoadKeyRef.current = metricsLoadKey;
    await fetchAllMetrics();
  }, [fetchAllMetrics, metricsLoadKey]);

  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
    };
  }, []);

  useEffect(() => {
    if (!open) {
      metricsLoadKeyRef.current = null;
      metricsRequestSeqRef.current += 1;
      setMetricsData(new Map<string, MetricPoint[]>());
      setMetricsError(null);
      setMetricsLoading(false);
      return;
    }

    if (
      metricsLoadKeyRef.current != null &&
      metricsLoadKeyRef.current !== metricsLoadKey
    ) {
      metricsLoadKeyRef.current = null;
      metricsRequestSeqRef.current += 1;
      setMetricsData(new Map<string, MetricPoint[]>());
      setMetricsError(null);
      setMetricsLoading(false);
    }
  }, [open, metricsLoadKey]);

  // Load metrics once when the tab is first opened. Further reloads are manual.
  useEffect(() => {
    if (!open || tabIndex !== 3) return;
    if (metricsLoadKeyRef.current === metricsLoadKey) return;

    metricsLoadKeyRef.current = metricsLoadKey;
    void fetchAllMetrics();
  }, [open, tabIndex, metricsLoadKey, fetchAllMetrics]);

  return (
    <Dialog
      open={open}
      onClose={onClose}
      fullScreen
      TransitionComponent={SlideUp}
    >
      <AppBar sx={{ position: 'relative' }} color="default" elevation={1}>
        <Toolbar
          sx={{
            flexDirection: { xs: 'column', sm: 'row' },
            alignItems: { xs: 'flex-start', sm: 'center' },
            gap: 1,
            py: { xs: 1, sm: 0 },
          }}
        >
          <Box
            sx={{
              display: 'flex',
              alignItems: 'center',
              width: { xs: '100%', sm: 'auto' },
            }}
          >
            <IconButton edge="start" onClick={onClose} aria-label="close">
              <CloseIcon />
            </IconButton>
            <Typography sx={{ ml: 1 }} variant="h6">
              {t('comparison.title')}
            </Typography>
          </Box>
          {/* Legend chips */}
          <Box
            sx={{
              display: 'flex',
              gap: 0.5,
              flexWrap: 'wrap',
              pl: { xs: 1, sm: 0 },
            }}
          >
            {sorted.map((exec, i) => (
              <Box
                key={exec.id}
                sx={{
                  display: 'flex',
                  alignItems: 'center',
                  gap: 0.5,
                  px: 1,
                  py: 0.25,
                  borderRadius: 1,
                  bgcolor: 'action.hover',
                }}
              >
                <Box
                  sx={{
                    width: 12,
                    height: 12,
                    borderRadius: '50%',
                    bgcolor: EXEC_COLORS[i % EXEC_COLORS.length],
                  }}
                />
                <Typography variant="caption">#{shortExecId(exec)}</Typography>
              </Box>
            ))}
          </Box>
          {/* Global refresh */}
          <Tooltip title={t('comparison.refresh', { defaultValue: 'Refresh' })}>
            <span>
              <IconButton
                size="small"
                onClick={handleRefreshMetrics}
                disabled={metricsLoading}
                sx={{ ml: 'auto' }}
              >
                {metricsLoading ? (
                  <CircularProgress size={18} />
                ) : (
                  <RefreshIcon fontSize="small" />
                )}
              </IconButton>
            </span>
          </Tooltip>
        </Toolbar>
        <Tabs
          value={tabIndex}
          onChange={(_e, v) => setTabIndex(v)}
          sx={{ px: 2 }}
        >
          <Tab label={t('comparison.taskConfig')} />
          <Tab label={t('comparison.strategyConfig')} />
          <Tab label={t('comparison.results')} />
          <Tab label={t('comparison.metricsOverlay')} />
        </Tabs>
      </AppBar>

      <Box sx={{ flex: 1, overflow: 'auto', p: 2 }}>
        {tabIndex === 0 && (
          <ConfigComparisonPanel
            executions={sorted}
            type="task"
            taskType={taskType}
          />
        )}
        {tabIndex === 1 && (
          <ConfigComparisonPanel
            executions={sorted}
            type="strategy"
            taskType={taskType}
            paramLabelMap={strategyComparisonContext.labelMap}
            schemaPropertiesByType={
              strategyComparisonContext.schemaPropertiesByType
            }
          />
        )}
        {tabIndex === 2 && <ResultsComparisonPanel executions={sorted} />}
        {tabIndex === 3 && (
          <MetricsOverlayPanel
            executions={sorted}
            metricsData={metricsData}
            isLoading={metricsLoading}
            error={metricsError}
            interval={interval}
            onIntervalChange={setInterval_}
            onRefresh={handleRefreshMetrics}
          />
        )}
      </Box>
    </Dialog>
  );
}

/* ------------------------------------------------------------------ */
/*  Config Comparison Panel (task config or strategy config)          */
/* ------------------------------------------------------------------ */

function ConfigComparisonPanel({
  executions,
  type,
  taskType,
  paramLabelMap,
  schemaPropertiesByType,
}: {
  executions: TaskExecution[];
  type: 'task' | 'strategy';
  taskType: TaskType;
  paramLabelMap?: Map<string, string>;
  schemaPropertiesByType?: Map<string, Record<string, ConfigProperty>>;
}) {
  const { t, i18n } = useTranslation('common');
  const { timezone } = useDateTimeFormatter({ includeTimezone: true });
  const booleanLabels = useMemo(
    () => ({
      yes: t('labels.yes'),
      no: t('labels.no'),
    }),
    [t]
  );
  const taskLabelMap = useMemo(() => {
    if (type !== 'task') return undefined;
    return buildTaskComparisonLabelMap(t, taskType, {
      includeDebugOptions: true,
      language: i18n.language,
      timezone,
    });
  }, [i18n.language, t, taskType, timezone, type]);

  const { configs, allKeys, keyLabels } = useMemo(() => {
    if (type === 'strategy') {
      const strategyData = buildStrategyComparisonData({
        configs: executions.map((exec) => exec.strategy_config),
        schemaPropertiesByType,
        language: i18n.language,
        labels: booleanLabels,
      });
      return {
        configs: strategyData.configs,
        allKeys: strategyData.keys,
        keyLabels: strategyData.labels,
      };
    }

    const taskConfigs = executions.map((exec) => {
      const raw = exec.task_config ?? {};
      const config = resolveTaskComparisonConfig(
        raw as Record<string, unknown>
      );
      return flattenObject(config, booleanLabels);
    });

    const keys = new Set<string>();
    for (const cfg of taskConfigs) {
      for (const k of Object.keys(cfg)) {
        keys.add(k);
      }
    }
    return { configs: taskConfigs, allKeys: [...keys].sort(), keyLabels: {} };
  }, [booleanLabels, executions, i18n.language, schemaPropertiesByType, type]);

  // Determine which keys differ
  const diffKeys = useMemo(() => {
    return new Set(
      allKeys.filter((key) => {
        const values = configs.map((c) => c[key] ?? '-');
        return values.some((v) => v !== values[0]);
      })
    );
  }, [allKeys, configs]);

  const [showAll, setShowAll] = useState(false);
  const displayKeys = showAll
    ? allKeys
    : allKeys.filter((k) => diffKeys.has(k));

  if (allKeys.length === 0) {
    return <Alert severity="info">{t('comparison.noSnapshot')}</Alert>;
  }

  return (
    <Box>
      <Box sx={{ display: 'flex', alignItems: 'center', mb: 2, gap: 1 }}>
        <Typography variant="subtitle2" color="text.secondary">
          {diffKeys.size > 0
            ? `${diffKeys.size} ${t('comparison.configDiff').toLowerCase()}`
            : t('comparison.noDifferences')}
        </Typography>
        <IconButton size="small" onClick={() => setShowAll((v) => !v)}>
          {showAll ? <ExpandLessIcon /> : <ExpandMoreIcon />}
        </IconButton>
        <Typography variant="caption" color="text.secondary">
          {showAll
            ? t('comparison.showDifferencesOnly', {
                defaultValue: 'Show differences only',
              })
            : t('comparison.showAll', { defaultValue: 'Show all' })}
        </Typography>
      </Box>

      {displayKeys.length === 0 && !showAll && (
        <Typography color="text.secondary">
          {t('comparison.noDifferences')}
        </Typography>
      )}

      <Box sx={{ overflowX: 'auto' }}>
        <Box
          component="table"
          sx={{
            width: '100%',
            borderCollapse: 'collapse',
            '& th, & td': {
              border: '1px solid',
              borderColor: 'divider',
              px: 1.5,
              py: 0.75,
              fontSize: '0.8125rem',
              verticalAlign: 'top',
            },
            '& th': {
              bgcolor: 'action.hover',
              fontWeight: 600,
              whiteSpace: 'nowrap',
            },
          }}
        >
          <thead>
            <tr>
              <th style={{ minWidth: 180 }}>
                {t('comparison.setting', { defaultValue: 'Setting' })}
              </th>
              {executions.map((exec, i) => (
                <th key={exec.id} style={{ minWidth: 160 }}>
                  <Box sx={{ display: 'flex', alignItems: 'center', gap: 0.5 }}>
                    <Box
                      sx={{
                        width: 10,
                        height: 10,
                        borderRadius: '50%',
                        bgcolor: EXEC_COLORS[i % EXEC_COLORS.length],
                        flexShrink: 0,
                      }}
                    />
                    {t('comparison.execution', {
                      number: shortExecId(exec),
                    })}
                  </Box>
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {displayKeys.map((key) => {
              const isDiff = diffKeys.has(key);
              const label =
                type === 'strategy'
                  ? resolveStrategyComparisonLabel(
                      keyLabels[key],
                      paramLabelMap,
                      key
                    )
                  : resolveTaskComparisonLabel(taskLabelMap, key);
              return (
                <tr key={key}>
                  <td>
                    <Typography
                      variant="body2"
                      fontWeight={isDiff ? 600 : 400}
                      sx={{ fontSize: '0.75rem' }}
                    >
                      {label.primary}
                    </Typography>
                    {label.secondary ? (
                      <Typography
                        variant="caption"
                        color="text.secondary"
                        sx={{
                          display: 'block',
                          fontSize: '0.6875rem',
                          lineHeight: 1.3,
                        }}
                      >
                        {label.secondary}
                      </Typography>
                    ) : null}
                  </td>
                  {configs.map((cfg, i) => (
                    <td
                      key={executions[i].id}
                      style={{
                        backgroundColor: isDiff
                          ? 'rgba(255,235,59,0.08)'
                          : undefined,
                      }}
                    >
                      <Typography
                        variant="body2"
                        sx={{
                          fontFamily: 'monospace',
                          fontSize: '0.75rem',
                          wordBreak: 'break-all',
                        }}
                      >
                        {cfg[key] ?? '-'}
                      </Typography>
                    </td>
                  ))}
                </tr>
              );
            })}
          </tbody>
        </Box>
      </Box>
    </Box>
  );
}

/* ------------------------------------------------------------------ */
/*  Results Comparison Panel                                          */
/* ------------------------------------------------------------------ */

function formatResultMetric(
  metrics: Record<string, unknown> | null | undefined,
  key: string
): { display: string; numeric: number | null } {
  const money = metricMoney(metrics, key);
  if (money) {
    const amount = Number(money.amount);
    return {
      display: formatMoneyPayload(money, {
        minimumFractionDigits: 2,
        maximumFractionDigits: 2,
        signed:
          key.includes('pnl') ||
          key === 'average_win' ||
          key === 'average_loss',
      }),
      numeric: Number.isFinite(amount) ? amount : null,
    };
  }

  const value = metrics?.[key];
  if (value == null) return { display: '-', numeric: null };
  const text = String(value);
  const numeric = Number(text);
  if (!Number.isFinite(numeric)) return { display: text, numeric: null };

  if (key === 'total_return' || key === 'win_rate' || key === 'max_drawdown') {
    return { display: formatAppPercent(numeric, 2, true), numeric };
  }

  if (key.endsWith('_quote')) {
    return {
      display: formatMoneyAmount(
        numeric,
        String(metrics?.quote_currency || ''),
        {
          minimumFractionDigits: 2,
          maximumFractionDigits: 2,
          signed: true,
        }
      ),
      numeric,
    };
  }

  if (key.includes('pnl') || key === 'average_win' || key === 'average_loss') {
    return {
      display: formatMoneyAmount(numeric, String(metrics?.pnl_currency || ''), {
        minimumFractionDigits: 2,
        maximumFractionDigits: 2,
        signed: true,
      }),
      numeric,
    };
  }

  return { display: text, numeric };
}

function ResultsComparisonPanel({
  executions,
}: {
  executions: TaskExecution[];
}) {
  const { t } = useTranslation('common');

  const resultRows = useMemo(() => {
    return RESULT_KEYS.map((key) => {
      const values = executions.map((exec) =>
        formatResultMetric(exec.metrics, key)
      );
      return { key, values };
    }).filter((row) => row.values.some((v) => v.display !== '-'));
  }, [executions]);

  if (resultRows.length === 0) {
    return <Alert severity="info">{t('comparison.noSnapshot')}</Alert>;
  }

  return (
    <Box sx={{ overflowX: 'auto' }}>
      <Box
        component="table"
        sx={{
          width: '100%',
          borderCollapse: 'collapse',
          '& th, & td': {
            border: '1px solid',
            borderColor: 'divider',
            px: 1.5,
            py: 0.75,
            fontSize: '0.8125rem',
          },
          '& th': {
            bgcolor: 'action.hover',
            fontWeight: 600,
            whiteSpace: 'nowrap',
          },
        }}
      >
        <thead>
          <tr>
            <th style={{ minWidth: 180 }}>Metric</th>
            {executions.map((exec, i) => (
              <th key={exec.id} style={{ minWidth: 140 }}>
                <Box sx={{ display: 'flex', alignItems: 'center', gap: 0.5 }}>
                  <Box
                    sx={{
                      width: 10,
                      height: 10,
                      borderRadius: '50%',
                      bgcolor: EXEC_COLORS[i % EXEC_COLORS.length],
                      flexShrink: 0,
                    }}
                  />
                  {t('comparison.execution', {
                    number: shortExecId(exec),
                  })}
                </Box>
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {resultRows.map(({ key, values }) => {
            const allSame = values.every(
              (v) => v.display === values[0].display
            );
            return (
              <tr key={key}>
                <td>
                  <Typography
                    variant="body2"
                    fontWeight={allSame ? 400 : 600}
                    sx={{ fontFamily: 'monospace', fontSize: '0.75rem' }}
                  >
                    {t(`metrics.${key}`, {
                      defaultValue: key.replace(/_/g, ' '),
                    })}
                  </Typography>
                </td>
                {values.map((v, i) => {
                  const num = v.numeric;
                  const isPnl =
                    key.includes('pnl') ||
                    key === 'total_return' ||
                    key === 'average_win' ||
                    key === 'average_loss';
                  const color =
                    isPnl && num != null
                      ? num >= 0
                        ? 'success.main'
                        : 'error.main'
                      : undefined;
                  return (
                    <td
                      key={executions[i].id}
                      style={{
                        textAlign: 'right',
                        backgroundColor: allSame
                          ? undefined
                          : 'rgba(255,235,59,0.08)',
                      }}
                    >
                      <Typography
                        variant="body2"
                        color={color}
                        sx={{
                          fontFamily: 'monospace',
                          fontSize: '0.75rem',
                        }}
                      >
                        {v.display}
                      </Typography>
                    </td>
                  );
                })}
              </tr>
            );
          })}
        </tbody>
      </Box>
    </Box>
  );
}

/* ------------------------------------------------------------------ */
/*  Metrics Overlay Panel                                             */
/* ------------------------------------------------------------------ */

function MetricsOverlayPanel({
  executions,
  metricsData,
  isLoading,
  error,
  interval,
  onIntervalChange,
  onRefresh,
}: {
  executions: TaskExecution[];
  metricsData: Map<string, MetricPoint[]>;
  isLoading: boolean;
  error: string | null;
  interval: number;
  onIntervalChange: (v: number) => void;
  onRefresh: () => void;
}) {
  const { t } = useTranslation('common');
  const { formatDateTime, formatDate } = useDateTimeFormatter();

  // Determine which metric keys have data across any execution
  const availableMetrics = useMemo(() => {
    const keysWithData = new Set<string>();
    for (const points of metricsData.values()) {
      for (const point of points) {
        for (const metric of CHART_METRICS) {
          if (
            metricOverlayValue(point.metrics, metric.key, metric.format) != null
          ) {
            keysWithData.add(metric.key);
          }
        }
      }
    }
    return CHART_METRICS.filter((m) => keysWithData.has(m.key));
  }, [metricsData]);

  // Build chart data: for each metric, build a unified x-axis with all
  // timestamps merged across executions, and per-execution y arrays with
  // null for timestamps where that execution has no data.
  const chartDataMap = useMemo(() => {
    const map: Record<
      string,
      {
        xAll: Date[];
        series: { execIndex: number; y: (number | null)[] }[];
      }
    > = {};

    for (const m of availableMetrics) {
      // Collect per-execution data as timestamp→value maps
      const execData: {
        execIndex: number;
        byTime: Map<number, number>;
      }[] = [];

      executions.forEach((exec, idx) => {
        const points = metricsData.get(exec.id) ?? [];
        const byTime = new Map<number, number>();
        for (const point of points) {
          const value = metricOverlayValue(point.metrics, m.key, m.format);
          if (value != null) {
            byTime.set(point.t, value);
          }
        }
        if (byTime.size >= 2) {
          execData.push({ execIndex: idx, byTime });
        }
      });

      if (execData.length === 0) continue;

      // Merge all timestamps into a sorted unique set
      const allTimestamps = new Set<number>();
      for (const ed of execData) {
        for (const t of ed.byTime.keys()) allTimestamps.add(t);
      }
      const sortedTs = [...allTimestamps].sort((a, b) => a - b);
      const xAll = sortedTs.map((t) => new Date(t * 1000));

      // Build y arrays with null for missing timestamps
      const series = execData.map((ed) => ({
        execIndex: ed.execIndex,
        y: sortedTs.map((t) => ed.byTime.get(t) ?? null),
      }));

      map[m.key] = { xAll, series };
    }
    return map;
  }, [availableMetrics, executions, metricsData]);

  if (error) {
    return <Alert severity="error">{error}</Alert>;
  }

  return (
    <Box>
      {/* Granularity toolbar */}
      <Box sx={{ mb: 2, display: 'flex', alignItems: 'center', gap: 1 }}>
        <ToggleButtonGroup
          value={interval}
          exclusive
          onChange={(_e, val) => {
            if (val !== null) onIntervalChange(val);
          }}
          size="small"
          aria-label="Granularity"
        >
          {INTERVAL_OPTIONS.map((opt) => (
            <ToggleButton
              key={opt.value}
              value={opt.value}
              sx={{ px: 1.5, py: 0.25, fontSize: '0.75rem' }}
            >
              {opt.label}
            </ToggleButton>
          ))}
        </ToggleButtonGroup>
        <Tooltip title="Refresh">
          <span>
            <IconButton size="small" onClick={onRefresh} disabled={isLoading}>
              {isLoading ? (
                <CircularProgress size={16} />
              ) : (
                <Typography variant="caption">↻</Typography>
              )}
            </IconButton>
          </span>
        </Tooltip>
      </Box>

      {isLoading ? <LinearProgress sx={{ mb: 2 }} /> : null}

      {availableMetrics.length === 0 && (
        <Box sx={{ display: 'flex', justifyContent: 'center', p: 4 }}>
          {isLoading ? (
            <CircularProgress size={24} />
          ) : (
            <Typography color="text.secondary">
              {t('metrics.noData')}
            </Typography>
          )}
        </Box>
      )}

      <Grid container spacing={2}>
        {availableMetrics.map((m) => {
          const chartData = chartDataMap[m.key];
          if (!chartData || chartData.series.length === 0) return null;

          const { xAll, series } = chartData;
          const rangeMs =
            xAll.length >= 2
              ? xAll[xAll.length - 1].getTime() - xAll[0].getTime()
              : 0;

          return (
            <Grid key={m.key} size={{ xs: 12, md: 6 }}>
              <Paper
                variant="outlined"
                sx={{ p: 1.5, height: CHART_HEIGHT + 40, overflow: 'hidden' }}
              >
                <Typography variant="subtitle2" sx={{ mb: 0.5 }}>
                  {t(`metrics.${m.key}`, {
                    defaultValue: m.key.replace(/_/g, ' '),
                  })}
                </Typography>
                <LineChart
                  xAxis={[
                    {
                      scaleType: 'time' as const,
                      data: xAll,
                      tickNumber: 8,
                      tickLabelStyle: { fontSize: 10 },
                      valueFormatter: (v: Date, ctx: { location: string }) => {
                        if (ctx.location === 'tooltip') {
                          return formatDateTime(v, {
                            includeSeconds: true,
                            includeTimezone: true,
                          });
                        }
                        return formatTickLabel(
                          v,
                          rangeMs,
                          formatDate,
                          formatDateTime
                        );
                      },
                    },
                  ]}
                  yAxis={[
                    {
                      position: 'right',
                      width: 60,
                      tickNumber: 5,
                      valueFormatter: (v: number | null) =>
                        v != null ? formatYLabel(v, m.format) : '',
                    },
                  ]}
                  series={series.map((s) => ({
                    data: s.y,
                    color: EXEC_COLORS[s.execIndex % EXEC_COLORS.length],
                    showMark: false,
                    label: `#${shortExecId(executions[s.execIndex])}`,
                    connectNulls: true,
                  }))}
                  axisHighlight={{ x: 'line', y: 'none' }}
                  grid={{ vertical: true, horizontal: true }}
                  height={CHART_HEIGHT}
                  margin={{ left: 8, right: 68, top: 8, bottom: 36 }}
                  slotProps={{
                    axisTickLabel: { style: { fontSize: 10 } },
                    legend: {
                      direction: 'row',
                      position: {
                        vertical: 'top',
                        horizontal: 'left',
                      },
                      padding: 0,
                      itemMarkWidth: 8,
                      itemMarkHeight: 8,
                      labelStyle: { fontSize: 10 },
                    } as Record<string, unknown>,
                  }}
                />
              </Paper>
            </Grid>
          );
        })}
      </Grid>
    </Box>
  );
}
