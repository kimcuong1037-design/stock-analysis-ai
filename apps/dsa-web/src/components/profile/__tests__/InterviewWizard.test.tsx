import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { InterviewWizard } from '../InterviewWizard';

vi.mock('../../../api/agent', () => ({
  agentApi: {
    submitInterview: vi.fn(() =>
      Promise.resolve({
        recommended: [
          { id: 'hot_theme', name: '热门主题', description: '题材策略' },
          { id: 'event_driven', name: '事件驱动', description: '事件策略' },
        ],
        explanation: '适合你',
      }),
    ),
  },
}));

// Helper: answer all 4 questions by clicking the first option in each
async function answerAllQuestions() {
  // Q1: 持仓周期 — first option label is ultra_short
  fireEvent.click(screen.getByTestId('option-horizon-ultra_short'));
  // Q2: 风险偏好 — first option label is conservative
  fireEvent.click(screen.getByTestId('option-risk-conservative'));
  // Q3: 交易风格 — first option is trend
  fireEvent.click(screen.getByTestId('option-style-trend'));
  // Q4: 盯盘投入 — first option is high
  fireEvent.click(screen.getByTestId('option-watch-high'));
}

describe('InterviewWizard', () => {
  beforeEach(async () => {
    const { agentApi } = await import('../../../api/agent');
    vi.mocked(agentApi.submitInterview).mockClear();
    vi.mocked(agentApi.submitInterview).mockResolvedValue({
      recommended: [
        { id: 'hot_theme', name: '热门主题', description: '题材策略' },
        { id: 'event_driven', name: '事件驱动', description: '事件策略' },
      ],
      explanation: '适合你',
    });
  });

  it('shows recommendation after answering all 4 questions', async () => {
    const onComplete = vi.fn();
    render(<InterviewWizard onComplete={onComplete} onSkip={() => {}} />);

    await answerAllQuestions();

    expect(await screen.findByText('热门主题')).toBeInTheDocument();
    expect(await screen.findByText('适合你')).toBeInTheDocument();
  });

  it('calls submitInterview with correct answer keys after answering all questions', async () => {
    const { agentApi } = await import('../../../api/agent');
    render(<InterviewWizard onComplete={() => {}} onSkip={() => {}} />);

    await answerAllQuestions();

    await waitFor(() => {
      expect(agentApi.submitInterview).toHaveBeenCalledWith({
        horizon: 'ultra_short',
        risk: 'conservative',
        style: 'trend',
        watch: 'high',
      });
      expect(agentApi.submitInterview).toHaveBeenCalledTimes(1);
    });
  });

  it('calls onComplete with all recommended ids when adopt button is clicked', async () => {
    const onComplete = vi.fn();
    render(<InterviewWizard onComplete={onComplete} onSkip={() => {}} />);

    await answerAllQuestions();

    const adoptBtn = await screen.findByTestId('interview-adopt');
    fireEvent.click(adoptBtn);
    expect(onComplete).toHaveBeenCalledWith(['hot_theme', 'event_driven']);
  });

  it('selects all recommended cards by default and toggles one off on click', async () => {
    const onComplete = vi.fn();
    render(<InterviewWizard onComplete={onComplete} onSkip={() => {}} />);

    await answerAllQuestions();

    const card = await screen.findByTestId('recommend-card-event_driven');
    expect(card).toHaveAttribute('aria-checked', 'true');

    fireEvent.click(card);
    expect(card).toHaveAttribute('aria-checked', 'false');

    fireEvent.click(screen.getByTestId('interview-adopt'));
    expect(onComplete).toHaveBeenCalledWith(['hot_theme']);
  });

  it('disables adopt when every recommended card is deselected', async () => {
    render(<InterviewWizard onComplete={() => {}} onSkip={() => {}} />);

    await answerAllQuestions();

    fireEvent.click(await screen.findByTestId('recommend-card-hot_theme'));
    fireEvent.click(screen.getByTestId('recommend-card-event_driven'));

    expect(screen.getByTestId('interview-adopt')).toBeDisabled();
  });

  it('disables adopt and shows busy state while saving', async () => {
    render(<InterviewWizard onComplete={() => {}} onSkip={() => {}} isSaving />);

    await answerAllQuestions();

    const adoptBtn = await screen.findByTestId('interview-adopt');
    expect(adoptBtn).toBeDisabled();
    expect(adoptBtn).toHaveAttribute('aria-busy', 'true');
  });

  it('calls onSkip when skip button is clicked', async () => {
    const onSkip = vi.fn();
    render(<InterviewWizard onComplete={() => {}} onSkip={onSkip} />);

    const skipBtn = screen.getByTestId('interview-skip');
    fireEvent.click(skipBtn);
    expect(onSkip).toHaveBeenCalled();
  });

  it('resets to question 1 when redo button is clicked after results', async () => {
    render(<InterviewWizard onComplete={() => {}} onSkip={() => {}} />);

    await answerAllQuestions();
    await screen.findByTestId('interview-adopt');

    const redoBtn = screen.getByTestId('interview-redo');
    fireEvent.click(redoBtn);

    // Should be back to first question
    expect(screen.getByTestId('option-horizon-ultra_short')).toBeInTheDocument();
  });

  it('shows error state when submitInterview rejects', async () => {
    const { agentApi } = await import('../../../api/agent');
    vi.mocked(agentApi.submitInterview).mockRejectedValueOnce(new Error('network error'));

    render(<InterviewWizard onComplete={() => {}} onSkip={() => {}} />);

    await answerAllQuestions();

    await waitFor(() => {
      expect(screen.getByTestId('interview-error')).toBeInTheDocument();
    });
  });

  it('calls onSkip from result-phase skip button (interview-skip-result)', async () => {
    const onSkip = vi.fn();
    render(<InterviewWizard onComplete={() => {}} onSkip={onSkip} />);

    await answerAllQuestions();

    // Wait for result phase
    await screen.findByTestId('interview-adopt');

    const resultSkipBtn = screen.getByTestId('interview-skip-result');
    fireEvent.click(resultSkipBtn);
    expect(onSkip).toHaveBeenCalled();
  });
});
