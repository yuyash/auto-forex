import { useCallback, useMemo, useState, type DragEvent } from 'react';
import {
  Alert,
  Box,
  CircularProgress,
  Divider,
  IconButton,
  Tooltip,
  Typography,
  type TypographyProps,
} from '@mui/material';
import {
  DragIndicator as DragIcon,
  Refresh as RefreshIcon,
  Settings as SettingsIcon,
} from '@mui/icons-material';
import { useTranslation } from 'react-i18next';
import { useAuth } from '../../../contexts/AuthContext';
import type { TaskSummary } from '../../../hooks/useTaskSummary';
import type {
  StrategySnapshotCard,
  StrategySnapshotResponse,
} from '../../../types/strategyVisualization';
import type { MetricPoint } from '../../../utils/fetchMetrics';
import {
  formatAppNumber,
  formatMoneyAmount,
  formatMoneyPayload,
  formatAppPercent,
  type NumberFormatSeparators,
} from '../../../utils/numberFormat';
import { useNumberFormatter } from '../../../hooks/useNumberFormatter';
import { useItemOrder } from '../../../hooks/useItemOrder';
import { ItemOrderDialog } from '../../common/ItemOrderDialog';
import { formatCurrencyConversionContext } from '../../../utils/currencyConversion';

type DetailNamespace = 'backtest' | 'trading';

export interface ExecutionStatusExtraItem {
  id: string;
  label: string;
  value: string;
  color?: TypographyProps['color'];
}

interface ExecutionStatusSummaryProps {
  taskNamespace: DetailNamespace;
  summary: TaskSummary;
  latestMetrics?: MetricPoint | null;
  pnlCurrency: string;
  displayedMarginRatio?: number | null;
  snapshot?: StrategySnapshotResponse | null;
  isSnapshotLoading?: boolean;
  snapshotError?: Error | null;
  extraItems?: ExecutionStatusExtraItem[];
  onRefresh?: () => void | Promise<unknown>;
  isRefreshing?: boolean;
}

interface ExecutionStatusItem {
  id: string;
  label: string;
  value: string;
  color?: TypographyProps['color'];
  tooltip?: string;
}

const METRIC_KEYS: Array<{
  key:
    | 'win_rate'
    | 'winning_trades'
    | 'losing_trades'
    | 'total_return'
    | 'current_base_units'
    | 'ticks_per_second';
  format: 'pct' | 'int' | 'rate';
}> = [
  { key: 'ticks_per_second', format: 'rate' },
  { key: 'current_base_units', format: 'int' },
  { key: 'win_rate', format: 'pct' },
  { key: 'winning_trades', format: 'int' },
  { key: 'losing_trades', format: 'int' },
  { key: 'total_return', format: 'pct' },
];

export function ExecutionStatusSummary({
  taskNamespace,
  summary,
  latestMetrics = null,
  pnlCurrency,
  displayedMarginRatio,
  snapshot = null,
  isSnapshotLoading = false,
  snapshotError = null,
  extraItems = [],
  onRefresh,
  isRefreshing = false,
}: ExecutionStatusSummaryProps) {
  const { t } = useTranslation(['common', 'strategy', taskNamespace]);
  const { user } = useAuth();
  const { separators } = useNumberFormatter();
  const snapshotCards = snapshot?.snapshot.cards;
  const accountCurrency = summary.execution.accountCurrency || pnlCurrency;
  const timezone = user?.timezone || 'UTC';
  const language = user?.language;
  const [orderDialogOpen, setOrderDialogOpen] = useState(false);
  const [dragIndex, setDragIndex] = useState<number | null>(null);
  const items = useMemo(() => {
    const cards = snapshotCards ?? [];
    const snapshotCardIds = new Set(cards.map((card) => card.id));
    return [
      ...buildResultItems({
        taskNamespace,
        summary,
        latestMetrics,
        pnlCurrency,
        displayedMarginRatio,
        hiddenIds: snapshotCardIds,
        language,
        separators,
        t,
        timezone,
      }),
      ...extraItems,
      ...cards.map((card) =>
        snapshotCardToItem(card, accountCurrency, pnlCurrency, t, separators)
      ),
    ];
  }, [
    accountCurrency,
    displayedMarginRatio,
    extraItems,
    latestMetrics,
    language,
    pnlCurrency,
    separators,
    summary,
    snapshotCards,
    t,
    taskNamespace,
    timezone,
  ]);
  const { orderedItems, updateOrder, resetOrder } = useItemOrder(
    `execution_status_${taskNamespace}`,
    items
  );

  const moveTile = useCallback(
    (from: number, to: number) => {
      if (from < 0 || to < 0 || from === to || to >= orderedItems.length) {
        return;
      }
      const ids = orderedItems.map((item) => item.id);
      const [moved] = ids.splice(from, 1);
      ids.splice(to, 0, moved);
      updateOrder(ids);
    },
    [orderedItems, updateOrder]
  );

  const handleTileDragStart = useCallback(
    (event: DragEvent, index: number) => {
      setDragIndex(index);
      event.dataTransfer.effectAllowed = 'move';
      event.dataTransfer.setData('text/plain', orderedItems[index]?.id ?? '');
    },
    [orderedItems]
  );

  const handleTileDragOver = useCallback(
    (event: DragEvent, index: number) => {
      event.preventDefault();
      event.dataTransfer.dropEffect = 'move';
      if (dragIndex !== null && dragIndex !== index) {
        moveTile(dragIndex, index);
        setDragIndex(index);
      }
    },
    [dragIndex, moveTile]
  );

  const handleTileDragEnd = useCallback(() => setDragIndex(null), []);

  if (items.length === 0 && !snapshotError && !isSnapshotLoading) {
    return null;
  }

  return (
    <Box>
      <Divider sx={{ my: 2 }} />
      <Box
        sx={{
          display: 'flex',
          alignItems: 'center',
          gap: 1,
          flexWrap: 'wrap',
          mb: 1.5,
        }}
      >
        <Typography variant="h6">
          {t('common:labels.executionStatus', 'Execution Status')}
        </Typography>
        {isSnapshotLoading || isRefreshing ? (
          <CircularProgress size={18} />
        ) : null}
        {onRefresh ? (
          <Tooltip title={t('actions.refresh')}>
            <span>
              <IconButton
                size="small"
                onClick={() => void onRefresh()}
                disabled={isRefreshing}
                aria-label={t('actions.refresh')}
              >
                <RefreshIcon fontSize="small" />
              </IconButton>
            </span>
          </Tooltip>
        ) : null}
        <Tooltip title={t('executionStatusOrder.configureTiles')}>
          <span>
            <IconButton
              size="small"
              onClick={() => setOrderDialogOpen(true)}
              disabled={orderedItems.length < 2}
              aria-label={t('executionStatusOrder.configureTiles')}
            >
              <SettingsIcon fontSize="small" />
            </IconButton>
          </span>
        </Tooltip>
      </Box>

      {snapshotError ? (
        <Alert severity="warning" sx={{ mb: 1.5 }}>
          {snapshotError.message}
        </Alert>
      ) : null}

      <Box
        sx={{
          display: 'grid',
          gap: 1,
          gridTemplateColumns: {
            xs: 'repeat(2, minmax(0, 1fr))',
            sm: 'repeat(3, minmax(0, 1fr))',
            lg: 'repeat(4, minmax(0, 1fr))',
            xl: 'repeat(6, minmax(0, 1fr))',
          },
        }}
      >
        {orderedItems.map((item, index) => (
          <ExecutionStatusTile
            key={item.id}
            item={item}
            index={index}
            isDragging={dragIndex === index}
            onDragStart={handleTileDragStart}
            onDragOver={handleTileDragOver}
            onDragEnd={handleTileDragEnd}
          />
        ))}
      </Box>
      {orderDialogOpen ? (
        <ItemOrderDialog
          open={orderDialogOpen}
          title={t('executionStatusOrder.title')}
          description={t('executionStatusOrder.description')}
          items={orderedItems.map((item) => ({
            id: item.id,
            label: item.label,
            secondary: item.value,
          }))}
          onClose={() => setOrderDialogOpen(false)}
          onSave={updateOrder}
          onReset={resetOrder}
        />
      ) : null}
    </Box>
  );
}

function ExecutionStatusTile({
  item,
  index,
  isDragging,
  onDragStart,
  onDragOver,
  onDragEnd,
}: {
  item: ExecutionStatusItem;
  index: number;
  isDragging: boolean;
  onDragStart: (event: DragEvent, index: number) => void;
  onDragOver: (event: DragEvent, index: number) => void;
  onDragEnd: () => void;
}) {
  const tile = (
    <Box
      draggable
      onDragStart={(event) => onDragStart(event, index)}
      onDragOver={(event) => onDragOver(event, index)}
      onDragEnd={onDragEnd}
      sx={{
        border: 1,
        borderColor: isDragging ? 'primary.main' : 'divider',
        borderRadius: 1,
        p: 1.25,
        minWidth: 0,
        minHeight: 68,
        cursor: 'grab',
        bgcolor: isDragging ? 'action.hover' : 'background.paper',
        '&:active': { cursor: 'grabbing' },
        '&:hover': {
          borderColor: 'text.secondary',
        },
      }}
    >
      <Box
        sx={{
          display: 'flex',
          alignItems: 'flex-start',
          justifyContent: 'space-between',
          gap: 0.5,
        }}
      >
        <Typography
          variant="caption"
          color="text.secondary"
          sx={{
            display: 'block',
            lineHeight: 1.25,
            overflowWrap: 'anywhere',
          }}
        >
          {item.label}
        </Typography>
        <DragIcon
          fontSize="small"
          sx={{ color: 'text.disabled', mt: -0.25, flexShrink: 0 }}
        />
      </Box>
      <Typography
        variant="body2"
        color={item.color}
        sx={{
          fontWeight: 600,
          lineHeight: 1.35,
          overflowWrap: 'anywhere',
          wordBreak: 'break-word',
        }}
      >
        {item.value}
      </Typography>
    </Box>
  );
  if (!item.tooltip) return tile;
  return (
    <Tooltip title={item.tooltip} arrow>
      {tile}
    </Tooltip>
  );
}

function buildResultItems({
  taskNamespace,
  summary,
  latestMetrics,
  pnlCurrency,
  displayedMarginRatio,
  hiddenIds,
  language,
  separators,
  t,
  timezone,
}: {
  taskNamespace: DetailNamespace;
  summary: TaskSummary;
  latestMetrics: MetricPoint | null;
  pnlCurrency: string;
  displayedMarginRatio?: number | null;
  hiddenIds?: Set<string>;
  language?: string;
  separators: NumberFormatSeparators;
  t: ReturnType<typeof useTranslation>['t'];
  timezone: string;
}): ExecutionStatusItem[] {
  const detailLabel = (key: string) => t(`${taskNamespace}:detail.${key}`);
  const pnlConversionTooltip = formatCurrencyConversionContext(
    summary.pnl.displayConversionContext,
    { language, separators, t, timezone }
  );
  const balanceConversionTooltip = formatCurrencyConversionContext(
    summary.execution.currentBalanceDisplayConversionContext,
    { language, separators, t, timezone }
  );
  const items: ExecutionStatusItem[] = [
    ...buildStatusReasonItems(summary, detailLabel),
    {
      id: 'realized_pnl',
      label: detailLabel('realizedPnl'),
      value: formatPnlValue(
        summary.pnl.realizedDisplayMoney,
        summary.pnl.realized,
        pnlCurrency,
        true,
        separators
      ),
      color: summary.pnl.realized >= 0 ? 'success.main' : 'error.main',
      tooltip: pnlConversionTooltip,
    },
    {
      id: 'unrealized_pnl',
      label: detailLabel('unrealizedPnl'),
      value: formatPnlValue(
        summary.pnl.unrealizedDisplayMoney,
        summary.pnl.unrealized,
        pnlCurrency,
        true,
        separators
      ),
      color: summary.pnl.unrealized >= 0 ? 'success.main' : 'error.main',
      tooltip: pnlConversionTooltip,
    },
    ...buildCurrentBalanceItems(
      summary,
      pnlCurrency,
      detailLabel,
      separators,
      balanceConversionTooltip
    ),
    {
      id: 'total_trades',
      label: detailLabel('totalTradesCount'),
      value: formatWholeNumber(summary.counts.totalTrades, separators),
    },
    {
      id: 'open_positions',
      label: detailLabel('openPositions'),
      value: formatWholeNumber(summary.counts.openPositions, separators),
    },
    {
      id: 'closed_positions',
      label: detailLabel('closedPositions'),
      value: formatWholeNumber(summary.counts.closedPositions, separators),
    },
    {
      id: 'open_long_units',
      label: detailLabel('openLongUnits'),
      value: formatQuantity(summary.counts.openLongUnits ?? 0, separators),
    },
    {
      id: 'open_short_units',
      label: detailLabel('openShortUnits'),
      value: formatQuantity(summary.counts.openShortUnits ?? 0, separators),
    },
  ];

  if (summary.execution.ticksProcessed > 0) {
    items.push({
      id: 'ticks_processed',
      label: detailLabel('ticksProcessed'),
      value: formatWholeNumber(summary.execution.ticksProcessed, separators),
    });
  }

  if (displayedMarginRatio != null) {
    items.push({
      id: 'margin_ratio',
      label: t('common:labels.marginRatio'),
      value: formatRatio(displayedMarginRatio, separators),
    });
  }

  if (summary.execution.currentAtr != null) {
    items.push({
      id: 'current_atr',
      label: t('common:labels.currentAtr'),
      value: formatDecimal(summary.execution.currentAtr, separators),
    });
  }

  items.push(...buildMetricItems(latestMetrics, summary, t, separators));
  return items.filter((item) => !hiddenIds?.has(item.id));
}

function buildStatusReasonItems(
  summary: TaskSummary,
  detailLabel: (key: string) => string
): ExecutionStatusItem[] {
  const statusReason =
    summary.task.statusReasonMessage || summary.task.stopReason;
  if (!statusReason) return [];

  const status = String(summary.task.status || '').toLowerCase();
  const shouldDisplay =
    Boolean(summary.task.statusReasonMessage) ||
    [
      'failed',
      'stopped',
      'completed',
      'paused',
      'stopping',
      'draining',
    ].includes(status);
  if (!shouldDisplay) return [];

  return [
    {
      id: 'status_reason',
      label: detailLabel('stopReason'),
      value: statusReason,
      color: status === 'failed' ? 'error.main' : undefined,
    },
  ];
}

function buildCurrentBalanceItems(
  summary: TaskSummary,
  pnlCurrency: string,
  detailLabel: (key: string) => string,
  separators: NumberFormatSeparators,
  tooltip: string
): ExecutionStatusItem[] {
  if (summary.execution.currentBalance == null) return [];

  const accountMoney = summary.execution.currentBalanceMoney;
  const displayMoney = summary.execution.currentBalanceDisplayMoney;
  const accountCurrency =
    accountMoney?.currency ||
    summary.execution.currentBalanceCurrency ||
    summary.execution.accountCurrency ||
    pnlCurrency;
  const displayCurrency = summary.execution.displayCurrency;

  const value = displayMoney
    ? formatMoneyPayload(displayMoney, {}, separators)
    : displayCurrency && summary.execution.currentBalanceDisplay != null
      ? formatCurrency(
          summary.execution.currentBalanceDisplay,
          displayCurrency,
          false,
          separators
        )
      : accountMoney
        ? formatMoneyPayload(accountMoney, {}, separators)
        : formatCurrency(
            summary.execution.currentBalance,
            accountCurrency,
            false,
            separators
          );

  return [
    {
      id: 'current_balance',
      label: detailLabel('currentBalance'),
      value,
      tooltip,
    },
  ];
}

function buildMetricItems(
  latestMetrics: MetricPoint | null,
  summary: TaskSummary,
  t: ReturnType<typeof useTranslation>['t'],
  separators: NumberFormatSeparators
): ExecutionStatusItem[] {
  return METRIC_KEYS.flatMap(({ key, format }) => {
    const value = metricValueForKey(key, latestMetrics, summary);
    if (value == null) return [];

    const color =
      key === 'losing_trades'
        ? 'error.main'
        : key === 'winning_trades'
          ? 'success.main'
          : undefined;

    return [
      {
        id: key,
        label: t(`common:metrics.${key}`, {
          defaultValue: key.replace(/_/g, ' '),
        }),
        value:
          format === 'pct'
            ? formatPercent(value, separators)
            : format === 'rate'
              ? formatRate(value, separators)
              : formatWholeNumber(value, separators),
        color,
      },
    ];
  });
}

function metricValueForKey(
  key: string,
  latestMetrics: MetricPoint | null,
  summary: TaskSummary
): number | null {
  const winningTrades = summary.counts.winningTrades;
  const losingTrades = summary.counts.losingTrades;

  if (key === 'winning_trades') return winningTrades;
  if (key === 'losing_trades') return losingTrades;
  if (key === 'win_rate') {
    const decidedTrades = winningTrades + losingTrades;
    return decidedTrades > 0 ? (winningTrades / decidedTrades) * 100 : 0;
  }

  if (!latestMetrics) return null;
  const raw = latestMetrics.metrics[key];
  if (raw == null || raw === '') return null;
  const value = Number(raw);
  return Number.isFinite(value) ? value : null;
}

function formatRate(value: number, separators: NumberFormatSeparators): string {
  return `${formatAppNumber(
    value,
    {
      minimumFractionDigits: 1,
      maximumFractionDigits: 1,
    },
    separators
  )}/s`;
}

function snapshotCardToItem(
  card: StrategySnapshotCard,
  accountCurrency: string,
  pnlCurrency: string,
  t: ReturnType<typeof useTranslation>['t'],
  separators: NumberFormatSeparators
): ExecutionStatusItem {
  const fallbackLabel = card.id.replace(/_/g, ' ');
  const labelKey = normalizeStrategyLabelKey(card.label_key);
  const label = labelKey
    ? t(`strategy:${labelKey}`, { defaultValue: fallbackLabel })
    : fallbackLabel;

  return {
    id: `snapshot_${card.id}`,
    label,
    value: formatSnapshotValue(
      card.id,
      card.value,
      accountCurrency,
      pnlCurrency,
      t,
      separators
    ),
  };
}

function normalizeStrategyLabelKey(labelKey?: string | null): string | null {
  if (!labelKey) return null;
  return labelKey.startsWith('strategy.')
    ? labelKey.slice('strategy.'.length)
    : labelKey;
}

function formatSnapshotValue(
  id: string,
  value: unknown,
  accountCurrency: string,
  pnlCurrency: string,
  t: ReturnType<typeof useTranslation>['t'],
  separators: NumberFormatSeparators
): string {
  if (value == null || value === '') return '-';

  if (typeof value === 'boolean') {
    return value ? t('common:labels.yes') : t('common:labels.no');
  }

  if (Array.isArray(value)) {
    return value.length === 0 ? '-' : value.map(String).join(', ');
  }

  if (typeof value === 'object') {
    return JSON.stringify(value);
  }

  const numericValue =
    typeof value === 'number' ? value : Number(String(value).trim());
  if (Number.isFinite(numericValue)) {
    if (isPercentKey(id)) return formatRatio(numericValue, separators);
    if (isCurrencyKey(id)) {
      return formatCurrency(
        numericValue,
        id.includes('pnl') ? pnlCurrency : accountCurrency,
        false,
        separators
      );
    }
    if (isCountKey(id)) return formatWholeNumber(numericValue, separators);
    return formatDecimal(numericValue, separators);
  }

  const stringValue = String(value);
  return t(`strategy:snapshotValues.${id}.${stringValue}`, {
    defaultValue: stringValue,
  });
}

function formatCurrency(
  value: number,
  currencyCode: string | null | undefined,
  signed = false,
  separators?: NumberFormatSeparators
): string {
  return formatMoneyAmount(
    value,
    currencyCode,
    {
      signed,
    },
    separators
  );
}

function formatPnlValue(
  displayMoney: { amount: string; currency: string } | null,
  fallbackValue: number,
  fallbackCurrency: string | null | undefined,
  signed = false,
  separators?: NumberFormatSeparators
): string {
  if (displayMoney) {
    return formatMoneyPayload(
      displayMoney,
      {
        signed,
      },
      separators
    );
  }
  return formatCurrency(fallbackValue, fallbackCurrency, signed, separators);
}

function formatWholeNumber(
  value: number,
  separators?: NumberFormatSeparators
): string {
  return formatAppNumber(
    value,
    {
      maximumFractionDigits: 0,
    },
    separators
  );
}

function formatQuantity(
  value: number,
  separators?: NumberFormatSeparators
): string {
  return formatAppNumber(
    value,
    {
      maximumFractionDigits: 2,
    },
    separators
  );
}

function formatDecimal(
  value: number,
  separators?: NumberFormatSeparators
): string {
  return formatAppNumber(
    value,
    {
      maximumFractionDigits: 2,
    },
    separators
  );
}

function formatPercent(
  value: number,
  separators?: NumberFormatSeparators
): string {
  return formatAppPercent(value, 2, false, separators);
}

function formatRatio(
  value: number,
  separators?: NumberFormatSeparators
): string {
  const percentValue = Math.abs(value) <= 1 ? value * 100 : value;
  return formatPercent(percentValue, separators);
}

function isPercentKey(id: string): boolean {
  return (
    id.endsWith('_rate') ||
    id.endsWith('_ratio') ||
    id.endsWith('_pct') ||
    id.endsWith('_return') ||
    id.includes('drawdown')
  );
}

function isCurrencyKey(id: string): boolean {
  return (
    id.includes('balance') ||
    id.includes('nav') ||
    id.includes('pnl') ||
    id.includes('profit') ||
    id.includes('loss')
  );
}

function isCountKey(id: string): boolean {
  return (
    id.endsWith('_count') ||
    id.endsWith('_cycles') ||
    id.endsWith('_entries') ||
    id.includes('trades') ||
    id.includes('positions') ||
    id.includes('ticks')
  );
}
