import type React from 'react';
import type { SkillConsensus } from '../../api/agent';
import { useUiLanguage } from '../../contexts/UiLanguageContext';
import { Card } from '../common/Card';
import { Badge } from '../common/Badge';
import { SIGNAL_VARIANT, SIGNAL_LABEL_KEY } from './signalBadge';

export interface SkillConsensusCardProps {
  consensus?: SkillConsensus | null;
}

/**
 * Renders the aggregated multi-skill consensus (signal / confidence / score
 * adjustment / reasoning) above SkillBreakdownTable. Reuses the same
 * signal -> badge mapping as SkillBreakdownTable so styling stays consistent.
 * Renders nothing when `consensus` is absent — callers may also gate the
 * surrounding block themselves.
 */
export const SkillConsensusCard: React.FC<SkillConsensusCardProps> = ({ consensus }) => {
  const { t } = useUiLanguage();

  if (!consensus) {
    return null;
  }

  const signalKey = consensus.signal?.toLowerCase();
  const variant = SIGNAL_VARIANT[signalKey] ?? 'default';
  const signalLabel = SIGNAL_LABEL_KEY[signalKey] ? t(SIGNAL_LABEL_KEY[signalKey]) : consensus.signal;

  return (
    <Card variant="bordered" padding="sm" className="mt-3">
      <div className="flex items-center justify-between gap-3">
        <span className="text-xs font-semibold uppercase tracking-wide text-secondary-text">
          {t('skillConsensus.title')}
        </span>
        <Badge variant={variant}>{signalLabel}</Badge>
      </div>
      <div className="mt-2 flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-secondary-text">
        <span>
          {t('skillConsensus.confidenceLabel')}: {Math.round((consensus.confidence ?? 0) * 100)}%
        </span>
        <span>
          {t('skillConsensus.scoreAdjustmentLabel')}: {consensus.score_adjustment > 0 ? '+' : ''}
          {consensus.score_adjustment}
        </span>
        <span>{t('skillConsensus.skillCountLabel', { count: consensus.skill_count ?? 0 })}</span>
      </div>
      {consensus.reasoning && (
        <p className="mt-2 text-xs leading-relaxed text-secondary-text">
          <span className="font-medium text-foreground">{t('skillConsensus.reasoningLabel')}: </span>
          {consensus.reasoning}
        </p>
      )}
    </Card>
  );
};
