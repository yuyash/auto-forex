import React, { useCallback, useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import {
  Alert,
  Box,
  Checkbox,
  Chip,
  FormControl,
  IconButton,
  InputLabel,
  MenuItem,
  Paper,
  Select,
  TablePagination,
  TextField,
  Tooltip,
  Typography,
  type SelectChangeEvent,
} from '@mui/material';
import { useMediaQuery, useTheme } from '@mui/material';
import FilterListOffIcon from '@mui/icons-material/FilterListOff';
import { Settings as SettingsIcon } from '@mui/icons-material';
import DataTable, { type Column } from '../../common/DataTable';
import { TableSelectionToolbar } from '../../common/TableSelectionToolbar';
import { DateRangeFilter } from '../../common/DateRangeFilter';
import { TableFilterBar } from '../../common/TableFilterBar';
import { tableFilterDateRangeSx } from '../../common/tableFilterLayout';
import { ColumnConfigDialog } from '../../common/ColumnConfigDialog';
import {
  applyColumnConfig,
  columnsToDefaults,
  useColumnConfig,
} from '../../../hooks/useColumnConfig';
import { useDateTimeFormatter } from '../../../hooks/useDateTimeFormatter';
import { useTableRowSelection } from '../../../hooks/useTableRowSelection';
import {
  useTaskMarketEvents,
  type TaskMarketEvent,
} from '../../../hooks/useTaskMarketEvents';
import type { TaskType } from '../../../types/common';
import { buildCopyHandler } from '../../../utils/tableCopyUtils';

interface TaskMarketEventsTableProps {
  taskId: string;
  taskType: TaskType;
  executionRunId?: string;
  enableRealTimeUpdates?: boolean;
}

type SortOrder = 'asc' | 'desc';

const toOrdering = (field: string, order: SortOrder): string =>
  order === 'desc' ? `-${field}` : field;

function formatDetails(details?: Record<string, unknown>): string {
  if (!details || Object.keys(details).length === 0) return '-';
  return JSON.stringify(details);
}

export const TaskMarketEventsTable: React.FC<TaskMarketEventsTableProps> = ({
  taskId,
  taskType,
  executionRunId,
  enableRealTimeUpdates = false,
}) => {
  const { t } = useTranslation('common');
  const theme = useTheme();
  const isMobile = useMediaQuery(theme.breakpoints.down('md'));
  const { formatDateTime } = useDateTimeFormatter({
    includeSeconds: true,
    includeMilliseconds: true,
    includeTimezone: true,
  });
  const [severityFilter, setSeverityFilter] = useState<string[]>([]);
  const [categoryFilter, setCategoryFilter] = useState<string[]>([]);
  const [eventTypeFilter, setEventTypeFilter] = useState('');
  const [instrumentFilter, setInstrumentFilter] = useState('');
  const [messageFilter, setMessageFilter] = useState('');
  const [createdFrom, setCreatedFrom] = useState('');
  const [createdTo, setCreatedTo] = useState('');
  const [page, setPage] = useState(0);
  const [rowsPerPage, setRowsPerPage] = useState(100);
  const [sortField, setSortField] = useState('created_at');
  const [sortOrder, setSortOrder] = useState<SortOrder>('desc');
  const [isReloading, setIsReloading] = useState(false);
  const [colConfigOpen, setColConfigOpen] = useState(false);

  const { events, totalCount, isLoading, error, refresh } = useTaskMarketEvents(
    {
      taskId,
      taskType,
      executionRunId,
      severity: severityFilter.length > 0 ? severityFilter : undefined,
      category: categoryFilter.length > 0 ? categoryFilter : undefined,
      eventType: eventTypeFilter.trim() || undefined,
      instrument: instrumentFilter.trim() || undefined,
      message: messageFilter.trim() || undefined,
      createdFrom: createdFrom
        ? new Date(createdFrom).toISOString()
        : undefined,
      createdTo: createdTo ? new Date(createdTo).toISOString() : undefined,
      ordering: toOrdering(sortField, sortOrder),
      page: page + 1,
      pageSize: rowsPerPage,
      enableRealTimeUpdates,
    }
  );

  const selection = useTableRowSelection();
  const getRowId = useCallback((row: TaskMarketEvent) => String(row.id), []);
  const pageRowIds = useMemo(
    () => events.map((row) => String(row.id)),
    [events]
  );

  const formatCreatedAt = useCallback(
    (createdAt: string): string => formatDateTime(createdAt),
    [formatDateTime]
  );

  const getSeverityColor = (
    severity: string
  ): 'default' | 'success' | 'error' | 'warning' | 'info' => {
    switch (severity.toLowerCase()) {
      case 'error':
      case 'critical':
        return 'error';
      case 'warning':
        return 'warning';
      case 'info':
        return 'info';
      case 'success':
        return 'success';
      default:
        return 'default';
    }
  };

  const handleSortChange = useCallback((field: string, order: SortOrder) => {
    setSortField(field);
    setSortOrder(order);
    setPage(0);
  }, []);

  const handleReload = useCallback(async () => {
    setIsReloading(true);
    await refresh();
    setIsReloading(false);
  }, [refresh]);

  const handleToggleAll = useCallback(() => {
    if (selection.isAllPageSelected(pageRowIds)) {
      selection.deselectAllOnPage(pageRowIds);
    } else {
      selection.selectAllOnPage(pageRowIds);
    }
  }, [pageRowIds, selection]);

  const resetFilters = useCallback(() => {
    setSeverityFilter([]);
    setCategoryFilter([]);
    setEventTypeFilter('');
    setInstrumentFilter('');
    setMessageFilter('');
    setCreatedFrom('');
    setCreatedTo('');
    setPage(0);
  }, []);

  const columns: Column<TaskMarketEvent>[] = [
    {
      id: 'created_at',
      label: t('tables.marketEvents.createdAt'),
      width: 280,
      minWidth: 240,
      render: (row) => formatCreatedAt(row.created_at),
    },
    {
      id: 'severity',
      label: t('tables.marketEvents.severity'),
      width: 130,
      minWidth: 100,
      render: (row) => (
        <Chip
          label={row.severity || '-'}
          color={getSeverityColor(row.severity || '')}
          size="small"
        />
      ),
    },
    {
      id: 'category',
      label: t('tables.marketEvents.category'),
      width: 140,
      minWidth: 110,
    },
    {
      id: 'event_type',
      label: t('tables.marketEvents.eventType'),
      width: 240,
      minWidth: 170,
    },
    {
      id: 'instrument',
      label: t('tables.marketEvents.instrument'),
      width: 140,
      minWidth: 110,
      render: (row) => row.instrument || '-',
    },
    {
      id: 'description',
      label: t('tables.marketEvents.description'),
      width: 520,
      minWidth: 280,
      render: (row) => (
        <Typography
          variant="body2"
          sx={{
            whiteSpace: 'pre-wrap',
            wordBreak: 'break-word',
            overflowWrap: 'anywhere',
          }}
        >
          {row.description || '-'}
        </Typography>
      ),
    },
    {
      id: 'details',
      label: t('tables.marketEvents.details'),
      width: 520,
      minWidth: 260,
      sortable: false,
      render: (row) => {
        const details = formatDetails(row.details);
        return (
          <Tooltip title={details === '-' ? '' : details} arrow>
            <Typography
              component="pre"
              variant="body2"
              sx={{
                m: 0,
                maxWidth: '100%',
                whiteSpace: 'pre-wrap',
                wordBreak: 'break-word',
                overflowWrap: 'anywhere',
                fontFamily: 'monospace',
              }}
            >
              {details}
            </Typography>
          </Tooltip>
        );
      },
    },
  ];

  const defaultColItems = columnsToDefaults(columns);
  const {
    columns: colConfig,
    updateColumns,
    resetToDefaults: resetColDefaults,
  } = useColumnConfig('task_market_events', defaultColItems);
  const visibleColumns = applyColumnConfig(columns, colConfig);

  const handleCopy = useCallback(() => {
    const eventMap = new Map(events.map((event) => [String(event.id), event]));
    const extractors: Record<string, (row: TaskMarketEvent) => string> = {
      created_at: (row) => formatCreatedAt(row.created_at),
      severity: (row) => row.severity || '-',
      category: (row) => row.category || '-',
      event_type: (row) => row.event_type || '-',
      instrument: (row) => row.instrument || '-',
      description: (row) => row.description || '-',
      details: (row) => formatDetails(row.details),
    };
    const { headers, formatRow } = buildCopyHandler(
      visibleColumns,
      extractors,
      eventMap
    );
    selection.copySelectedRows(headers, formatRow, pageRowIds);
  }, [events, formatCreatedAt, pageRowIds, selection, visibleColumns]);

  const renderMobileCell = useCallback(
    (column: Column<TaskMarketEvent>, row: TaskMarketEvent) => {
      if (column.render) return column.render(row);
      return String(row[column.id as keyof TaskMarketEvent] ?? '');
    },
    []
  );

  if (error) {
    return (
      <Box sx={{ p: 3 }}>
        <Alert severity="error">{error.message}</Alert>
      </Box>
    );
  }

  return (
    <Box sx={{ p: { xs: 1.5, sm: 3 } }}>
      <Box
        sx={{
          mb: 1,
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
        }}
      >
        <Typography variant="h6">{t('tables.marketEvents.title')}</Typography>
        <Box sx={{ display: 'flex', alignItems: 'center', gap: 0.5 }}>
          <Tooltip title={t('tables.marketEvents.resetFilters')}>
            <IconButton size="small" onClick={resetFilters}>
              <FilterListOffIcon fontSize="small" />
            </IconButton>
          </Tooltip>
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
        <FormControl
          sx={{ flex: { xs: '1 1 100%', sm: '0 1 200px' }, minWidth: 0 }}
          size="small"
        >
          <InputLabel>{t('tables.marketEvents.severityFilter')}</InputLabel>
          <Select<string[]>
            multiple
            value={severityFilter}
            label={t('tables.marketEvents.severityFilter')}
            onChange={(event: SelectChangeEvent<string[]>) => {
              const value = event.target.value;
              setSeverityFilter(
                typeof value === 'string' ? value.split(',') : value
              );
              setPage(0);
            }}
            renderValue={(selected) => (
              <Box sx={{ display: 'flex', flexWrap: 'wrap', gap: 0.5 }}>
                {selected.map((value) => (
                  <Chip
                    key={value}
                    label={value}
                    size="small"
                    color={getSeverityColor(value)}
                  />
                ))}
              </Box>
            )}
          >
            <MenuItem value="info">Info</MenuItem>
            <MenuItem value="warning">Warning</MenuItem>
            <MenuItem value="error">Error</MenuItem>
            <MenuItem value="critical">Critical</MenuItem>
          </Select>
        </FormControl>
        <FormControl
          sx={{ flex: { xs: '1 1 100%', sm: '0 1 220px' }, minWidth: 0 }}
          size="small"
        >
          <InputLabel>{t('tables.marketEvents.categoryFilter')}</InputLabel>
          <Select<string[]>
            multiple
            value={categoryFilter}
            label={t('tables.marketEvents.categoryFilter')}
            onChange={(event: SelectChangeEvent<string[]>) => {
              const value = event.target.value;
              setCategoryFilter(
                typeof value === 'string' ? value.split(',') : value
              );
              setPage(0);
            }}
            renderValue={(selected) => (
              <Box sx={{ display: 'flex', flexWrap: 'wrap', gap: 0.5 }}>
                {selected.map((value) => (
                  <Chip key={value} label={value} size="small" />
                ))}
              </Box>
            )}
          >
            <MenuItem value="market">Market</MenuItem>
            <MenuItem value="trading">Trading</MenuItem>
            <MenuItem value="security">Security</MenuItem>
          </Select>
        </FormControl>
        <DateRangeFilter
          from={createdFrom}
          to={createdTo}
          onFromChange={(value) => {
            setCreatedFrom(value);
            setPage(0);
          }}
          onToChange={(value) => {
            setCreatedTo(value);
            setPage(0);
          }}
          fromLabel={t('tables.marketEvents.createdFrom')}
          toLabel={t('tables.marketEvents.createdTo')}
          sx={tableFilterDateRangeSx}
        />
        <TextField
          size="small"
          label={t('tables.marketEvents.eventTypeFilter')}
          value={eventTypeFilter}
          onChange={(event) => {
            setEventTypeFilter(event.target.value);
            setPage(0);
          }}
          sx={{ flex: { xs: '1 1 100%', md: '0 1 260px' }, minWidth: 0 }}
        />
        <TextField
          size="small"
          label={t('tables.marketEvents.instrumentFilter')}
          value={instrumentFilter}
          onChange={(event) => {
            setInstrumentFilter(event.target.value);
            setPage(0);
          }}
          sx={{ flex: { xs: '1 1 100%', sm: '0 1 180px' }, minWidth: 0 }}
        />
        <TextField
          size="small"
          label={t('tables.marketEvents.messageFilter')}
          placeholder={t('tables.marketEvents.messageFilterPlaceholder')}
          value={messageFilter}
          onChange={(event) => {
            setMessageFilter(event.target.value);
            setPage(0);
          }}
          sx={{ flex: { xs: '1 1 100%', md: '1 1 320px' }, minWidth: 0 }}
        />
      </TableFilterBar>

      {isMobile ? (
        <Box sx={{ display: 'grid', gap: 1.5 }}>
          {isLoading && events.length === 0 ? (
            <Paper variant="outlined" sx={{ p: 2 }}>
              <Typography color="text.secondary">
                {t('common.loading')}
              </Typography>
            </Paper>
          ) : events.length === 0 ? (
            <Paper variant="outlined" sx={{ p: 2 }}>
              <Typography color="text.secondary">
                {t('tables.marketEvents.noEvents')}
              </Typography>
            </Paper>
          ) : (
            events.map((row) => {
              const rowId = getRowId(row);
              const isSelected = selection.selectedRowIds.has(rowId);
              return (
                <Paper key={rowId} variant="outlined" sx={{ p: 1.5 }}>
                  <Box
                    sx={{
                      display: 'flex',
                      alignItems: 'flex-start',
                      justifyContent: 'space-between',
                      gap: 1,
                      mb: 1,
                    }}
                  >
                    <Box sx={{ minWidth: 0 }}>
                      <Typography variant="body2" fontWeight={600}>
                        {formatCreatedAt(row.created_at)}
                      </Typography>
                      <Box
                        sx={{
                          mt: 0.75,
                          display: 'flex',
                          gap: 0.75,
                          flexWrap: 'wrap',
                          alignItems: 'center',
                        }}
                      >
                        <Chip
                          label={row.severity || '-'}
                          color={getSeverityColor(row.severity || '')}
                          size="small"
                        />
                        <Chip
                          label={row.event_type || '-'}
                          size="small"
                          variant="outlined"
                        />
                      </Box>
                    </Box>
                    <Checkbox
                      checked={isSelected}
                      onChange={() => selection.toggleRowSelection(rowId)}
                    />
                  </Box>
                  <Box sx={{ display: 'grid', gap: 1 }}>
                    {visibleColumns
                      .filter(
                        (column) =>
                          String(column.id) !== 'created_at' &&
                          String(column.id) !== 'severity' &&
                          String(column.id) !== 'event_type'
                      )
                      .map((column) => (
                        <Box key={String(column.id)}>
                          <Typography
                            variant="caption"
                            color="text.secondary"
                            sx={{ display: 'block', mb: 0.25 }}
                          >
                            {column.label}
                          </Typography>
                          <Box
                            sx={{
                              whiteSpace: 'pre-wrap',
                              wordBreak: 'break-word',
                              overflowWrap: 'anywhere',
                              fontFamily:
                                String(column.id) === 'details'
                                  ? 'monospace'
                                  : 'inherit',
                            }}
                          >
                            {renderMobileCell(column, row)}
                          </Box>
                        </Box>
                      ))}
                  </Box>
                </Paper>
              );
            })
          )}
        </Box>
      ) : (
        <DataTable
          columns={visibleColumns}
          data={events}
          isLoading={isLoading}
          emptyMessage={t('tables.marketEvents.noEvents')}
          defaultRowsPerPage={rowsPerPage}
          rowsPerPageOptions={[rowsPerPage]}
          storageKey="task-market-events"
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
      )}

      <TablePagination
        component="div"
        count={totalCount}
        page={page}
        onPageChange={(_event, newPage) => setPage(newPage)}
        rowsPerPage={rowsPerPage}
        onRowsPerPageChange={(event) => {
          setRowsPerPage(parseInt(event.target.value, 10));
          setPage(0);
        }}
        rowsPerPageOptions={[25, 50, 100, 200, 500, 1000]}
      />

      <ColumnConfigDialog
        open={colConfigOpen}
        columns={colConfig}
        onClose={() => setColConfigOpen(false)}
        onSave={updateColumns}
        onReset={resetColDefaults}
      />
    </Box>
  );
};

export default TaskMarketEventsTable;
