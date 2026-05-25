import { useState, useEffect, useMemo, useCallback } from 'react';
import {
  Box,
  TextField,
  FormControl,
  InputLabel,
  Select,
  MenuItem,
  FormHelperText,
  Typography,
  Alert,
  Divider,
  Checkbox,
  FormControlLabel,
  Stack,
  Tooltip,
  IconButton,
  Button,
} from '@mui/material';
import InfoOutlinedIcon from '@mui/icons-material/InfoOutlined';
import { useTranslation } from 'react-i18next';
import type {
  ConfigSchema,
  ConfigProperty,
  StrategyConfig,
  ConfigPreset,
  FieldComparisonRule,
} from '../../types/strategy';
import { orderConfigFieldTuples } from '../../utils/configFieldOrder';
import {
  conditionMatchesValue,
  isParameterVisible,
  matchesDependsOn,
  normalizeComparableValue,
} from '../../utils/strategySchemaDependsOn';
import {
  calculateSnowballReferenceBaseUnits,
  SNOWBALL_AUTO_BASE_UNITS_REFERENCE_BALANCE,
  syncSnowballReferenceBaseUnits,
} from '../../utils/snowballBaseUnits';

interface StrategyConfigFormProps {
  configSchema: ConfigSchema;
  config: StrategyConfig;
  onChange: (config: StrategyConfig) => void;
  disabled?: boolean;
  showValidation?: boolean;
}

interface ValidationErrors {
  [key: string]: string;
}

type NumericFieldType = 'number' | 'integer';

const DECIMAL_NUMBER_PATTERN =
  /^-?(?:(?:\d+\.?\d*)|(?:\.\d+))(?:[eE][+-]?\d+)?$/;
const INTEGER_NUMBER_PATTERN = /^-?\d+$/;

const cloneDefaultValue = (value: unknown): unknown => {
  if (Array.isArray(value)) return [...value];
  if (value && typeof value === 'object') {
    return { ...(value as Record<string, unknown>) };
  }
  return value;
};

const formatNumericInputValue = (value: unknown): string => {
  if (value === null || value === undefined) return '';
  if (typeof value === 'string' || typeof value === 'number') {
    return String(value);
  }
  return '';
};

const parseNumericInputValue = (
  raw: string,
  fieldType: NumericFieldType
): number | string => {
  if (raw === '') return '';

  if (fieldType === 'integer') {
    if (INTEGER_NUMBER_PATTERN.test(raw)) {
      return Number.parseInt(raw, 10);
    }

    if (DECIMAL_NUMBER_PATTERN.test(raw)) {
      const numeric = Number(raw);
      return Number.isInteger(numeric) ? numeric : raw;
    }

    return raw;
  }

  if (!DECIMAL_NUMBER_PATTERN.test(raw)) {
    return raw;
  }

  const numeric = Number(raw);
  return Number.isFinite(numeric) ? numeric : raw;
};

const comparisonPasses = (
  value: number,
  otherValue: number,
  operator: FieldComparisonRule['operator']
): boolean => {
  switch (operator) {
    case 'gt':
      return value > otherValue;
    case 'gte':
      return value >= otherValue;
    case 'lt':
      return value < otherValue;
    case 'lte':
      return value <= otherValue;
    case 'eq':
      return value === otherValue;
    default:
      return true;
  }
};

const StrategyConfigForm = ({
  configSchema,
  config,
  onChange,
  disabled = false,
  showValidation = false,
}: StrategyConfigFormProps) => {
  const { t, i18n } = useTranslation('strategy');

  /** Resolve a localized schema field: e.g. title_ja → title fallback. */
  const localized = useCallback(
    (
      prop: ConfigProperty,
      field: 'title' | 'description' | 'group'
    ): string | undefined => {
      const langKey = `${field}_${i18n.language}` as keyof ConfigProperty;
      return (prop[langKey] as string | undefined) ?? prop[field];
    },
    [i18n.language]
  );

  /** Resolve a localized enum label for a given option value. */
  const localizedEnumLabel = useCallback(
    (prop: ConfigProperty, value: string): string | undefined => {
      const langKey = `enum_labels_${i18n.language}` as keyof ConfigProperty;
      const langLabels = prop[langKey] as Record<string, string> | undefined;
      if (langLabels?.[value]) return langLabels[value];
      return prop.enum_labels?.[value];
    },
    [i18n.language]
  );

  const localizedEnumDescription = useCallback(
    (prop: ConfigProperty, value: string): string | undefined => {
      const langKey =
        `enum_descriptions_${i18n.language}` as keyof ConfigProperty;
      const langDescriptions = prop[langKey] as
        | Record<string, string>
        | undefined;
      if (langDescriptions?.[value]) return langDescriptions[value];
      return prop.enum_descriptions?.[value];
    },
    [i18n.language]
  );

  const localizedPresetField = useCallback(
    (
      preset: ConfigPreset,
      field: 'label' | 'description'
    ): string | undefined => {
      const langKey = `${field}_${i18n.language}` as keyof ConfigPreset;
      return (preset[langKey] as string | undefined) ?? preset[field];
    },
    [i18n.language]
  );

  const [validationErrors, setValidationErrors] = useState<ValidationErrors>(
    {}
  );
  const [jsonDrafts, setJsonDrafts] = useState<Record<string, string>>({});
  const [jsonDraftErrors, setJsonDraftErrors] = useState<
    Record<string, string>
  >({});
  const [numericDrafts, setNumericDrafts] = useState<Record<string, string>>(
    {}
  );

  const getNumericDraftKey = (fieldName: string, index?: number): string =>
    index === undefined ? fieldName : `${fieldName}.${index}`;

  const setNumericDraft = (key: string, value: string) => {
    setNumericDrafts((prev) => ({ ...prev, [key]: value }));
  };

  const clearNumericDraft = (key: string) => {
    setNumericDrafts((prev) => {
      if (!(key in prev)) return prev;
      const next = { ...prev };
      delete next[key];
      return next;
    });
  };

  useEffect(() => {
    setNumericDrafts({});
  }, [configSchema]);

  useEffect(() => {
    if (!configSchema.properties) {
      return;
    }

    let updatedConfig: StrategyConfig | null = null;

    Object.entries(configSchema.properties).forEach(
      ([fieldName, fieldSchema]) => {
        if (!fieldSchema.dependsOn) {
          return;
        }

        const matches = isParameterVisible(
          fieldName,
          config,
          configSchema.properties
        );

        if (
          !matches &&
          Object.prototype.hasOwnProperty.call(config, fieldName)
        ) {
          if (!updatedConfig) {
            updatedConfig = { ...config };
          }
          delete updatedConfig[fieldName];
        }
      }
    );

    if (updatedConfig) {
      onChange(updatedConfig);
    }
  }, [config, configSchema.properties, onChange]);

  // Auto-resize linkedCount arrays when the source field value changes.
  useEffect(() => {
    if (!configSchema.properties) return;

    let updatedConfig: StrategyConfig | null = null;

    Object.entries(configSchema.properties).forEach(
      ([fieldName, fieldSchema]) => {
        if (!fieldSchema.linkedCount || fieldSchema.type !== 'array') return;

        const { field: countField, offset = 0 } = fieldSchema.linkedCount;
        const targetLen = Math.max(0, Number(config[countField] ?? 0) + offset);
        const current = config[fieldName];
        if (!Array.isArray(current)) return;

        if (current.length !== targetLen) {
          if (!updatedConfig) updatedConfig = { ...config };
          const resized = [...current];
          // Pad with '' (empty) for new slots so inputs start blank
          while (resized.length < targetLen) {
            resized.push('');
          }
          // Trim excess
          updatedConfig[fieldName] = resized.slice(0, targetLen);
        }
      }
    );

    if (updatedConfig) onChange(updatedConfig);
  }, [config, configSchema, onChange]);

  useEffect(() => {
    const nextDrafts: Record<string, string> = {};
    Object.entries(configSchema.properties || {}).forEach(
      ([fieldName, fieldSchema]) => {
        if (
          fieldSchema.type === 'object' ||
          (fieldSchema.type === 'array' && fieldSchema.items?.type === 'object')
        ) {
          const value = config[fieldName] ?? fieldSchema.default;
          if (value !== undefined) {
            nextDrafts[fieldName] = JSON.stringify(value, null, 2);
          }
        }
      }
    );
    setJsonDrafts((prev) => ({ ...nextDrafts, ...prev }));
  }, [config, configSchema.properties]);

  // Validate config against schema
  const validateConfig = (currentConfig: StrategyConfig): ValidationErrors => {
    const errors: ValidationErrors = {};

    // Check required fields
    if (configSchema.required) {
      configSchema.required.forEach((fieldName) => {
        if (
          currentConfig[fieldName] === undefined ||
          currentConfig[fieldName] === null ||
          currentConfig[fieldName] === ''
        ) {
          errors[fieldName] = t('validation.required', {
            defaultValue: 'This field is required',
          });
        }
      });
    }

    // Validate field types and constraints
    Object.entries(configSchema.properties || {}).forEach(
      ([fieldName, fieldSchema]) => {
        const value = currentConfig[fieldName];

        if (
          !isParameterVisible(fieldName, currentConfig, configSchema.properties)
        ) {
          return;
        }

        // Skip validation if field is empty and not required
        if (
          value === undefined ||
          value === null ||
          value === '' ||
          (Array.isArray(value) && value.length === 0)
        ) {
          return;
        }

        // Number validation
        if (fieldSchema.type === 'number' || fieldSchema.type === 'integer') {
          const numValue = Number(value);

          if (!Number.isFinite(numValue)) {
            errors[fieldName] = t('validation.invalidNumber', {
              defaultValue: 'Must be a valid number',
            });
            return;
          }

          if (
            fieldSchema.minimum !== undefined &&
            numValue < fieldSchema.minimum
          ) {
            errors[fieldName] = t('validation.minimum', {
              defaultValue: `Must be at least ${fieldSchema.minimum}`,
              min: fieldSchema.minimum,
            });
          }

          if (
            fieldSchema.maximum !== undefined &&
            numValue > fieldSchema.maximum
          ) {
            errors[fieldName] = t('validation.maximum', {
              defaultValue: `Must be at most ${fieldSchema.maximum}`,
              max: fieldSchema.maximum,
            });
          }

          if (fieldSchema.type === 'integer' && !Number.isInteger(numValue)) {
            errors[fieldName] = t('validation.integer', {
              defaultValue: 'Must be a whole number',
            });
          }

          fieldSchema.comparisonRules?.forEach((rule) => {
            if (
              rule.dependsOn &&
              !matchesDependsOn(
                currentConfig,
                rule.dependsOn,
                configSchema.properties
              )
            ) {
              return;
            }

            const otherRaw =
              currentConfig[rule.field] ??
              configSchema.properties?.[rule.field]?.default;
            const otherValue = Number(otherRaw);
            if (Number.isNaN(otherValue)) return;

            if (!comparisonPasses(numValue, otherValue, rule.operator)) {
              const langKey =
                `message_${i18n.language}` as keyof FieldComparisonRule;
              errors[fieldName] =
                (rule[langKey] as string | undefined) ??
                rule.message ??
                t('validation.invalidComparison', {
                  defaultValue:
                    'Value does not satisfy related field constraint',
                });
            }
          });
        }

        // Array validation
        if (fieldSchema.type === 'array' && Array.isArray(value)) {
          if (fieldSchema.items?.type === 'string') {
            const invalidItems = value.filter(
              (item) => typeof item !== 'string'
            );
            if (invalidItems.length > 0) {
              errors[fieldName] = t('validation.invalidArray', {
                defaultValue: 'All items must be strings',
              });
            }
          }
          if (fieldSchema.items?.type === 'number') {
            const hasEmpty = value.some(
              (item) => item === '' || item === null || item === undefined
            );
            if (hasEmpty) {
              errors[fieldName] = t('validation.allItemsRequired', {
                defaultValue: 'All values must be filled in',
              });
              return;
            }

            const numericValues = value.map((item) => Number(item));
            if (numericValues.some((item) => !Number.isFinite(item))) {
              errors[fieldName] = t('validation.invalidNumber', {
                defaultValue: 'Must be a valid number',
              });
              return;
            }

            const itemMinimum = fieldSchema.items.minimum;
            if (
              itemMinimum !== undefined &&
              numericValues.some((item) => item < itemMinimum)
            ) {
              errors[fieldName] = t('validation.minimum', {
                defaultValue: `Must be at least ${itemMinimum}`,
                min: itemMinimum,
              });
            }

            const itemMaximum = fieldSchema.items.maximum;
            if (
              itemMaximum !== undefined &&
              numericValues.some((item) => item > itemMaximum)
            ) {
              errors[fieldName] = t('validation.maximum', {
                defaultValue: `Must be at most ${itemMaximum}`,
                max: itemMaximum,
              });
            }
          }
        }

        // Enum validation
        if (
          fieldSchema.enum &&
          !fieldSchema.enum.some((option) =>
            conditionMatchesValue(value, option)
          )
        ) {
          errors[fieldName] = t('validation.invalidOption', {
            defaultValue: 'Invalid option selected',
          });
        }
      }
    );

    return errors;
  };

  // Validate on config change
  useEffect(() => {
    if (showValidation) {
      const errors = validateConfig(config);
      setValidationErrors(errors);
    } else {
      setValidationErrors({});
    }
    // validateConfig is stable and doesn't need to be in deps
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [config, showValidation, configSchema]);

  // Handle field change
  const handleFieldChange = (fieldName: string, value: unknown) => {
    let updatedConfig = {
      ...config,
      [fieldName]: value,
    };

    // Mutual exclusion: when a boolean field with exclusiveWith is set to true,
    // automatically set the other field to false.
    const fieldSchema = configSchema.properties?.[fieldName];
    if (
      fieldSchema?.exclusiveWith &&
      fieldSchema.type === 'boolean' &&
      value === true
    ) {
      updatedConfig[fieldSchema.exclusiveWith] = false;
    }

    Object.entries(configSchema.properties || {}).forEach(
      ([dependentFieldName, dependentSchema]) => {
        if (
          !dependentSchema.dependsOn ||
          dependentSchema.deferDefaultUntilConfigured
        ) {
          return;
        }

        const wasVisible = isParameterVisible(
          dependentFieldName,
          config,
          configSchema.properties
        );
        const isVisible = isParameterVisible(
          dependentFieldName,
          updatedConfig,
          configSchema.properties
        );
        if (
          !wasVisible &&
          isVisible &&
          !Object.prototype.hasOwnProperty.call(
            updatedConfig,
            dependentFieldName
          ) &&
          Object.prototype.hasOwnProperty.call(dependentSchema, 'default')
        ) {
          updatedConfig[dependentFieldName] = cloneDefaultValue(
            dependentSchema.default
          );
        }
      }
    );

    updatedConfig = syncSnowballReferenceBaseUnits(
      updatedConfig,
      configSchema.properties,
      fieldName
    );

    onChange(updatedConfig);
  };

  const handlePresetApply = (preset: ConfigPreset) => {
    setNumericDrafts({});
    onChange({
      ...config,
      ...preset.parameters,
    });
  };

  const setJsonFieldError = (fieldName: string, message: string | null) => {
    setJsonDraftErrors((prev) => {
      const next = { ...prev };
      if (message) {
        next[fieldName] = message;
      } else {
        delete next[fieldName];
      }
      return next;
    });
  };

  const renderLabel = (label: string, description?: string) => {
    if (!description) return label;
    return (
      <Box
        component="span"
        sx={{ display: 'inline-flex', alignItems: 'center', gap: 0.5 }}
      >
        <span>{label}</span>
        <Tooltip title={description} placement="top" arrow>
          <IconButton aria-label={`${label} help`}>
            <InfoOutlinedIcon fontSize="inherit" />
          </IconButton>
        </Tooltip>
      </Box>
    );
  };

  const formatNumber = (value: number): string => {
    return new Intl.NumberFormat(i18n.language).format(value);
  };

  const renderAutoBaseUnitsHelper = (
    fieldName: string,
    baseHelperText: string | undefined
  ) => {
    const autoAdjustEnabled =
      normalizeComparableValue(config.base_units_auto_adjust_enabled) === true;
    if (
      !autoAdjustEnabled ||
      !['base_units', 'base_units_balance_ratio', 'base_units_step'].includes(
        fieldName
      )
    ) {
      return baseHelperText;
    }

    const referenceBaseUnits = calculateSnowballReferenceBaseUnits(
      config.base_units_balance_ratio,
      config.base_units_step
    );
    if (referenceBaseUnits === null) {
      return baseHelperText;
    }

    const previewText = t('autoBaseUnits.referencePreview', {
      defaultValue:
        'At reference balance {{balance}}, base units are {{units}}. Runtime uses the actual task/account balance.',
      balance: formatNumber(SNOWBALL_AUTO_BASE_UNITS_REFERENCE_BALANCE),
      units: formatNumber(referenceBaseUnits),
    });

    if (!baseHelperText) return previewText;
    return (
      <>
        {baseHelperText}
        <br />
        {previewText}
      </>
    );
  };

  // Render field based on schema type
  const renderField = (fieldName: string, fieldSchema: ConfigProperty) => {
    const value = config[fieldName] ?? fieldSchema.default ?? '';
    const error = jsonDraftErrors[fieldName] || validationErrors[fieldName];
    const isRequired = configSchema.required?.includes(fieldName);
    const label =
      localized(fieldSchema, 'title') ?? formatFieldLabel(fieldName);
    const labelNode = renderLabel(label, localized(fieldSchema, 'description'));
    const fieldDisabled =
      disabled ||
      Boolean(
        fieldSchema.disabledWhen &&
          matchesDependsOn(
            config,
            fieldSchema.disabledWhen,
            configSchema.properties
          )
      );

    // Enum field (dropdown)
    if (fieldSchema.enum) {
      const hasExplicitValue = Object.prototype.hasOwnProperty.call(
        config,
        fieldName
      );
      const isNumericEnum = fieldSchema.enum.every(
        (opt) => typeof opt === 'number'
      );
      const selectValue =
        fieldSchema.deferDefaultUntilConfigured && !hasExplicitValue
          ? ''
          : isNumericEnum
            ? Number(value)
            : String(value);

      const getOptionDescription = (option: string | number): string => {
        return localizedEnumDescription(fieldSchema, String(option)) || '';
      };

      // Format numeric enum values (e.g., granularity seconds to readable names)
      const formatNumericEnumValue = (val: number): string => {
        const granularityNames: Record<number, string> = {
          300: 'M5 (5 minutes)',
          900: 'M15 (15 minutes)',
          1800: 'M30 (30 minutes)',
          3600: 'H1 (1 hour)',
          7200: 'H2 (2 hours)',
          14400: 'H4 (4 hours)',
          28800: 'H8 (8 hours)',
          43200: 'H12 (12 hours)',
          86400: 'D1 (1 day)',
          604800: 'W1 (1 week)',
        };
        return granularityNames[val] || String(val);
      };

      const enumOptions = (fieldSchema.enum || []).filter((option) => {
        const hidden = fieldSchema.hidden_enum_values ?? [];
        return !hidden.map(String).includes(String(option));
      });

      return (
        <FormControl
          fullWidth
          key={fieldName}
          error={!!error}
          disabled={fieldDisabled}
        >
          <InputLabel required={isRequired}>{labelNode}</InputLabel>
          <Select
            value={selectValue}
            label={label}
            displayEmpty={fieldSchema.deferDefaultUntilConfigured}
            onChange={(e) => {
              if (
                fieldSchema.deferDefaultUntilConfigured &&
                e.target.value === ''
              ) {
                const updatedConfig = { ...config };
                delete updatedConfig[fieldName];
                onChange(updatedConfig);
                return;
              }
              const newValue = isNumericEnum
                ? Number(e.target.value)
                : e.target.value;
              handleFieldChange(fieldName, newValue);
            }}
          >
            {fieldSchema.deferDefaultUntilConfigured && (
              <MenuItem value="">
                <em>
                  {t('common:selectOption', {
                    defaultValue: 'Select an option',
                  })}
                </em>
              </MenuItem>
            )}
            {enumOptions.map((option) => (
              <MenuItem key={String(option)} value={option}>
                <Box>
                  <Typography variant="body2">
                    {typeof option === 'number'
                      ? formatNumericEnumValue(option)
                      : (localizedEnumLabel(fieldSchema, String(option)) ??
                        formatEnumValue(String(option)))}
                  </Typography>
                  {getOptionDescription(option) && (
                    <Typography
                      variant="caption"
                      color="text.secondary"
                      sx={{
                        display: 'block',
                        maxWidth: 400,
                        whiteSpace: 'normal',
                        lineHeight: 1.3,
                      }}
                    >
                      {getOptionDescription(option)}
                    </Typography>
                  )}
                </Box>
              </MenuItem>
            ))}
          </Select>
          {(localized(fieldSchema, 'description') || error) && (
            <FormHelperText>
              {error || localized(fieldSchema, 'description')}
            </FormHelperText>
          )}
        </FormControl>
      );
    }

    // Boolean field (checkbox)
    if (fieldSchema.type === 'boolean') {
      return (
        <FormControlLabel
          key={fieldName}
          control={
            <Checkbox
              checked={normalizeComparableValue(value) === true}
              onChange={(e) => handleFieldChange(fieldName, e.target.checked)}
              disabled={fieldDisabled}
            />
          }
          label={
            <Box>
              <Typography variant="body2">
                {renderLabel(label, localized(fieldSchema, 'description'))}
                {isRequired && (
                  <Typography component="span" color="error">
                    {' '}
                    *
                  </Typography>
                )}
              </Typography>
            </Box>
          }
        />
      );
    }

    // Number field
    if (fieldSchema.type === 'number' || fieldSchema.type === 'integer') {
      const draftKey = getNumericDraftKey(fieldName);
      const inputValue =
        numericDrafts[draftKey] ?? formatNumericInputValue(value);

      return (
        <TextField
          key={fieldName}
          fullWidth
          label={labelNode}
          type="text"
          inputMode="decimal"
          value={inputValue}
          onChange={(e) => {
            const raw = e.target.value;
            setNumericDraft(draftKey, raw);
            handleFieldChange(
              fieldName,
              parseNumericInputValue(raw, fieldSchema.type as NumericFieldType)
            );
          }}
          onBlur={() => clearNumericDraft(draftKey)}
          helperText={renderAutoBaseUnitsHelper(
            fieldName,
            error || localized(fieldSchema, 'description')
          )}
          error={!!error}
          required={isRequired}
          disabled={fieldDisabled}
          inputProps={{
            min: fieldSchema.minimum,
            max: fieldSchema.maximum,
            step: fieldSchema.type === 'integer' ? 1 : 'any',
          }}
        />
      );
    }

    // Array field
    if (fieldSchema.type === 'array') {
      // --- Per-step numeric inputs (linkedCount) ---
      if (fieldSchema.linkedCount && fieldSchema.items?.type === 'number') {
        const countField = fieldSchema.linkedCount.field;
        const offset = fieldSchema.linkedCount.offset ?? 0;
        const countValue = Number(config[countField] ?? 0) + offset;
        const stepCount = Math.max(0, countValue);
        const currentArray = Array.isArray(value)
          ? (value as (number | string)[])
          : [];
        const itemMin = fieldSchema.items?.minimum;
        const labelTpl =
          ((fieldSchema as unknown as Record<string, unknown>)[
            `itemLabel_${i18n.language}`
          ] as string) ??
          fieldSchema.itemLabel ??
          `${label} {index}`;

        return (
          <Box key={fieldName}>
            <Typography variant="body2" color="text.secondary" sx={{ mb: 1 }}>
              {renderLabel(label, localized(fieldSchema, 'description'))}
            </Typography>
            {stepCount === 0 ? (
              <Typography variant="caption" color="text.secondary">
                {t('validation.linkedCountZero', {
                  defaultValue: `Set ${countField} first to configure per-step values.`,
                })}
              </Typography>
            ) : (
              <Stack spacing={1}>
                {Array.from({ length: stepCount }, (_, i) => {
                  const stepLabel = labelTpl.replace('{index}', String(i + 1));
                  const stepValue = currentArray[i] ?? '';
                  const draftKey = getNumericDraftKey(fieldName, i);
                  const inputValue =
                    numericDrafts[draftKey] ??
                    formatNumericInputValue(stepValue);
                  const numericStepValue = Number(stepValue);
                  const stepValueBelowMin =
                    itemMin !== undefined &&
                    Number.isFinite(numericStepValue) &&
                    numericStepValue < itemMin;

                  return (
                    <TextField
                      key={`${fieldName}_${i}`}
                      label={stepLabel}
                      type="text"
                      inputMode="decimal"
                      size="small"
                      value={inputValue}
                      onChange={(e) => {
                        const raw = e.target.value;
                        const next = [...currentArray];
                        // Ensure array is exactly stepCount long
                        while (next.length < stepCount) next.push('');
                        setNumericDraft(draftKey, raw);
                        next[i] = parseNumericInputValue(raw, 'number');
                        handleFieldChange(fieldName, next.slice(0, stepCount));
                      }}
                      onBlur={() => clearNumericDraft(draftKey)}
                      disabled={fieldDisabled}
                      error={!!error || stepValueBelowMin}
                      helperText={
                        stepValueBelowMin
                          ? t('validation.minimum', {
                              defaultValue: `Must be at least ${itemMin}`,
                              min: itemMin,
                            })
                          : undefined
                      }
                      inputProps={{
                        min: itemMin,
                        step: 'any',
                      }}
                      sx={{ maxWidth: 280 }}
                    />
                  );
                })}
              </Stack>
            )}
          </Box>
        );
      }

      if (fieldSchema.items?.type === 'object') {
        const jsonValue =
          jsonDrafts[fieldName] ??
          JSON.stringify(Array.isArray(value) ? value : [], null, 2);
        return (
          <TextField
            key={fieldName}
            fullWidth
            label={labelNode}
            value={jsonValue}
            onChange={(e) => {
              const raw = e.target.value;
              setJsonDrafts((prev) => ({ ...prev, [fieldName]: raw }));
              try {
                const parsed = raw.trim() ? JSON.parse(raw) : [];
                if (!Array.isArray(parsed)) {
                  setJsonFieldError(
                    fieldName,
                    t('validation.invalidArray', {
                      defaultValue: 'Must be a JSON array',
                    })
                  );
                  return;
                }
                setJsonFieldError(fieldName, null);
                handleFieldChange(fieldName, parsed);
              } catch {
                setJsonFieldError(
                  fieldName,
                  t('validation.invalidJson', {
                    defaultValue: 'Must be valid JSON',
                  })
                );
              }
            }}
            helperText={
              error ||
              localized(fieldSchema, 'description') ||
              'Enter a JSON array (example: [{"take_profit_pips": 25}])'
            }
            error={!!error}
            required={isRequired}
            disabled={fieldDisabled}
            multiline
            minRows={4}
          />
        );
      }

      const itemType = fieldSchema.items?.type ?? 'string';
      const arrayValue = Array.isArray(value) ? value.join(', ') : '';
      return (
        <TextField
          key={fieldName}
          fullWidth
          label={labelNode}
          value={arrayValue}
          onChange={(e) => {
            const parsedItems = e.target.value
              .split(',')
              .map((item) => item.trim())
              .filter((item) => item.length > 0)
              .map((item) => {
                if (itemType === 'integer') {
                  return Number.parseInt(item, 10);
                }
                if (itemType === 'number') {
                  return Number.parseFloat(item);
                }
                if (itemType === 'boolean') {
                  return item.toLowerCase() === 'true';
                }
                return item;
              });
            handleFieldChange(fieldName, parsedItems);
          }}
          helperText={
            error ||
            localized(fieldSchema, 'description') ||
            'Enter comma-separated values'
          }
          error={!!error}
          required={isRequired}
          disabled={fieldDisabled}
        />
      );
    }

    if (fieldSchema.type === 'object') {
      const jsonValue =
        jsonDrafts[fieldName] ??
        JSON.stringify(
          typeof value === 'object' && value !== null && !Array.isArray(value)
            ? value
            : {},
          null,
          2
        );
      return (
        <TextField
          key={fieldName}
          fullWidth
          label={labelNode}
          value={jsonValue}
          onChange={(e) => {
            const raw = e.target.value;
            setJsonDrafts((prev) => ({ ...prev, [fieldName]: raw }));
            try {
              const parsed = raw.trim() ? JSON.parse(raw) : {};
              if (
                typeof parsed !== 'object' ||
                parsed === null ||
                Array.isArray(parsed)
              ) {
                setJsonFieldError(
                  fieldName,
                  t('validation.invalidObject', {
                    defaultValue: 'Must be a JSON object',
                  })
                );
                return;
              }
              setJsonFieldError(fieldName, null);
              handleFieldChange(fieldName, parsed);
            } catch {
              setJsonFieldError(
                fieldName,
                t('validation.invalidJson', {
                  defaultValue: 'Must be valid JSON',
                })
              );
            }
          }}
          helperText={
            error ||
            localized(fieldSchema, 'description') ||
            'Enter a JSON object'
          }
          error={!!error}
          required={isRequired}
          disabled={fieldDisabled}
          multiline
          minRows={4}
        />
      );
    }

    // Default: string field
    const stringValue =
      typeof value === 'string' || typeof value === 'number'
        ? value
        : value === null || value === undefined
          ? ''
          : String(value);
    return (
      <TextField
        key={fieldName}
        fullWidth
        label={labelNode}
        value={stringValue}
        onChange={(e) => handleFieldChange(fieldName, e.target.value)}
        helperText={error || localized(fieldSchema, 'description')}
        error={!!error}
        required={isRequired}
        disabled={fieldDisabled}
      />
    );
  };

  // Format field name to readable label
  const formatFieldLabel = (fieldName: string): string => {
    return fieldName
      .split('_')
      .map((word) => word.charAt(0).toUpperCase() + word.slice(1))
      .join(' ');
  };

  // Format enum value to readable text
  const formatEnumValue = (value: string): string => {
    return value
      .split('_')
      .map((word) => word.charAt(0).toUpperCase() + word.slice(1))
      .join(' ');
  };

  // Check if there are any validation errors
  const hasErrors = Object.keys(validationErrors).length > 0;

  // Build ordered groups from schema properties
  // NOTE: This hook must be called before the early return below to satisfy
  // the Rules of Hooks (hooks must be called in the same order every render).
  const groupedFields = useMemo(() => {
    const groups: Array<{ name: string; fields: [string, ConfigProperty][] }> =
      [];
    const groupMap = new Map<string, [string, ConfigProperty][]>();
    const seenGroups: string[] = [];

    Object.entries(configSchema.properties || {}).forEach(
      ([fieldName, fieldSchema]) => {
        if (!isParameterVisible(fieldName, config, configSchema.properties)) {
          return;
        }
        const groupName = localized(fieldSchema, 'group') || '';
        if (!groupMap.has(groupName)) {
          groupMap.set(groupName, []);
          seenGroups.push(groupName);
        }
        groupMap.get(groupName)!.push([fieldName, fieldSchema]);
      }
    );

    seenGroups.forEach((name) => {
      groups.push({ name, fields: groupMap.get(name)! });
    });

    return groups;
  }, [config, configSchema.properties, localized]);

  if (
    !configSchema.properties ||
    Object.keys(configSchema.properties).length === 0
  ) {
    return (
      <Alert severity="info">
        {t('noParameters', {
          defaultValue: 'This strategy has no configurable parameters.',
        })}
      </Alert>
    );
  }

  return (
    <Box>
      {configSchema.presets && configSchema.presets.length > 0 && (
        <Box sx={{ mb: 3 }}>
          <Typography variant="subtitle1" gutterBottom>
            {t('presets.title', { defaultValue: 'Presets' })}
          </Typography>
          <Stack direction="row" spacing={1} sx={{ flexWrap: 'wrap' }}>
            {configSchema.presets.map((preset) => (
              <Tooltip
                key={preset.id}
                title={localizedPresetField(preset, 'description') ?? ''}
                arrow
              >
                <span>
                  <Button
                    variant="outlined"
                    size="small"
                    disabled={disabled}
                    onClick={() => handlePresetApply(preset)}
                  >
                    {localizedPresetField(preset, 'label') ?? preset.id}
                  </Button>
                </span>
              </Tooltip>
            ))}
          </Stack>
        </Box>
      )}

      {showValidation && hasErrors && (
        <Alert severity="error" sx={{ mb: 2 }}>
          {t('validation.formErrors', {
            defaultValue: 'Please fix the errors below before proceeding.',
          })}
        </Alert>
      )}

      {groupedFields.map(({ name: groupName, fields }, groupIdx) => {
        const orderedVisibleFields = orderConfigFieldTuples(fields);

        return (
          <Box key={groupName || '__ungrouped'} sx={{ mb: 3 }}>
            {groupIdx > 0 && <Divider sx={{ mb: 2 }} />}
            {groupName && (
              <Typography variant="subtitle1" gutterBottom>
                {groupName}
              </Typography>
            )}
            <Stack spacing={2}>
              {orderedVisibleFields.map(([fieldName, fieldSchema]) => (
                <Box key={fieldName}>{renderField(fieldName, fieldSchema)}</Box>
              ))}
            </Stack>
          </Box>
        );
      })}

      {configSchema.required && configSchema.required.length > 0 && (
        <Typography
          variant="caption"
          color="text.secondary"
          sx={{ mt: 2, display: 'block' }}
        >
          * {t('requiredFields', { defaultValue: 'Required fields' })}
        </Typography>
      )}
    </Box>
  );
};

export default StrategyConfigForm;
