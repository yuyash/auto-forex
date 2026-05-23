import { Box, Divider, Typography } from '@mui/material';
import { useTranslation } from 'react-i18next';
import {
  type ExecutionWatermarks,
  type TaskSummary,
  type WatermarkInfo,
} from '../../../hooks/useTaskSummary';
import { useDateTimeFormatter } from '../../../hooks/useDateTimeFormatter';
import { useNumberFormatter } from '../../../hooks/useNumberFormatter';
import {
  formatAppNumber,
  formatAppPercent,
  formatMoneyAmount,
  type NumberFormatSeparators,
} from '../../../utils/numberFormat';

interface ExecutionWatermarkSummaryProps {
  summary: TaskSummary;
  pnlCurrency: string;
}

type WatermarkFormat = 'ratio' | 'money' | 'integer';

interface WatermarkDefinition {
  key: keyof ExecutionWatermarks;
  labelKey: string;
  format: WatermarkFormat;
}

const WATERMARK_DEFINITIONS: WatermarkDefinition[] = [
  {
    key: 'marginRatioMax',
    labelKey: 'marginRatioMax',
    format: 'ratio',
  },
  {
    key: 'baseUnitsMax',
    labelKey: 'baseUnitsMax',
    format: 'integer',
  },
  {
    key: 'openLongUnitsMax',
    labelKey: 'openLongUnitsMax',
    format: 'integer',
  },
  {
    key: 'openShortUnitsMax',
    labelKey: 'openShortUnitsMax',
    format: 'integer',
  },
  {
    key: 'realizedPnlMax',
    labelKey: 'realizedPnlMax',
    format: 'money',
  },
  {
    key: 'unrealizedPnlMin',
    labelKey: 'unrealizedPnlMin',
    format: 'money',
  },
  {
    key: 'openPositionsMax',
    labelKey: 'openPositionsMax',
    format: 'integer',
  },
  {
    key: 'activeCyclesMax',
    labelKey: 'activeCyclesMax',
    format: 'integer',
  },
];

const EMPTY_WATERMARK: WatermarkInfo = {
  value: null,
  timestamp: null,
};

export function ExecutionWatermarkSummary({
  summary,
  pnlCurrency,
}: ExecutionWatermarkSummaryProps) {
  const { t } = useTranslation('common');
  const { formatDateTime } = useDateTimeFormatter({
    includeSeconds: true,
    includeTimezone: true,
  });
  const { separators } = useNumberFormatter();
  const watermarks = summary.watermarks;
  const items = WATERMARK_DEFINITIONS.map((definition) => ({
    ...definition,
    watermark: watermarks?.[definition.key] ?? EMPTY_WATERMARK,
  }));
  const hasData = items.some((item) => item.watermark.value != null);

  return (
    <Box>
      <Divider sx={{ my: 2 }} />
      <Typography variant="h6" gutterBottom>
        {t('watermarks.title')}
      </Typography>
      {hasData ? (
        <Box
          sx={{
            display: 'grid',
            gap: 1,
            gridTemplateColumns: {
              xs: 'repeat(1, minmax(0, 1fr))',
              sm: 'repeat(2, minmax(0, 1fr))',
              md: 'repeat(4, minmax(0, 1fr))',
            },
          }}
        >
          {items.map((item) => (
            <Box
              key={item.key}
              sx={{
                border: 1,
                borderColor: 'divider',
                borderRadius: 1,
                p: 1.25,
                minWidth: 0,
                minHeight: 82,
                bgcolor: 'background.paper',
              }}
            >
              <Typography
                variant="caption"
                color="text.secondary"
                sx={{ display: 'block', lineHeight: 1.25 }}
              >
                {t(`watermarks.${item.labelKey}`)}
              </Typography>
              <Typography
                variant="body2"
                sx={{
                  fontWeight: 600,
                  lineHeight: 1.35,
                  overflowWrap: 'anywhere',
                  wordBreak: 'break-word',
                }}
              >
                {formatWatermarkValue(
                  item.watermark,
                  item.format,
                  pnlCurrency,
                  separators
                )}
              </Typography>
              <Typography
                variant="caption"
                color="text.secondary"
                sx={{ display: 'block', mt: 0.5, overflowWrap: 'anywhere' }}
              >
                {item.watermark.timestamp
                  ? t('watermarks.timestamp', {
                      time: formatDateTime(item.watermark.timestamp),
                    })
                  : t('watermarks.noTimestamp')}
              </Typography>
            </Box>
          ))}
        </Box>
      ) : (
        <Typography variant="body2" color="text.secondary">
          {t('watermarks.noData')}
        </Typography>
      )}
    </Box>
  );
}

function formatWatermarkValue(
  watermark: WatermarkInfo,
  format: WatermarkFormat,
  pnlCurrency: string,
  separators: NumberFormatSeparators
): string {
  if (watermark.value == null || !Number.isFinite(watermark.value)) {
    return '-';
  }
  if (format === 'ratio') {
    const percentValue =
      Math.abs(watermark.value) <= 1 ? watermark.value * 100 : watermark.value;
    return formatAppPercent(percentValue, 2, false, separators);
  }
  if (format === 'money') {
    return formatMoneyAmount(
      watermark.value,
      pnlCurrency,
      { signed: true },
      separators
    );
  }
  return formatAppNumber(
    watermark.value,
    {
      maximumFractionDigits: 0,
    },
    separators
  );
}
