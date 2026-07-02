import type React from 'react';
import type { UiTextKey } from '../../i18n/uiText';
import { Badge } from '../common/Badge';

export type BadgeVariant = NonNullable<React.ComponentProps<typeof Badge>['variant']>;

// Shared signal -> badge styling map, used by both SkillBreakdownTable
// (per-skill rows) and SkillConsensusCard (aggregated consensus) so signal
// styling stays consistent across both views without duplicating the map.
export const SIGNAL_VARIANT: Record<string, BadgeVariant> = {
  strong_buy: 'success',
  buy: 'success',
  hold: 'default',
  sell: 'danger',
  strong_sell: 'danger',
};

export const SIGNAL_LABEL_KEY: Record<string, UiTextKey> = {
  strong_buy: 'skillBreakdown.signal.strongBuy',
  buy: 'skillBreakdown.signal.buy',
  hold: 'skillBreakdown.signal.hold',
  sell: 'skillBreakdown.signal.sell',
  strong_sell: 'skillBreakdown.signal.strongSell',
};
