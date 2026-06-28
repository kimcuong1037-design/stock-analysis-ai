import type React from 'react';
import { useState } from 'react';
import { agentApi, type SkillInfo } from '../../api/agent';
import { useUiLanguage } from '../../contexts/UiLanguageContext';
import { Button, InlineAlert, Loading } from '../common';
import { cn } from '../../utils/cn';

// ── Question definitions ──────────────────────────────────────────────────────

type QuestionKey = 'horizon' | 'risk' | 'style' | 'watch';

interface QuestionDef {
  key: QuestionKey;
  titleI18n: string;
  options: { value: string; labelI18n: string }[];
}

const QUESTIONS: QuestionDef[] = [
  {
    key: 'horizon',
    titleI18n: 'interviewWizard.q.horizon',
    options: [
      { value: 'ultra_short', labelI18n: 'interviewWizard.opt.horizon.ultra_short' },
      { value: 'swing',       labelI18n: 'interviewWizard.opt.horizon.swing' },
      { value: 'long',        labelI18n: 'interviewWizard.opt.horizon.long' },
    ],
  },
  {
    key: 'risk',
    titleI18n: 'interviewWizard.q.risk',
    options: [
      { value: 'conservative', labelI18n: 'interviewWizard.opt.risk.conservative' },
      { value: 'balanced',     labelI18n: 'interviewWizard.opt.risk.balanced' },
      { value: 'aggressive',   labelI18n: 'interviewWizard.opt.risk.aggressive' },
    ],
  },
  {
    key: 'style',
    titleI18n: 'interviewWizard.q.style',
    options: [
      { value: 'trend',      labelI18n: 'interviewWizard.opt.style.trend' },
      { value: 'reversal',   labelI18n: 'interviewWizard.opt.style.reversal' },
      { value: 'theme',      labelI18n: 'interviewWizard.opt.style.theme' },
      { value: 'value',      labelI18n: 'interviewWizard.opt.style.value' },
      { value: 'framework',  labelI18n: 'interviewWizard.opt.style.framework' },
    ],
  },
  {
    key: 'watch',
    titleI18n: 'interviewWizard.q.watch',
    options: [
      { value: 'high',   labelI18n: 'interviewWizard.opt.watch.high' },
      { value: 'medium', labelI18n: 'interviewWizard.opt.watch.medium' },
      { value: 'low',    labelI18n: 'interviewWizard.opt.watch.low' },
    ],
  },
];

// ── Types ─────────────────────────────────────────────────────────────────────

type Answers = Partial<Record<QuestionKey, string>>;

type WizardPhase =
  | { phase: 'questions' }
  | { phase: 'loading' }
  | { phase: 'error'; message: string }
  | { phase: 'result'; recommended: SkillInfo[]; explanation: string };

// ── Component ─────────────────────────────────────────────────────────────────

export interface InterviewWizardProps {
  onComplete: (ids: string[]) => void;
  onSkip: () => void;
}

export const InterviewWizard: React.FC<InterviewWizardProps> = ({ onComplete, onSkip }) => {
  const { t } = useUiLanguage();

  const [answers, setAnswers] = useState<Answers>({});
  const [state, setState] = useState<WizardPhase>({ phase: 'questions' });

  // ── Derived ─────────────────────────────────────────────────────────────────

  const allAnswered = QUESTIONS.every((q) => answers[q.key] !== undefined);

  // ── Handlers ────────────────────────────────────────────────────────────────

  const handleSelect = (key: QuestionKey, value: string) => {
    const next = { ...answers, [key]: value };
    setAnswers(next);

    // Auto-submit once all 4 are answered — only from the questions phase
    if (state.phase === 'questions' && QUESTIONS.every((q) => next[q.key] !== undefined)) {
      void submit(next as Record<QuestionKey, string>);
    }
  };

  const submit = async (finalAnswers: Record<QuestionKey, string>) => {
    setState({ phase: 'loading' });
    try {
      const result = await agentApi.submitInterview(finalAnswers);
      setState({ phase: 'result', recommended: result.recommended, explanation: result.explanation });
    } catch {
      setState({ phase: 'error', message: t('interviewWizard.error') });
    }
  };

  const handleRedo = () => {
    setAnswers({});
    setState({ phase: 'questions' });
  };

  // ── Render ───────────────────────────────────────────────────────────────────

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h3 className="text-base font-semibold text-foreground">{t('interviewWizard.title')}</h3>
          <p className="mt-0.5 text-xs text-secondary-text">{t('interviewWizard.subtitle')}</p>
        </div>
        <Button
          variant="ghost"
          size="sm"
          data-testid="interview-skip"
          onClick={onSkip}
        >
          {t('interviewWizard.skip')}
        </Button>
      </div>

      {/* Loading */}
      {state.phase === 'loading' && <Loading />}

      {/* Error */}
      {state.phase === 'error' && (
        <div data-testid="interview-error">
          <InlineAlert variant="danger" message={state.message} />
        </div>
      )}

      {/* Questions */}
      {(state.phase === 'questions' || state.phase === 'error') && (
        <div className="space-y-6">
          {QUESTIONS.map((q, idx) => {
            return (
              <section key={q.key} aria-label={t(q.titleI18n as Parameters<typeof t>[0])}>
                <p
                  className={cn(
                    'mb-3 text-sm font-medium',
                    'text-foreground',
                  )}
                >
                  <span className="mr-1 text-xs text-muted-text">{idx + 1}.</span>
                  {t(q.titleI18n as Parameters<typeof t>[0])}
                </p>
                <div className="flex flex-wrap gap-2">
                  {q.options.map((opt) => {
                    const selected = answers[q.key] === opt.value;
                    return (
                      <button
                        key={opt.value}
                        type="button"
                        data-testid={`option-${q.key}-${opt.value}`}
                        aria-pressed={selected}
                        onClick={() => handleSelect(q.key, opt.value)}
                        className={cn(
                          'rounded-lg border px-3 py-1.5 text-sm transition-all',
                          'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-cyan/40',
                          selected
                            ? 'border-cyan/60 bg-cyan/10 text-foreground shadow-soft-card'
                            : 'border-border/60 bg-card/50 text-secondary-text hover:border-cyan/40 hover:bg-card',
                        )}
                      >
                        {t(opt.labelI18n as Parameters<typeof t>[0])}
                      </button>
                    );
                  })}
                </div>
              </section>
            );
          })}

          {/* Progress indicator */}
          <p className="text-xs text-muted-text">
            {t('interviewWizard.step', {
              current: Math.min(Object.keys(answers).length + 1, QUESTIONS.length),
              total: QUESTIONS.length,
            })}
            {state.phase === 'questions' && allAnswered && ' — ' + t('interviewWizard.loading')}
          </p>
        </div>
      )}

      {/* Result */}
      {state.phase === 'result' && (
        <div className="space-y-4">
          <h4 className="text-sm font-semibold text-foreground">{t('interviewWizard.resultTitle')}</h4>

          <div className="space-y-3">
            {state.recommended.map((skill) => (
              <div
                key={skill.id}
                className="rounded-xl border border-cyan/30 bg-cyan/5 p-4"
              >
                <p className="text-sm font-semibold text-foreground">{skill.name}</p>
                <p className="mt-1 text-xs text-secondary-text">{skill.description}</p>
              </div>
            ))}
          </div>

          {state.explanation && (
            <p className="text-xs text-secondary-text">{state.explanation}</p>
          )}

          {/* Actions */}
          <div className="flex gap-3">
            <Button
              variant="primary"
              size="sm"
              data-testid="interview-adopt"
              onClick={() => onComplete(state.recommended.map((s) => s.id))}
            >
              {t('interviewWizard.adopt')}
            </Button>
            <Button
              variant="ghost"
              size="sm"
              data-testid="interview-redo"
              onClick={handleRedo}
            >
              {t('interviewWizard.redo')}
            </Button>
            <Button
              variant="ghost"
              size="sm"
              data-testid="interview-skip-result"
              onClick={onSkip}
            >
              {t('interviewWizard.skip')}
            </Button>
          </div>
        </div>
      )}
    </div>
  );
};
