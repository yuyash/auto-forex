import { Box, Typography, Paper } from '@mui/material';
import { useParams } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import TradingTaskForm from '../components/trading/TradingTaskForm';
import TradingTaskUpdateForm from '../components/trading/TradingTaskUpdateForm';
import { useTradingTask } from '../hooks/useTradingTasks';
import {
  LoadingSpinner,
  Breadcrumbs,
  PageContainer,
} from '../components/common';

export default function TradingTaskFormPage() {
  const { t } = useTranslation('trading');
  const { id } = useParams<{ id: string }>();
  const taskId = id || undefined;

  const { data: task, isLoading } = useTradingTask(taskId, {
    enabled: !!taskId,
  });

  const isEditMode = !!taskId;

  if (isEditMode && (isLoading || !task)) {
    return (
      <PageContainer>
        <Box
          sx={{
            display: 'flex',
            justifyContent: 'center',
            alignItems: 'center',
            minHeight: '60vh',
          }}
        >
          <LoadingSpinner />
        </Box>
      </PageContainer>
    );
  }

  return (
    <PageContainer>
      <Box sx={{ py: 4 }}>
        <Breadcrumbs />

        <Typography variant="h4" component="h1" gutterBottom>
          {isEditMode ? t('pages.editTitle') : t('pages.createTitle')}
        </Typography>
        <Typography variant="body1" color="text.secondary" sx={{ mb: 4 }}>
          {isEditMode ? t('pages.editSubtitle') : t('pages.createSubtitle')}
        </Typography>

        <Paper sx={{ p: 4, mt: 3 }}>
          {isEditMode && task ? (
            <TradingTaskUpdateForm
              taskId={taskId}
              taskName={task.name}
              taskDescription={task.description}
              accountId={Number(task.account_id)}
              accountName={task.account_name}
              debugOptions={task.debug_options}
              restartRequiredForExecutionEdits={
                task.action_policy?.restart_required_for_execution_edits
              }
              initialData={{
                config_id: task.config_id,
                instrument: task.instrument,
                display_currency: task.display_currency,
                sell_on_stop: task.sell_on_stop ?? false,
                hedging_enabled: task.hedging_enabled,
                tick_granularity: task.tick_granularity,
                initial_positions_enabled:
                  task.initial_positions_enabled ?? false,
                initial_position_cycles: task.initial_position_cycles ?? [],
                api_retry_max_attempts: task.api_retry_max_attempts,
                api_retry_backoff_base_seconds:
                  task.api_retry_backoff_base_seconds
                    ? Number(task.api_retry_backoff_base_seconds)
                    : undefined,
                api_retry_backoff_max_seconds:
                  task.api_retry_backoff_max_seconds
                    ? Number(task.api_retry_backoff_max_seconds)
                    : undefined,
                drain_duration_hours: task.drain_duration_hours,
                market_idle_pre_close_minutes:
                  task.market_idle_pre_close_minutes,
                market_idle_resume_delay_minutes:
                  task.market_idle_resume_delay_minutes,
                live_tick_stale_guard_enabled:
                  task.live_tick_stale_guard_enabled,
                live_tick_max_age_seconds: task.live_tick_max_age_seconds,
                live_tick_status_log_interval_seconds:
                  task.live_tick_status_log_interval_seconds,
                broker_drift_check_interval_seconds:
                  task.broker_drift_check_interval_seconds,
              }}
            />
          ) : (
            <TradingTaskForm />
          )}
        </Paper>
      </Box>
    </PageContainer>
  );
}
