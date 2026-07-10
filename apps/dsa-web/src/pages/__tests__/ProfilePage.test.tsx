import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, expect, it, vi } from 'vitest';
import { ProfilePage } from '../ProfilePage';

const { getProfile, getSkills, putProfile, submitInterview } = vi.hoisted(() => ({
  getProfile: vi.fn(),
  getSkills: vi.fn(),
  putProfile: vi.fn(),
  submitInterview: vi.fn(),
}));

vi.mock('../../api/agent', () => ({
  agentApi: {
    getProfile: (...args: unknown[]) => getProfile(...args),
    getSkills: (...args: unknown[]) => getSkills(...args),
    putProfile: (...args: unknown[]) => putProfile(...args),
    submitInterview: (...args: unknown[]) => submitInterview(...args),
  },
}));

beforeEach(() => {
  vi.clearAllMocks();
  getProfile.mockResolvedValue({ skillIds: ['bull_trend'], source: 'manual', updatedAt: null });
  getSkills.mockResolvedValue({
    skills: [
      { id: 'bull_trend', name: '牛市趋势', description: 'd', category: 'trend' },
      { id: 'chan_theory', name: '缠论', description: '缠论框架', category: 'framework' },
    ],
    default_skill_id: 'bull_trend',
  });
  putProfile.mockResolvedValue({ skillIds: ['bull_trend'], source: 'manual', updatedAt: null });
  submitInterview.mockResolvedValue({
    recommended: [{ id: 'chan_theory', name: '缠论', description: '缠论框架' }],
    explanation: '适合你',
  });
});

it('renders profile page heading', async () => {
  render(<ProfilePage />);
  expect(await screen.findByRole('heading', { name: '投资画像' })).toBeInTheDocument();
});

it('backfills the saved profile selection into strategy center on the manual tab', async () => {
  render(<ProfilePage />);

  fireEvent.click(await screen.findByRole('tab', { name: '直接选策略' }));

  const preSelected = await screen.findByTestId('skill-card-bull_trend');
  expect(preSelected).toHaveAttribute('aria-checked', 'true');
});

it('saves the manual selection with source manual when the save button is clicked', async () => {
  render(<ProfilePage />);

  fireEvent.click(await screen.findByRole('tab', { name: '直接选策略' }));
  await screen.findByTestId('skill-card-bull_trend');

  fireEvent.click(screen.getByRole('button', { name: '保存画像' }));

  await waitFor(() => {
    expect(putProfile).toHaveBeenCalledWith({ skillIds: ['bull_trend'], source: 'manual' });
  });
});

it('saves the interview recommendation with source interview after adopting', async () => {
  render(<ProfilePage />);

  fireEvent.click(await screen.findByTestId('option-horizon-ultra_short'));
  fireEvent.click(screen.getByTestId('option-risk-conservative'));
  fireEvent.click(screen.getByTestId('option-style-trend'));
  fireEvent.click(screen.getByTestId('option-watch-high'));

  const adoptBtn = await screen.findByTestId('interview-adopt');
  fireEvent.click(adoptBtn);

  await waitFor(() => {
    expect(putProfile).toHaveBeenCalledWith({ skillIds: ['chan_theory'], source: 'interview' });
  });
});

it('shows save feedback after adopting the interview recommendation', async () => {
  render(<ProfilePage />);

  fireEvent.click(await screen.findByTestId('option-horizon-ultra_short'));
  fireEvent.click(screen.getByTestId('option-risk-conservative'));
  fireEvent.click(screen.getByTestId('option-style-trend'));
  fireEvent.click(screen.getByTestId('option-watch-high'));

  fireEvent.click(await screen.findByTestId('interview-adopt'));

  expect(await screen.findByText('画像已保存')).toBeInTheDocument();
});

it('switches to the manual tab when the interview is skipped', async () => {
  render(<ProfilePage />);

  fireEvent.click(await screen.findByTestId('interview-skip'));

  expect(await screen.findByTestId('skill-card-bull_trend')).toBeInTheDocument();
});
