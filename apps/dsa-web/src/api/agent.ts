import apiClient from './index';
import { API_BASE_URL } from '../utils/constants';
import { createApiError, isApiRequestError, parseApiError } from './error';

export interface ChatStreamOptions {
  signal?: AbortSignal;
}

export interface ChatRequest {
  message: string;
  skills?: string[];
}

export interface ChatStreamRequest extends ChatRequest {
  session_id?: string;
  context?: unknown;
}

export interface SkillBreakdownItem {
  skill_id: string;
  display_name: string;
  signal: string;
  confidence: number;
  score_adjustment: number;
  reasoning: string;
  key_levels: Record<string, unknown>;
}

export interface ChatResponse {
  success: boolean;
  content: string;
  session_id: string;
  error?: string;
  skill_breakdown?: SkillBreakdownItem[];
}

export interface SkillInfo {
  id: string;
  name: string;
  description: string;
  category?: string;
  profileTags?: Record<string, string[]>;
  isDefault?: boolean;
}

export interface SkillsResponse {
  skills: SkillInfo[];
  default_skill_id: string;
}

export interface InvestorProfile {
  skillIds: string[];
  source: string | null;
  updatedAt: string | null;
}

export interface ChatSessionItem {
  session_id: string;
  title: string;
  message_count: number;
  created_at: string | null;
  last_active: string | null;
}

export interface ChatSessionMessage {
  id: string;
  role: 'user' | 'assistant';
  content: string;
  created_at: string | null;
}

type RawSkillInfo = {
  id: string;
  name: string;
  description: string;
  category?: string;
  profile_tags?: Record<string, string[]>;
  profileTags?: Record<string, string[]>;
};

function mapSkillInfo(raw: RawSkillInfo): Omit<SkillInfo, 'isDefault'> {
  return {
    id: raw.id,
    name: raw.name,
    description: raw.description,
    category: raw.category,
    profileTags: raw.profile_tags ?? raw.profileTags,
  };
}

export const agentApi = {
  async chat(payload: ChatRequest): Promise<ChatResponse> {
    const response = await apiClient.post<ChatResponse>('/api/v1/agent/chat', payload, {
      timeout: 120000,
    });
    return response.data;
  },
  async getSkills(): Promise<SkillsResponse> {
    const response = await apiClient.get<{
      skills: RawSkillInfo[];
      default_skill_id: string;
    }>('/api/v1/agent/skills');
    const data = response.data;
    return {
      default_skill_id: data.default_skill_id,
      skills: data.skills.map((s) => ({
        ...mapSkillInfo(s),
        isDefault: s.id === data.default_skill_id,
      })),
    };
  },
  async getProfile(): Promise<InvestorProfile> {
    const response = await apiClient.get<{ skill_ids: string[]; source: string | null; updated_at: string | null }>(
      '/api/v1/agent/profile',
    );
    const data = response.data;
    return { skillIds: data.skill_ids ?? [], source: data.source ?? null, updatedAt: data.updated_at ?? null };
  },
  async putProfile(p: {
    skillIds: string[];
    source?: string;
    interviewAnswers?: Record<string, unknown>;
  }): Promise<InvestorProfile> {
    const response = await apiClient.put<{ skill_ids: string[]; source: string | null; updated_at: string | null }>(
      '/api/v1/agent/profile',
      { skill_ids: p.skillIds, source: p.source ?? 'manual', interview_answers: p.interviewAnswers },
    );
    const data = response.data;
    return { skillIds: data.skill_ids ?? [], source: data.source ?? null, updatedAt: data.updated_at ?? null };
  },
  async submitInterview(answers: Record<string, string>): Promise<{ recommended: SkillInfo[]; explanation: string }> {
    const response = await apiClient.post<{ recommended: RawSkillInfo[]; explanation: string }>(
      '/api/v1/agent/profile/interview',
      { answers },
    );
    const data = response.data;
    return { recommended: (data.recommended ?? []).map(mapSkillInfo), explanation: data.explanation ?? '' };
  },
  async getChatSessions(limit = 50): Promise<ChatSessionItem[]> {
    const response = await apiClient.get<{ sessions: ChatSessionItem[] }>('/api/v1/agent/chat/sessions', { params: { limit } });
    return response.data.sessions;
  },
  async getChatSessionMessages(sessionId: string): Promise<ChatSessionMessage[]> {
    const response = await apiClient.get<{ messages: ChatSessionMessage[] }>(`/api/v1/agent/chat/sessions/${sessionId}`);
    return response.data.messages;
  },
  async deleteChatSession(sessionId: string): Promise<void> {
    await apiClient.delete(`/api/v1/agent/chat/sessions/${sessionId}`);
  },
  async sendChat(content: string): Promise<{ success: boolean }> {
    const response = await apiClient.post<{
      success: boolean;
      error?: string;
      message?: string;
    }>('/api/v1/agent/chat/send', { content });
    const data = response.data;
    if (data.success === false) {
      throw new Error(data.message || '发送失败');
    }
    return { success: true };
  },
  async chatStream(
    payload: ChatStreamRequest,
    options?: ChatStreamOptions,
  ): Promise<Response> {
    const base = API_BASE_URL || '';
    const url = `${base}/api/v1/agent/chat/stream`;
    try {
      const response = await fetch(url, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
        credentials: 'include',
        signal: options?.signal,
      });

      if (response.ok) {
        return response;
      }

      const contentType = response.headers.get('content-type') || '';
      let responseData: unknown = null;
      if (contentType.includes('application/json')) {
        responseData = await response.json().catch(() => null);
      } else {
        responseData = await response.text().catch(() => null);
      }

      const parsed = parseApiError({
        response: {
          status: response.status,
          statusText: response.statusText,
          data: responseData,
        },
      });
      throw createApiError(parsed, {
        response: {
          status: response.status,
          statusText: response.statusText,
          data: responseData,
        },
      });
    } catch (error: unknown) {
      if (isApiRequestError(error)) {
        throw error;
      }
      if (error instanceof Error && error.name === 'AbortError') {
        throw error;
      }

      const parsed = parseApiError(error);
      throw createApiError(parsed, { cause: error });
    }
  },
};
