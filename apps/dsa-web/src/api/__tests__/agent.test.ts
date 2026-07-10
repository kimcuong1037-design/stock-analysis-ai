import { beforeEach, describe, expect, it, vi } from 'vitest';
import { agentApi } from '../agent';

const { get, put, post } = vi.hoisted(() => ({ get: vi.fn(), put: vi.fn(), post: vi.fn() }));
vi.mock('../index', () => ({ default: { get, put, post } }));

describe('agentApi profile', () => {
  beforeEach(() => {
    get.mockReset();
    put.mockReset();
    post.mockReset();
  });

  it('getProfile maps snake_case to camelCase', async () => {
    get.mockResolvedValueOnce({
      data: { skill_ids: ['bull_trend'], source: 'manual', updated_at: null },
    });
    const p = await agentApi.getProfile();
    expect(p.skillIds).toEqual(['bull_trend']);
    expect(p.source).toBe('manual');
    expect(p.updatedAt).toBeNull();
    expect(get).toHaveBeenCalledWith('/api/v1/agent/profile');
  });

  it('putProfile sends snake_case body and returns camelCase', async () => {
    put.mockResolvedValueOnce({
      data: { skill_ids: ['bull_trend'], source: 'manual', updated_at: '2026-01-01T00:00:00Z' },
    });
    const result = await agentApi.putProfile({
      skillIds: ['bull_trend'],
      source: 'manual',
      interviewAnswers: { horizon: 'long' },
    });
    expect(put).toHaveBeenCalledWith('/api/v1/agent/profile', {
      skill_ids: ['bull_trend'],
      source: 'manual',
      interview_answers: { horizon: 'long' },
    });
    expect(result.skillIds).toEqual(['bull_trend']);
    expect(result.updatedAt).toBe('2026-01-01T00:00:00Z');
  });

  it('putProfile defaults source to "manual" when omitted', async () => {
    put.mockResolvedValueOnce({
      data: { skill_ids: ['bull_trend'], source: 'manual', updated_at: null },
    });
    await agentApi.putProfile({ skillIds: ['bull_trend'] });
    expect(put).toHaveBeenCalledWith('/api/v1/agent/profile', {
      skill_ids: ['bull_trend'],
      source: 'manual',
      interview_answers: undefined,
    });
  });

  it('submitInterview posts answers and returns recommended + explanation', async () => {
    const recommended = [
      { id: 'bull_trend', name: 'Bull Trend', description: 'Trend following', category: 'trend', profileTags: { horizon: ['long'] } },
    ];
    post.mockResolvedValueOnce({
      data: { recommended, explanation: 'Based on your answers...' },
    });
    const result = await agentApi.submitInterview({ horizon: 'long', risk: 'medium', style: 'growth', watch: 'daily' });
    expect(post).toHaveBeenCalledWith('/api/v1/agent/profile/interview', {
      answers: { horizon: 'long', risk: 'medium', style: 'growth', watch: 'daily' },
    });
    expect(result.recommended).toHaveLength(1);
    expect(result.recommended[0].id).toBe('bull_trend');
    expect(result.explanation).toBe('Based on your answers...');
  });

  it('submitInterview remaps snake_case profile_tags to camelCase profileTags', async () => {
    post.mockResolvedValueOnce({
      data: {
        recommended: [
          { id: 'hot_theme', name: '热门主题', description: 'd', category: 'theme', profile_tags: { style: ['theme'] } },
        ],
        explanation: 'x',
      },
    });
    const result = await agentApi.submitInterview({ horizon: 'short' });
    expect(result.recommended[0].profileTags).toEqual({ style: ['theme'] });
    expect(result.explanation).toBe('x');
  });

  it('getSkills maps profile_tags to profileTags, keeps category, sets isDefault from default_skill_id', async () => {
    get.mockResolvedValueOnce({
      data: {
        skills: [
          {
            id: 'bull_trend',
            name: 'Bull Trend',
            description: 'Trend following',
            category: 'trend',
            profile_tags: { horizon: ['long', 'medium'], risk: ['high'] },
          },
          {
            id: 'value_pick',
            name: 'Value Pick',
            description: 'Value investing',
            category: 'value',
            profile_tags: { style: ['value'] },
          },
        ],
        default_skill_id: 'bull_trend',
      },
    });
    const result = await agentApi.getSkills();
    // existing consumers: id/name/description must still work
    expect(result.skills[0].id).toBe('bull_trend');
    expect(result.skills[0].name).toBe('Bull Trend');
    expect(result.skills[0].description).toBe('Trend following');
    // new fields
    expect(result.skills[0].category).toBe('trend');
    expect(result.skills[0].profileTags).toEqual({ horizon: ['long', 'medium'], risk: ['high'] });
    expect(result.skills[0].isDefault).toBe(true);
    expect(result.skills[1].isDefault).toBe(false);
    expect(result.default_skill_id).toBe('bull_trend');
  });
});
