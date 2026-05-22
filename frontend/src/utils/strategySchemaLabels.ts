/**
 * Resolve localized parameter labels from a strategy JSON schema.
 *
 * Given a strategy type and the strategies list (which includes config_schema),
 * builds a map from raw parameter key → localized title string.
 */

import type { Strategy } from '../services/api/strategies';
import type { ConfigProperty } from '../types/strategy';

/**
 * Build a key→label map for strategy parameters using the JSON schema's
 * localized title fields (e.g. title_ja for Japanese).
 *
 * Falls back to the base `title`, then to a Title-Cased version of the key.
 */
export function buildParameterLabelMap(
  strategies: Strategy[],
  strategyType: string,
  language: string
): Map<string, string> {
  const map = new Map<string, string>();
  const strategy = strategies.find((s) => s.id === strategyType);
  if (!strategy?.config_schema) return map;

  const schema = strategy.config_schema as {
    properties?: Record<string, ConfigProperty>;
  };
  if (!schema.properties) return map;

  for (const [key, prop] of Object.entries(schema.properties)) {
    const localized = localizedPropertyString(prop, 'title', language);
    if (localized) {
      map.set(key, localized);
    }
  }

  return map;
}

function languageCandidates(language: string): string[] {
  const normalized = language.trim().toLowerCase();
  if (!normalized) return [];
  const base = normalized.split(/[-_]/)[0];
  return [...new Set([normalized, base])];
}

function localizedPropertyString(
  prop: ConfigProperty,
  prefix: 'title',
  language: string
): string | undefined {
  for (const candidate of languageCandidates(language)) {
    const value = prop[`${prefix}_${candidate}` as keyof ConfigProperty] as
      | string
      | undefined;
    if (value) return value;
  }
  return prop.title;
}

/**
 * Resolve a single parameter key to its localized label.
 * Returns the localized title if found, otherwise a Title-Cased version of the key.
 */
export function resolveParameterLabel(
  labelMap: Map<string, string>,
  key: string
): string {
  return (
    labelMap.get(key) ??
    key.replace(/_/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase())
  );
}
