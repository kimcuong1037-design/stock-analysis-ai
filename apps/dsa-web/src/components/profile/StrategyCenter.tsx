import type React from 'react';
import { useEffect, useState } from 'react';
import { agentApi, type SkillInfo } from '../../api/agent';
import { useUiLanguage } from '../../contexts/UiLanguageContext';
import { formatUiText } from '../../i18n/uiText';
import { EmptyState, InlineAlert, Loading } from '../common';
import { cn } from '../../utils/cn';

// Category display order
const CATEGORY_ORDER = ['trend', 'pattern', 'reversal', 'framework'] as const;
type KnownCategory = (typeof CATEGORY_ORDER)[number];

const CATEGORY_I18N_KEY: Record<KnownCategory | 'other', `strategyCenter.category.${string}`> = {
  trend: 'strategyCenter.category.trend',
  pattern: 'strategyCenter.category.pattern',
  reversal: 'strategyCenter.category.reversal',
  framework: 'strategyCenter.category.framework',
  other: 'strategyCenter.category.other',
} as const;

interface SkillCardProps {
  skill: SkillInfo;
  isSelected: boolean;
  isDisabled: boolean;
  onToggle: () => void;
}

const SkillCard: React.FC<SkillCardProps> = ({ skill, isSelected, isDisabled, onToggle }) => {
  const handleClick = () => {
    if (!isDisabled) {
      onToggle();
    }
  };

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if ((e.key === 'Enter' || e.key === ' ') && !isDisabled) {
      e.preventDefault();
      onToggle();
    }
  };

  return (
    <div
      role="checkbox"
      aria-checked={isSelected}
      aria-disabled={isDisabled}
      tabIndex={isDisabled ? -1 : 0}
      data-skill-id={skill.id}
      data-testid={`skill-card-${skill.id}`}
      onClick={handleClick}
      onKeyDown={handleKeyDown}
      className={cn(
        'relative rounded-xl border p-4 transition-all',
        'select-none focus:outline-none focus-visible:ring-2 focus-visible:ring-cyan/40',
        isSelected
          ? 'border-cyan/60 bg-cyan/10 shadow-soft-card'
          : 'border-border/60 bg-card/50',
        isDisabled && !isSelected
          ? 'cursor-not-allowed opacity-40'
          : 'cursor-pointer hover:border-cyan/40 hover:bg-card',
      )}
    >
      {/* Selection indicator */}
      <span
        className={cn(
          'absolute right-3 top-3 h-4 w-4 rounded border transition-colors',
          isSelected
            ? 'border-cyan bg-cyan'
            : 'border-border/60 bg-base',
        )}
        aria-hidden
      >
        {isSelected && (
          <svg viewBox="0 0 12 12" fill="none" xmlns="http://www.w3.org/2000/svg" className="h-full w-full p-0.5">
            <path d="M2 6l3 3 5-5" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" className="text-base" />
          </svg>
        )}
      </span>

      <p className="pr-6 text-sm font-semibold text-foreground">{skill.name}</p>
      <p className="mt-1 pr-6 text-xs text-secondary-text">{skill.description}</p>
    </div>
  );
};

export interface StrategyCenterProps {
  selected: string[];
  onChange: (ids: string[]) => void;
  maxSelected: number;
}

interface GroupedSkills {
  category: string;
  label: string;
  skills: SkillInfo[];
}

export const StrategyCenter: React.FC<StrategyCenterProps> = ({
  selected,
  onChange,
  maxSelected,
}) => {
  const { t } = useUiLanguage();
  const [skills, setSkills] = useState<SkillInfo[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;

    agentApi
      .getSkills()
      .then((res) => {
        if (!cancelled) {
          setSkills(res.skills);
          setLoading(false);
        }
      })
      .catch(() => {
        if (!cancelled) {
          setError(t('strategyCenter.loadingError'));
          setLoading(false);
        }
      });

    return () => {
      cancelled = true;
    };
  }, [t]);

  const handleToggle = (id: string) => {
    if (selected.includes(id)) {
      onChange(selected.filter((s) => s !== id));
    } else if (selected.length < maxSelected) {
      onChange([...selected, id]);
    }
  };

  // Group skills: known categories in order, unknowns in 'other'
  const grouped: GroupedSkills[] = (() => {
    const buckets: Record<string, SkillInfo[]> = {};
    for (const skill of skills) {
      const cat = skill.category ?? 'other';
      if (!buckets[cat]) buckets[cat] = [];
      buckets[cat].push(skill);
    }

    const result: GroupedSkills[] = [];

    for (const cat of CATEGORY_ORDER) {
      if (buckets[cat] && buckets[cat].length > 0) {
        result.push({
          category: cat,
          label: t(CATEGORY_I18N_KEY[cat]),
          skills: buckets[cat],
        });
      }
    }

    // Collect unknown categories for 'other' bucket
    const otherSkills: SkillInfo[] = [];
    for (const [cat, catSkills] of Object.entries(buckets)) {
      if (!(CATEGORY_ORDER as readonly string[]).includes(cat)) {
        otherSkills.push(...catSkills);
      }
    }
    if (otherSkills.length > 0) {
      result.push({
        category: 'other',
        label: t(CATEGORY_I18N_KEY['other']),
        skills: otherSkills,
      });
    }

    return result;
  })();

  const atMax = selected.length >= maxSelected;

  return (
    <div className="space-y-6">
      {/* Header with selected count */}
      <div className="flex items-center justify-between">
        <h3 className="text-base font-semibold text-foreground">{t('strategyCenter.title')}</h3>
        <span className="text-xs text-secondary-text">
          {formatUiText(t('strategyCenter.selectedCount'), { count: selected.length, max: maxSelected })}
        </span>
      </div>

      {/* Max-reached hint */}
      {atMax && (
        <InlineAlert variant="info" message={t('strategyCenter.maxReachedHint')} />
      )}

      {/* Loading state */}
      {loading && <Loading />}

      {/* Error state */}
      {!loading && error && (
        <InlineAlert variant="danger" message={error} />
      )}

      {/* Empty state */}
      {!loading && !error && skills.length === 0 && (
        <EmptyState
          title={t('strategyCenter.emptyTitle')}
          description={t('strategyCenter.emptyDescription')}
        />
      )}

      {/* Grouped skill cards */}
      {!loading && !error && grouped.map((group) => (
        <section key={group.category} aria-label={group.label}>
          <h4 className="mb-3 text-xs font-semibold uppercase tracking-wider text-muted-text">
            {group.label}
          </h4>
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
            {group.skills.map((skill) => {
              const isSelected = selected.includes(skill.id);
              const isDisabled = atMax && !isSelected;
              return (
                <SkillCard
                  key={skill.id}
                  skill={skill}
                  isSelected={isSelected}
                  isDisabled={isDisabled}
                  onToggle={() => handleToggle(skill.id)}
                />
              );
            })}
          </div>
        </section>
      ))}
    </div>
  );
};
