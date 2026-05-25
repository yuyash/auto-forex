import { useState } from 'react';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import type { ConfigSchema, StrategyConfig } from '../../types/strategy';
import StrategyConfigForm from './StrategyConfigForm';

const configSchema: ConfigSchema = {
  type: 'object',
  properties: {
    multiplier: {
      type: 'number',
      title: 'Multiplier',
      default: 1,
    },
    step_count: {
      type: 'integer',
      title: 'Step Count',
      default: 2,
      minimum: 1,
    },
    step_values: {
      type: 'array',
      title: 'Step Values',
      default: [1, 2],
      linkedCount: {
        field: 'step_count',
      },
      items: {
        type: 'number',
        minimum: 0.1,
      },
      itemLabel: 'Step {index}',
    },
  },
};

const initialConfig: StrategyConfig = {
  multiplier: 1,
  step_count: 2,
  step_values: [1, 2],
};

const StatefulForm = ({
  onConfigChange,
}: {
  onConfigChange: (config: StrategyConfig) => void;
}) => {
  const [config, setConfig] = useState<StrategyConfig>(initialConfig);

  return (
    <StrategyConfigForm
      configSchema={configSchema}
      config={config}
      onChange={(nextConfig) => {
        setConfig(nextConfig);
        onConfigChange(nextConfig);
      }}
      showValidation
    />
  );
};

describe('StrategyConfigForm', () => {
  it('keeps decimal input drafts for scalar number fields', async () => {
    const user = userEvent.setup();
    const onConfigChange = vi.fn();

    render(<StatefulForm onConfigChange={onConfigChange} />);

    const multiplierInput = screen.getByRole('textbox', {
      name: 'Multiplier',
    });

    await user.clear(multiplierInput);
    await user.type(multiplierInput, '1.');

    expect(multiplierInput).toHaveValue('1.');
    expect(onConfigChange).toHaveBeenLastCalledWith(
      expect.objectContaining({ multiplier: 1 })
    );

    await user.type(multiplierInput, '5');

    expect(multiplierInput).toHaveValue('1.5');
    expect(onConfigChange).toHaveBeenLastCalledWith(
      expect.objectContaining({ multiplier: 1.5 })
    );
  });

  it('keeps decimal input drafts for linked numeric array fields', async () => {
    const user = userEvent.setup();
    const onConfigChange = vi.fn();

    render(<StatefulForm onConfigChange={onConfigChange} />);

    const firstStepInput = screen.getByRole('textbox', {
      name: 'Step 1',
    });

    await user.clear(firstStepInput);
    await user.type(firstStepInput, '2.');

    expect(firstStepInput).toHaveValue('2.');
    expect(onConfigChange).toHaveBeenLastCalledWith(
      expect.objectContaining({ step_values: [2, 2] })
    );

    await user.type(firstStepInput, '25');

    expect(firstStepInput).toHaveValue('2.25');
    expect(onConfigChange).toHaveBeenLastCalledWith(
      expect.objectContaining({ step_values: [2.25, 2] })
    );
  });
});
