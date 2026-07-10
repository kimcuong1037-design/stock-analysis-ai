import { render, screen, fireEvent } from '@testing-library/react';
import { describe, it, expect, vi } from 'vitest';
import { StrategyCenter } from '../StrategyCenter';

vi.mock('../../../api/agent', () => ({
  agentApi: {
    getSkills: () =>
      Promise.resolve({
        skills: [
          { id: 'bull_trend', name: '牛市趋势', description: '多头趋势策略', category: 'trend' },
          { id: 'chan_theory', name: '缠论', description: '缠论框架分析', category: 'framework' },
          { id: 'head_shoulders', name: '头肩顶', description: '头肩形态识别', category: 'pattern' },
        ],
        default_skill_id: 'bull_trend',
      }),
  },
}));

describe('StrategyCenter', () => {
  it('renders strategy cards grouped by category', async () => {
    render(<StrategyCenter selected={[]} onChange={() => {}} maxSelected={3} />);
    expect(await screen.findByText('牛市趋势')).toBeInTheDocument();
    expect(await screen.findByText('缠论')).toBeInTheDocument();
    expect(await screen.findByText('头肩顶')).toBeInTheDocument();
  });

  it('renders category group headings for each present category', async () => {
    render(<StrategyCenter selected={[]} onChange={() => {}} maxSelected={3} />);
    // The mock data has: bull_trend (trend), head_shoulders (pattern), chan_theory (framework)
    // Headings are rendered via i18n zh fallback: 趋势, 形态, 框架
    expect(await screen.findByText('趋势')).toBeInTheDocument();
    expect(await screen.findByText('形态')).toBeInTheDocument();
    expect(await screen.findByText('框架')).toBeInTheDocument();
  });

  it('shows skill descriptions', async () => {
    render(<StrategyCenter selected={[]} onChange={() => {}} maxSelected={3} />);
    expect(await screen.findByText('多头趋势策略')).toBeInTheDocument();
    expect(await screen.findByText('缠论框架分析')).toBeInTheDocument();
  });

  it('calls onChange with added id when selecting an unselected card', async () => {
    const onChange = vi.fn();
    render(<StrategyCenter selected={[]} onChange={onChange} maxSelected={3} />);
    // wait for skills to load
    const card = await screen.findByText('牛市趋势');
    fireEvent.click(card.closest('[data-skill-id]') ?? card);
    expect(onChange).toHaveBeenCalledWith(['bull_trend']);
  });

  it('calls onChange with removed id when deselecting a selected card', async () => {
    const onChange = vi.fn();
    render(<StrategyCenter selected={['bull_trend']} onChange={onChange} maxSelected={3} />);
    const card = await screen.findByText('牛市趋势');
    fireEvent.click(card.closest('[data-skill-id]') ?? card);
    expect(onChange).toHaveBeenCalledWith([]);
  });

  it('disables unselected cards at maxSelected', async () => {
    const onChange = vi.fn();
    // 'bull_trend' and 'chan_theory' are selected, maxSelected=2
    render(
      <StrategyCenter
        selected={['bull_trend', 'chan_theory']}
        onChange={onChange}
        maxSelected={2}
      />,
    );
    // 'head_shoulders' is unselected and should be disabled
    const disabledCard = await screen.findByTestId('skill-card-head_shoulders');
    expect(disabledCard).toHaveAttribute('aria-disabled', 'true');

    // clicking disabled unselected card must NOT call onChange
    fireEvent.click(disabledCard);
    expect(onChange).not.toHaveBeenCalled();
  });

  it('still allows deselecting an already-selected card at maxSelected', async () => {
    const onChange = vi.fn();
    render(
      <StrategyCenter
        selected={['bull_trend', 'chan_theory']}
        onChange={onChange}
        maxSelected={2}
      />,
    );
    const selectedCard = await screen.findByTestId('skill-card-bull_trend');
    fireEvent.click(selectedCard);
    expect(onChange).toHaveBeenCalledWith(['chan_theory']);
  });
});
