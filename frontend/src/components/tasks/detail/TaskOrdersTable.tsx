/**
 * TaskOrdersTable Component
 *
 * Displays orders for a task with pagination and filtering.
 */

import React, { useState, useCallback } from 'react';
import { useTranslation } from 'react-i18next';
import {
  Box,
  Chip,
  Typography,
  Alert,
  TablePagination,
  IconButton,
  InputAdornment,
  TextField,
  Tooltip,
} from '@mui/material';
import {
  Settings as SettingsIcon,
  Search as SearchIcon,
  Clear as ClearIcon,
} from '@mui/icons-material';
import DataTable, { type Column } from '../../common/DataTable';
import { TableSelectionToolbar } from '../../common/TableSelectionToolbar';
import { useTableRowSelection } from '../../../hooks/useTableRowSelection';
import { useTaskOrders, type TaskOrder } from '../../../hooks/useTaskOrders';
import type { TaskType } from '../../../types/common';
import { ColumnConfigDialog } from '../../common/ColumnConfigDialog';
import {
  useColumnConfig,
  columnsToDefaults,
  applyColumnConfig,
} from '../../../hooks/useColumnConfig';
import { buildCopyHandler } from '../../../utils/tableCopyUtils';
import { formatAppNumber } from '../../../utils/numberFormat';
import { useDateTimeFormatter } from '../../../hooks/useDateTimeFormatter';
import { DateRangeFilter } from '../../common/DateRangeFilter';
import { TableFilterBar } from '../../common/TableFilterBar';
import {
  tableFilterDateRangeSx,
  tableFilterFieldSx,
} from '../../common/tableFilterLayout';

interface TaskOrdersTableProps {
  taskId: string | number;
  taskType: TaskType;
  executionRunId?: string;
  enableRealTimeUpdates?: boolean;
}

type SortOrder = 'asc' | 'desc';

const toOrdering = (field: string, order: SortOrder): string =>
  order === 'desc' ? `-${field}` : field;

export const TaskOrdersTable: React.FC<TaskOrdersTableProps> = ({
  taskId,
  taskType,
  executionRunId,
  enableRealTimeUpdates = false,
}) => {
  const { t } = useTranslation('common');
  const { formatDateTime } = useDateTimeFormatter({
    includeSeconds: true,
    includeTimezone: true,
  });
  const [page, setPage] = useState(0);
  const [rowsPerPage, setRowsPerPage] = useState(50);
  const [sortField, setSortField] = useState('submitted_at');
  const [sortOrder, setSortOrder] = useState<SortOrder>('desc');
  const [isReloading, setIsReloading] = useState(false);
  const selection = useTableRowSelection();

  // --- Date range filter ---
  const [dateFrom, setDateFrom] = useState('');
  const [dateTo, setDateTo] = useState('');

  // --- Order ID filter (prefix match on UUID — accept 4+ hex chars/dashes) ---
  const [orderIdFilter, setOrderIdFilter] = useState('');
  const hasOrderIdFilter = orderIdFilter.trim().length > 0;
  const ORDER_ID_PREFIX_PATTERN = /^[0-9a-f-]{4,}$/i;
  const isOrderIdFilterValid =
    !hasOrderIdFilter || ORDER_ID_PREFIX_PATTERN.test(orderIdFilter.trim());
  const effectiveOrderId =
    hasOrderIdFilter && isOrderIdFilterValid ? orderIdFilter.trim() : '';

  const { orders, totalCount, isLoading, error, refresh } = useTaskOrders({
    taskId,
    taskType,
    executionRunId,
    page: page + 1,
    pageSize: rowsPerPage,
    ordering: toOrdering(sortField, sortOrder),
    orderId: effectiveOrderId || undefined,
    timestampFrom: dateFrom ? new Date(dateFrom).toISOString() : undefined,
    timestampTo: dateTo ? new Date(dateTo).toISOString() : undefined,
    enableRealTimeUpdates,
  });

  const getRowId = useCallback((row: TaskOrder) => String(row.id), []);
  const pageRowIds = orders.map((r) => String(r.id));

  const handleToggleAll = useCallback(() => {
    if (selection.isAllPageSelected(pageRowIds)) {
      selection.deselectAllOnPage(pageRowIds);
    } else {
      selection.selectAllOnPage(pageRowIds);
    }
  }, [pageRowIds, selection]);

  const handleReload = useCallback(async () => {
    setIsReloading(true);
    await refresh();
    setIsReloading(false);
  }, [refresh]);

  const handleSortChange = useCallback((field: string, order: SortOrder) => {
    setSortField(field);
    setSortOrder(order);
    setPage(0);
  }, []);

  const formatTimestamp = useCallback(
    (timestamp: string): string => formatDateTime(timestamp),
    [formatDateTime]
  );

  const formatPrice = useCallback(
    (value: string | number | null | undefined, digits = 5): string => {
      if (value == null || value === '') return '-';
      const numericValue =
        typeof value === 'string' ? parseFloat(value) : Number(value);
      if (!Number.isFinite(numericValue)) return '-';
      return formatAppNumber(numericValue, {
        minimumFractionDigits: digits,
        maximumFractionDigits: digits,
        useGrouping: false,
      });
    },
    []
  );

  const formatMilliseconds = useCallback(
    (seconds: string | number | null | undefined): string => {
      if (seconds == null || seconds === '') return '-';
      const numericValue =
        typeof seconds === 'string' ? parseFloat(seconds) : Number(seconds);
      if (!Number.isFinite(numericValue)) return '-';
      return `${formatAppNumber(numericValue * 1000, {
        minimumFractionDigits: 0,
        maximumFractionDigits: 1,
      })} ms`;
    },
    []
  );

  const statusColor = (
    status: string
  ): 'success' | 'error' | 'warning' | 'default' | 'info' => {
    switch (status.toLowerCase()) {
      case 'filled':
        return 'success';
      case 'cancelled':
        return 'warning';
      case 'rejected':
        return 'error';
      case 'pending':
        return 'info';
      case 'triggered':
        return 'default';
      default:
        return 'default';
    }
  };

  const columns: Column<TaskOrder>[] = [
    {
      id: 'id',
      label: t('tables.orders.orderId'),
      width: 120,
      minWidth: 80,
      render: (row) => (row.id ? String(row.id).slice(0, 8) : '-'),
    },
    {
      id: 'submitted_at',
      label: t('tables.orders.processedAt'),
      width: 220,
      minWidth: 220,
      render: (row) =>
        row.submitted_at ? formatTimestamp(row.submitted_at) : '-',
    },
    {
      id: 'instrument',
      label: t('tables.orders.instrument'),
      width: 100,
      minWidth: 85,
    },
    {
      id: 'order_type',
      label: t('tables.orders.type'),
      width: 128,
      minWidth: 128,
      render: (row) => (
        <Chip
          label={row.order_type.toUpperCase()}
          variant="outlined"
          size="small"
        />
      ),
    },
    {
      id: 'replayed_at',
      label: 'Replay',
      width: 105,
      minWidth: 90,
      render: (row) =>
        row.replayed_at ? (
          <Tooltip title={`Replayed at ${formatTimestamp(row.replayed_at)}`}>
            <Chip
              label="REPLAY"
              size="small"
              color="warning"
              variant="filled"
            />
          </Tooltip>
        ) : (
          '-'
        ),
    },
    {
      id: 'direction',
      label: t('tables.orders.direction'),
      width: 120,
      minWidth: 120,
      render: (row) => {
        if (!row.direction)
          return (
            <Typography variant="body2" color="text.secondary">
              CLOSE
            </Typography>
          );
        const dir = row.direction.toLowerCase();
        return (
          <Chip
            label={
              dir === 'long'
                ? 'LONG'
                : dir === 'short'
                  ? 'SHORT'
                  : row.direction.toUpperCase()
            }
            color={dir === 'long' ? 'success' : 'error'}
            size="small"
          />
        );
      },
    },
    {
      id: 'units',
      label: t('tables.orders.units'),
      width: 70,
      minWidth: 55,
      align: 'right',
      render: (row) => formatAppNumber(Math.abs(row.units)),
    },
    {
      id: 'status',
      label: t('tables.orders.status'),
      width: 120,
      minWidth: 120,
      render: (row) => (
        <Chip
          label={row.status.toUpperCase()}
          color={statusColor(row.status)}
          size="small"
        />
      ),
    },
    {
      id: 'broker_order_id',
      label: 'Broker Order',
      width: 180,
      minWidth: 140,
      render: (row) =>
        row.broker_order_id ? (
          <Typography variant="body2" fontFamily="monospace">
            {row.broker_order_id}
          </Typography>
        ) : (
          '-'
        ),
    },
    {
      id: 'oanda_trade_id',
      label: 'OANDA Trade',
      width: 150,
      minWidth: 120,
      render: (row) =>
        row.oanda_trade_id ? (
          <Typography variant="body2" fontFamily="monospace">
            {row.oanda_trade_id}
          </Typography>
        ) : (
          '-'
        ),
    },
    {
      id: 'requested_price',
      label: t('tables.orders.requestedPrice'),
      width: 120,
      minWidth: 120,
      align: 'right',
      render: (row) => formatPrice(row.requested_price, 5),
    },
    {
      id: 'fill_price',
      label: t('tables.orders.fillPrice'),
      width: 120,
      minWidth: 120,
      align: 'right',
      render: (row) => formatPrice(row.fill_price, 5),
    },
    {
      id: 'filled_at',
      label: t('tables.orders.filledAt'),
      width: 220,
      minWidth: 220,
      render: (row) => (row.filled_at ? formatTimestamp(row.filled_at) : '-'),
    },
    {
      id: 'oanda_response_seconds',
      label: t('tables.orders.oandaResponseMs'),
      width: 140,
      minWidth: 125,
      align: 'right',
      render: (row) => formatMilliseconds(row.oanda_response_seconds),
    },
    {
      id: 'stop_loss',
      label: t('tables.orders.stopLoss'),
      width: 95,
      minWidth: 80,
      align: 'right',
      render: (row) => formatPrice(row.stop_loss, 5),
    },
    {
      id: 'error_message',
      label: t('tables.orders.error'),
      minWidth: 200,
      render: (row) =>
        row.error_message ? (
          <Typography
            variant="body2"
            color="error.main"
            title={row.error_message}
            sx={{ whiteSpace: 'normal', wordBreak: 'break-word' }}
          >
            {row.error_message}
          </Typography>
        ) : (
          '-'
        ),
    },
  ];

  // Column config
  const [colConfigOpen, setColConfigOpen] = useState(false);
  const defaultColItems = columnsToDefaults(columns).map((column) =>
    ['replayed_at', 'broker_order_id', 'oanda_trade_id'].includes(column.id)
      ? { ...column, visible: false }
      : column
  );
  const {
    columns: colConfig,
    updateColumns,
    resetToDefaults,
  } = useColumnConfig('task_orders', defaultColItems);
  const visibleColumns = applyColumnConfig(columns, colConfig);

  const handleCopy = useCallback(() => {
    const orderMap = new Map(orders.map((o) => [String(o.id), o]));
    const extractors: Record<string, (r: TaskOrder) => string> = {
      id: (r) => (r.id ? String(r.id).slice(0, 8) : '-'),
      submitted_at: (r) =>
        r.submitted_at ? formatTimestamp(r.submitted_at) : '-',
      instrument: (r) => r.instrument ?? '-',
      order_type: (r) => r.order_type ?? '-',
      direction: (r) => r.direction ?? '-',
      units: (r) => formatAppNumber(Math.abs(r.units)),
      status: (r) => r.status ?? '-',
      replayed_at: (r) =>
        r.replayed_at ? formatTimestamp(r.replayed_at) : '-',
      broker_order_id: (r) => r.broker_order_id ?? '-',
      oanda_trade_id: (r) => r.oanda_trade_id ?? '-',
      requested_price: (r) => formatPrice(r.requested_price, 5),
      fill_price: (r) => formatPrice(r.fill_price, 5),
      filled_at: (r) => (r.filled_at ? formatTimestamp(r.filled_at) : '-'),
      oanda_response_seconds: (r) =>
        formatMilliseconds(r.oanda_response_seconds),
      stop_loss: (r) => formatPrice(r.stop_loss, 5),
      error_message: (r) => r.error_message || '-',
    };
    const { headers, formatRow } = buildCopyHandler(
      visibleColumns,
      extractors,
      orderMap
    );
    selection.copySelectedRows(headers, formatRow, pageRowIds);
  }, [
    formatPrice,
    formatMilliseconds,
    formatTimestamp,
    orders,
    pageRowIds,
    selection,
    visibleColumns,
  ]);

  if (error) {
    return (
      <Box sx={{ p: 3 }}>
        <Alert severity="error">{error.message}</Alert>
      </Box>
    );
  }

  return (
    <Box sx={{ p: 3 }}>
      <Box
        sx={{
          mb: 2,
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'center',
        }}
      >
        <Typography variant="h6">
          {t('tables.orders.title')} ({totalCount})
        </Typography>
        <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
          <Tooltip title={t('common:columnConfig.configureColumns')}>
            <IconButton
              size="small"
              onClick={() => setColConfigOpen(true)}
              aria-label={t('common:columnConfig.configureColumns')}
            >
              <SettingsIcon fontSize="small" />
            </IconButton>
          </Tooltip>
          <TableSelectionToolbar
            selectedCount={selection.selectedRowIds.size}
            onCopy={handleCopy}
            onSelectAll={() => selection.selectAllOnPage(pageRowIds)}
            onReset={selection.resetSelection}
            onReload={handleReload}
            isReloading={isReloading}
          />
        </Box>
      </Box>
      <TableFilterBar>
        <TextField
          size="small"
          placeholder={t('tables.orders.orderIdFilter')}
          value={orderIdFilter}
          onChange={(e) => {
            setOrderIdFilter(e.target.value);
            setPage(0);
          }}
          error={hasOrderIdFilter && !isOrderIdFilterValid}
          helperText={
            hasOrderIdFilter && !isOrderIdFilterValid
              ? t('tables.orders.invalidOrderId')
              : undefined
          }
          sx={tableFilterFieldSx}
          slotProps={{
            input: {
              startAdornment: (
                <InputAdornment position="start">
                  <SearchIcon fontSize="small" />
                </InputAdornment>
              ),
              endAdornment: orderIdFilter ? (
                <InputAdornment position="end">
                  <IconButton
                    size="small"
                    onClick={() => setOrderIdFilter('')}
                    edge="end"
                  >
                    <ClearIcon fontSize="small" />
                  </IconButton>
                </InputAdornment>
              ) : null,
            },
          }}
        />
        <DateRangeFilter
          from={dateFrom}
          to={dateTo}
          onFromChange={(v) => {
            setDateFrom(v);
            setPage(0);
          }}
          onToChange={(v) => {
            setDateTo(v);
            setPage(0);
          }}
          sx={tableFilterDateRangeSx}
        />
      </TableFilterBar>

      <DataTable
        columns={visibleColumns}
        data={orders}
        isLoading={isLoading}
        emptyMessage={t('tables.orders.noOrders')}
        defaultRowsPerPage={rowsPerPage}
        rowsPerPageOptions={[rowsPerPage]}
        tableMaxHeight="none"
        hidePagination
        selectable
        getRowId={getRowId}
        selectedRowIds={selection.selectedRowIds}
        onToggleRow={selection.toggleRowSelection}
        allPageSelected={selection.isAllPageSelected(pageRowIds)}
        indeterminate={selection.isIndeterminate(pageRowIds)}
        onToggleAll={handleToggleAll}
        sortMode="server"
        orderBy={sortField}
        order={sortOrder}
        onSortChange={handleSortChange}
        fillEmptyRows
      />

      <TablePagination
        component="div"
        count={totalCount}
        page={page}
        onPageChange={(_e, newPage) => setPage(newPage)}
        rowsPerPage={rowsPerPage}
        onRowsPerPageChange={(e) => {
          setRowsPerPage(parseInt(e.target.value, 10));
          setPage(0);
        }}
        rowsPerPageOptions={[10, 25, 50, 100, 200, 500, 1000]}
      />

      <ColumnConfigDialog
        open={colConfigOpen}
        columns={colConfig}
        onClose={() => setColConfigOpen(false)}
        onSave={updateColumns}
        onReset={resetToDefaults}
      />
    </Box>
  );
};

export default TaskOrdersTable;
