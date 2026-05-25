import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { TaskMetricsTab } from '../../../src/components/tasks/detail/TaskMetricsTab';
import type {
  MetricPoint,
  MetricsPeriod,
  PeriodicReturnMetricPoint,
  PeriodicTradeMetricsResponse,
} from '../../../src/utils/fetchMetrics';

const lineChartProps = vi.hoisted(
  () =>
    [] as Array<{
      series?: Array<{ label?: string; data?: Array<number | null> }>;
      width?: number;
      height?: number;
    }>
);
const barChartProps = vi.hoisted(
  () =>
    [] as Array<{
      xAxis?: Array<{ data?: string[] }>;
      width?: number;
      height?: number;
    }>
);

vi.mock('@mui/x-charts/LineChart', () => ({
  LineChart: (props: {
    series?: Array<{ label?: string; data?: Array<number | null> }>;
    width?: number;
    height?: number;
  }) => {
    lineChartProps.push(props);
    return <div data-testid="line-chart" />;
  },
}));

vi.mock('@mui/x-charts/BarChart', () => ({
  BarChart: (props: {
    xAxis?: Array<{ data?: string[] }>;
    width?: number;
    height?: number;
  }) => {
    barChartProps.push(props);
    return <div data-testid="bar-chart" />;
  },
}));

describe('TaskMetricsTab', () => {
  beforeEach(() => {
    lineChartProps.length = 0;
    barChartProps.length = 0;
    window.localStorage.clear();
  });

  const periodicReturns = (
    period: MetricsPeriod,
    rows: Array<[label: string, periodReturn: string]>
  ): PeriodicTradeMetricsResponse => {
    const returns = {
      day: [] as PeriodicReturnMetricPoint[],
      week: [] as PeriodicReturnMetricPoint[],
      month: [] as PeriodicReturnMetricPoint[],
      year: [] as PeriodicReturnMetricPoint[],
    };
    returns[period] = rows.map(([label, periodReturn], index) => ({
      t: index + 1,
      timestamp: label,
      label,
      period_return: periodReturn,
    }));

    return {
      execution_id: null,
      strategy_type: '',
      instrument: null,
      currency: null,
      timezone: 'UTC',
      periods: {
        day: [],
        week: [],
        month: [],
        year: [],
      },
      returns,
    };
  };

  it('renders large metric series without overflowing the call stack', () => {
    const data: MetricPoint[] = Array.from({ length: 150_000 }, (_, index) => ({
      t: 1_700_000_000 + index * 60,
      metrics: {
        current_balance: 10_000 + index * 0.01,
      },
    }));

    render(
      <TaskMetricsTab
        data={data}
        isLoading={false}
        error={null}
        interval={1}
        since=""
        until=""
        onIntervalChange={vi.fn()}
        onSinceChange={vi.fn()}
        onUntilChange={vi.fn()}
        onRefresh={vi.fn()}
        periodicMetrics={periodicReturns('week', [
          ['2026-01-05', '0.02'],
          ['2026-01-12', '0.03'],
        ])}
      />
    );

    expect(screen.getByTestId('line-chart')).toBeInTheDocument();
  });

  it('falls back to the chart panel size when Safari reports a zero-size chart host', async () => {
    const clientWidthDescriptor = Object.getOwnPropertyDescriptor(
      HTMLElement.prototype,
      'clientWidth'
    );
    const clientHeightDescriptor = Object.getOwnPropertyDescriptor(
      HTMLElement.prototype,
      'clientHeight'
    );
    const originalGetBoundingClientRect =
      HTMLElement.prototype.getBoundingClientRect;
    const measuredSize = (element: HTMLElement) =>
      element.dataset.chartPanelPlot === 'true'
        ? { width: 640, height: 300 }
        : { width: 0, height: 0 };

    Object.defineProperty(HTMLElement.prototype, 'clientWidth', {
      configurable: true,
      get() {
        return measuredSize(this).width;
      },
    });
    Object.defineProperty(HTMLElement.prototype, 'clientHeight', {
      configurable: true,
      get() {
        return measuredSize(this).height;
      },
    });
    HTMLElement.prototype.getBoundingClientRect = function () {
      const size = measuredSize(this);
      return {
        x: 0,
        y: 0,
        top: 0,
        left: 0,
        right: size.width,
        bottom: size.height,
        width: size.width,
        height: size.height,
        toJSON: () => ({}),
      } as DOMRect;
    };

    const data: MetricPoint[] = [1_700_000_000, 1_700_000_060].map(
      (t, index) => ({
        t,
        metrics: {
          current_balance: 10_000 + index,
          total_return: index * 0.01,
        },
      })
    );

    const { unmount } = render(
      <TaskMetricsTab
        data={data}
        isLoading={false}
        error={null}
        interval={1}
        since=""
        until=""
        onIntervalChange={vi.fn()}
        onSinceChange={vi.fn()}
        onUntilChange={vi.fn()}
        onRefresh={vi.fn()}
        periodicMetrics={periodicReturns('week', [
          ['2026-01-05', '2'],
          ['2026-01-12', '3'],
        ])}
      />
    );

    try {
      await waitFor(() => {
        expect(
          lineChartProps.some(
            (props) => props.width === 640 && props.height === 300
          )
        ).toBe(true);
        expect(
          barChartProps.some(
            (props) => props.width === 640 && props.height === 300
          )
        ).toBe(true);
      });
    } finally {
      unmount();
      if (clientWidthDescriptor) {
        Object.defineProperty(
          HTMLElement.prototype,
          'clientWidth',
          clientWidthDescriptor
        );
      }
      if (clientHeightDescriptor) {
        Object.defineProperty(
          HTMLElement.prototype,
          'clientHeight',
          clientHeightDescriptor
        );
      }
      HTMLElement.prototype.getBoundingClientRect =
        originalGetBoundingClientRect;
    }
  });

  it('renders SnowballNet strategy chart metrics without win/loss charts', () => {
    const data: MetricPoint[] = [1_700_000_000, 1_700_000_060].map(
      (t, index) => ({
        t,
        metrics: {
          total_pnl: 100 + index,
          total_pnl_quote: 100 + index,
          realized_pnl: 80 + index,
          realized_pnl_quote: 80 + index,
          unrealized_pnl: 20 + index,
          unrealized_pnl_quote: 20 + index,
          margin_ratio: 0.34 + index * 0.01,
          snowball_net_current_price: 156 + index * 0.01,
          snowball_net_target_price: 156.2 + index * 0.01,
          snowball_net_next_add_price: 155.9 - index * 0.01,
          snowball_net_theoretical_next_add_price: 155.7 - index * 0.01,
          snowball_net_pips_from_average: 4 + index,
          snowball_net_margin_ratio_pct: 34 + index,
          snowball_net_next_add_distance_pips: 12 - index,
          snowball_net_loss_cut_threshold_pips: -120,
          snowball_net_margin_reduce_threshold_pct: 85,
          snowball_net_margin_reduce_target_pct: 70,
          snowball_net_emergency_threshold_pct: 95,
          win_rate: 50,
          winning_trades: 1,
          losing_trades: 1,
        },
      })
    );

    render(
      <TaskMetricsTab
        data={data}
        isLoading={false}
        error={null}
        interval={1}
        since=""
        until=""
        onIntervalChange={vi.fn()}
        onSinceChange={vi.fn()}
        onUntilChange={vi.fn()}
        onRefresh={vi.fn()}
        strategyType="snowball_net"
      />
    );

    expect(screen.getByText('Price Levels')).toBeInTheDocument();
    expect(screen.getByText('Pips From Average')).toBeInTheDocument();
    expect(screen.getByText('Margin Closeout Ratio')).toBeInTheDocument();
    expect(screen.getByText('Total PnL')).toBeInTheDocument();
    expect(screen.getByText('Realized PnL')).toBeInTheDocument();
    expect(screen.getByText('Unrealized PnL')).toBeInTheDocument();
    expect(screen.queryByText('Total PnL (Quote)')).not.toBeInTheDocument();
    expect(screen.queryByText('Realized PnL (Quote)')).not.toBeInTheDocument();
    expect(
      screen.queryByText('Unrealized PnL (Quote)')
    ).not.toBeInTheDocument();
    expect(screen.getAllByText('Margin Closeout Ratio')).toHaveLength(1);
    expect(screen.queryByText('Exit Price')).not.toBeInTheDocument();
    expect(screen.queryByText('Next Add Price')).not.toBeInTheDocument();
    expect(screen.queryByText('Current Net Price')).not.toBeInTheDocument();
    expect(
      screen.queryByText('Theoretical Next Add Price')
    ).not.toBeInTheDocument();
    expect(screen.queryByText('Next Add Distance')).not.toBeInTheDocument();
    expect(screen.queryByText('Loss Cut Threshold')).not.toBeInTheDocument();
    expect(
      screen.queryByText('Margin Reduce Threshold')
    ).not.toBeInTheDocument();
    expect(screen.queryByText('Margin Reduce Target')).not.toBeInTheDocument();
    expect(
      screen.queryByText('Emergency Stop Threshold')
    ).not.toBeInTheDocument();
    expect(screen.queryByText('Win Rate')).not.toBeInTheDocument();
    expect(screen.queryByText('Winning Trades')).not.toBeInTheDocument();
    expect(screen.queryByText('Losing Trades')).not.toBeInTheDocument();

    const lineChartLabels = lineChartProps.map(
      (props) => props.series?.map((series) => series.label ?? '') ?? []
    );
    const hasChartWithLabels = (...labels: string[]) =>
      lineChartLabels.some((chartLabels) =>
        labels.every((label) => chartLabels.includes(label))
      );
    const hasSingleSeriesChart = (label: string) =>
      lineChartLabels.some(
        (chartLabels) => chartLabels.length === 1 && chartLabels[0] === label
      );

    expect(
      hasChartWithLabels('Next Add Price', 'Current Net Price', 'Exit Price')
    ).toBe(true);
    expect(hasChartWithLabels('Pips From Average', 'Loss Cut Threshold')).toBe(
      true
    );
    expect(
      hasChartWithLabels(
        'Margin Closeout Ratio',
        'Margin Reduce Threshold',
        'Margin Reduce Target',
        'Emergency Stop Threshold'
      )
    ).toBe(true);
    expect(hasSingleSeriesChart('Current Net Price')).toBe(false);
    expect(hasSingleSeriesChart('Exit Price')).toBe(false);
    expect(hasSingleSeriesChart('Next Add Price')).toBe(false);
    expect(hasSingleSeriesChart('Margin Reduce Threshold')).toBe(false);
    expect(hasSingleSeriesChart('Margin Reduce Target')).toBe(false);
    expect(hasSingleSeriesChart('Emergency Stop Threshold')).toBe(false);
    expect(lineChartLabels.flat().includes('Theoretical Next Add Price')).toBe(
      false
    );
    expect(lineChartLabels.flat().includes('Next Add Distance')).toBe(false);
  });

  it('renders Snowball risk guard integer cooldown metrics', () => {
    const data: MetricPoint[] = [
      {
        t: 1_700_000_000,
        metrics: {
          snowball_volatility_guard_cooldown_remaining_minutes: 3,
        },
      },
    ];

    render(
      <TaskMetricsTab
        data={data}
        isLoading={false}
        error={null}
        interval={1}
        since=""
        until=""
        onIntervalChange={vi.fn()}
        onSinceChange={vi.fn()}
        onUntilChange={vi.fn()}
        onRefresh={vi.fn()}
        strategyType="snowball"
      />
    );

    expect(screen.getByText('Snowball Guard')).toBeInTheDocument();
    expect(screen.getByText('3 min')).toBeInTheDocument();
  });

  it('labels weekly period returns by the week start date', () => {
    const data: MetricPoint[] = [
      ['2026-01-06T00:00:00Z', 0],
      ['2026-01-09T00:00:00Z', 0.02],
      ['2026-01-13T00:00:00Z', 0.02],
      ['2026-01-16T00:00:00Z', 0.05],
    ].map(([iso, totalReturn]) => ({
      t: Math.floor(new Date(iso).getTime() / 1000),
      metrics: {
        total_return: totalReturn,
      },
    }));

    render(
      <TaskMetricsTab
        data={data}
        isLoading={false}
        error={null}
        interval={1}
        since=""
        until=""
        onIntervalChange={vi.fn()}
        onSinceChange={vi.fn()}
        onUntilChange={vi.fn()}
        onRefresh={vi.fn()}
        timezone="UTC"
        periodicMetrics={periodicReturns('week', [
          ['2026-01-05', '2'],
          ['2026-01-12', '3'],
        ])}
      />
    );

    fireEvent.click(screen.getByRole('button', { name: 'Weekly Return' }));

    const latestBarChart = barChartProps.at(-1);
    expect(latestBarChart?.xAxis?.[0]?.data).toEqual([
      '2026-01-05',
      '2026-01-12',
    ]);
    expect(latestBarChart?.xAxis?.[0]?.data).not.toContain('2026-W02');
  });

  it('defaults period returns to weekly for a one-year range', () => {
    const data: MetricPoint[] = [
      ['2026-01-01T00:00:00Z', 0],
      ['2026-04-01T00:00:00Z', 0.03],
      ['2026-08-01T00:00:00Z', 0.05],
      ['2026-12-31T00:00:00Z', 0.08],
    ].map(([iso, totalReturn]) => ({
      t: Math.floor(new Date(iso).getTime() / 1000),
      metrics: {
        total_return: totalReturn,
      },
    }));

    render(
      <TaskMetricsTab
        data={data}
        isLoading={false}
        error={null}
        interval={240}
        since=""
        until=""
        onIntervalChange={vi.fn()}
        onSinceChange={vi.fn()}
        onUntilChange={vi.fn()}
        onRefresh={vi.fn()}
        timezone="UTC"
        periodicMetrics={periodicReturns('week', [
          ['2025-12-29', '3'],
          ['2026-03-30', '2'],
          ['2026-07-27', '3'],
          ['2026-12-28', '0'],
        ])}
      />
    );

    const latestBarChart = barChartProps.at(-1);
    expect(latestBarChart?.xAxis?.[0]?.data).toEqual([
      '2025-12-29',
      '2026-03-30',
      '2026-07-27',
      '2026-12-28',
    ]);
  });

  it('defaults period returns to monthly beyond two years', () => {
    const data: MetricPoint[] = [
      ['2024-01-01T00:00:00Z', 0],
      ['2025-06-01T00:00:00Z', 0.04],
      ['2027-01-02T00:00:00Z', 0.09],
    ].map(([iso, totalReturn]) => ({
      t: Math.floor(new Date(iso).getTime() / 1000),
      metrics: {
        total_return: totalReturn,
      },
    }));

    render(
      <TaskMetricsTab
        data={data}
        isLoading={false}
        error={null}
        interval={1440}
        since=""
        until=""
        onIntervalChange={vi.fn()}
        onSinceChange={vi.fn()}
        onUntilChange={vi.fn()}
        onRefresh={vi.fn()}
        timezone="UTC"
        periodicMetrics={periodicReturns('month', [
          ['2024-01', '4'],
          ['2025-06', '5'],
          ['2027-01', '0'],
        ])}
      />
    );

    const latestBarChart = barChartProps.at(-1);
    expect(latestBarChart?.xAxis?.[0]?.data).toEqual([
      '2024-01',
      '2025-06',
      '2027-01',
    ]);
  });
});
