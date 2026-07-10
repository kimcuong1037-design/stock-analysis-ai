import type React from 'react';
import { Fragment, useState } from 'react';
import type { SkillBreakdownItem } from '../../api/agent';
import { useUiLanguage } from '../../contexts/UiLanguageContext';
import { Badge } from '../common/Badge';
import { JsonViewer } from '../common/JsonViewer';
import { cn } from '../../utils/cn';
import { SIGNAL_VARIANT, SIGNAL_LABEL_KEY } from './signalBadge';

const hasKeyLevels = (levels: Record<string, unknown> | null | undefined): boolean =>
  !!levels && Object.keys(levels).length > 0;

export interface SkillBreakdownTableProps {
  items: SkillBreakdownItem[];
}

/**
 * Renders one row per skill opinion (display_name / signal badge / confidence /
 * score adjustment). Rows expand on click to reveal reasoning and key_levels.
 * Renders nothing when `items` is empty — callers gate the surrounding block.
 */
export const SkillBreakdownTable: React.FC<SkillBreakdownTableProps> = ({ items }) => {
  const { t } = useUiLanguage();
  const [expandedId, setExpandedId] = useState<string | null>(null);

  if (!items || items.length === 0) {
    return null;
  }

  const toggleRow = (skillId: string) => {
    setExpandedId((prev) => (prev === skillId ? null : skillId));
  };

  return (
    <div className="mt-3 overflow-hidden rounded-xl border border-border/50">
      <div className="border-b border-border/40 bg-elevated/40 px-3 py-2 text-xs font-semibold uppercase tracking-wide text-secondary-text">
        {t('skillBreakdown.title')}
      </div>
      <table className="w-full text-left text-sm">
        <thead className="bg-elevated/60 text-xs uppercase tracking-wide text-secondary-text">
          <tr>
            <th className="px-3 py-2 font-medium">{t('skillBreakdown.columnSkill')}</th>
            <th className="px-3 py-2 font-medium">{t('skillBreakdown.columnSignal')}</th>
            <th className="px-3 py-2 font-medium">{t('skillBreakdown.columnConfidence')}</th>
            <th className="px-3 py-2 font-medium">{t('skillBreakdown.columnScoreAdjustment')}</th>
          </tr>
        </thead>
        <tbody>
          {items.map((item) => {
            const isExpanded = expandedId === item.skill_id;
            const signalKey = item.signal?.toLowerCase();
            const variant = SIGNAL_VARIANT[signalKey] ?? 'default';
            const signalLabel = SIGNAL_LABEL_KEY[signalKey] ? t(SIGNAL_LABEL_KEY[signalKey]) : item.signal;

            return (
              <Fragment key={item.skill_id}>
                <tr
                  role="button"
                  tabIndex={0}
                  aria-expanded={isExpanded}
                  onClick={() => toggleRow(item.skill_id)}
                  onKeyDown={(e) => {
                    if (e.key === 'Enter' || e.key === ' ') {
                      e.preventDefault();
                      toggleRow(item.skill_id);
                    }
                  }}
                  className="cursor-pointer border-t border-border/40 transition-colors hover:bg-hover"
                >
                  <td className="px-3 py-2 font-medium text-foreground">{item.display_name}</td>
                  <td className="px-3 py-2">
                    <Badge variant={variant}>{signalLabel}</Badge>
                  </td>
                  <td className="px-3 py-2 text-secondary-text">
                    {Math.round((item.confidence ?? 0) * 100)}%
                  </td>
                  <td
                    className={cn(
                      'px-3 py-2 font-medium',
                      item.score_adjustment > 0 && 'text-success',
                      item.score_adjustment < 0 && 'text-danger',
                      item.score_adjustment === 0 && 'text-secondary-text',
                    )}
                  >
                    {item.score_adjustment > 0 ? '+' : ''}
                    {item.score_adjustment}
                  </td>
                </tr>
                {isExpanded && (
                  <tr className="border-t border-border/40 bg-elevated/30">
                    <td colSpan={4} className="px-3 py-3">
                      <div className="space-y-2 text-xs text-secondary-text">
                        <div>
                          <span className="font-medium text-foreground">
                            {t('skillBreakdown.reasoningLabel')}:{' '}
                          </span>
                          {item.reasoning}
                        </div>
                        {hasKeyLevels(item.key_levels) && (
                          <div>
                            <span className="mb-1 block font-medium text-foreground">
                              {t('skillBreakdown.keyLevelsLabel')}
                            </span>
                            <JsonViewer data={item.key_levels} />
                          </div>
                        )}
                      </div>
                    </td>
                  </tr>
                )}
              </Fragment>
            );
          })}
        </tbody>
      </table>
    </div>
  );
};
