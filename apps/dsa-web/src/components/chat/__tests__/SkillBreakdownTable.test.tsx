import { render, screen, fireEvent } from '@testing-library/react';
import { it, expect } from 'vitest';
import { SkillBreakdownTable } from '../SkillBreakdownTable';

const items = [
  { skill_id: 'bull_trend', display_name: '牛市趋势', signal: 'buy', confidence: 0.8, score_adjustment: 12, reasoning: '多头排列', key_levels: {} },
  { skill_id: 'box_oscillation', display_name: '箱体震荡', signal: 'sell', confidence: 0.6, score_adjustment: -8, reasoning: '触顶', key_levels: {} },
];

it('renders one row per skill and expands detail', () => {
  render(<SkillBreakdownTable items={items} />);
  expect(screen.getByText('牛市趋势')).toBeInTheDocument();
  expect(screen.getByText('箱体震荡')).toBeInTheDocument();
  fireEvent.click(screen.getByText('牛市趋势'));
  expect(screen.getByText('多头排列')).toBeInTheDocument();
});

it('renders nothing when empty', () => {
  const { container } = render(<SkillBreakdownTable items={[]} />);
  expect(container).toBeEmptyDOMElement();
});
