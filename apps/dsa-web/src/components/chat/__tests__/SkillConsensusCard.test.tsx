import { render, screen } from '@testing-library/react';
import { it, expect } from 'vitest';
import { SkillConsensusCard } from '../SkillConsensusCard';

const consensus = {
  signal: 'hold',
  confidence: 0.72,
  score_adjustment: 4,
  reasoning: '综合共识依据',
  skill_count: 2,
};

it('renders signal, confidence, score adjustment and reasoning', () => {
  render(<SkillConsensusCard consensus={consensus} />);
  expect(screen.getByText('共识结论')).toBeInTheDocument();
  expect(screen.getByText('持有')).toBeInTheDocument();
  expect(screen.getByText(/72%/)).toBeInTheDocument();
  expect(screen.getByText(/\+4/)).toBeInTheDocument();
  expect(screen.getByText('综合共识依据')).toBeInTheDocument();
});

it('renders nothing when consensus is absent', () => {
  const { container: withUndefined } = render(<SkillConsensusCard />);
  expect(withUndefined).toBeEmptyDOMElement();

  const { container: withNull } = render(<SkillConsensusCard consensus={null} />);
  expect(withNull).toBeEmptyDOMElement();
});
