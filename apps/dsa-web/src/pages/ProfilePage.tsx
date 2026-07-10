import type React from 'react';
import { useEffect, useState } from 'react';
import { agentApi } from '../api/agent';
import { useUiLanguage } from '../contexts/UiLanguageContext';
import { AppPage, Button, InlineAlert, Loading, PageHeader, SectionCard } from '../components/common';
import { InterviewWizard } from '../components/profile/InterviewWizard';
import { StrategyCenter } from '../components/profile/StrategyCenter';
import { cn } from '../utils/cn';

const MAX_SELECTED_SKILLS = 5;

type EntranceTab = 'interview' | 'manual';

export const ProfilePage: React.FC = () => {
  const { t } = useUiLanguage();
  const [activeTab, setActiveTab] = useState<EntranceTab>('interview');
  const [selectedSkillIds, setSelectedSkillIds] = useState<string[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [loadFailed, setLoadFailed] = useState(false);
  const [isSaving, setIsSaving] = useState(false);
  const [saveFailed, setSaveFailed] = useState(false);
  const [saveSucceeded, setSaveSucceeded] = useState(false);

  useEffect(() => {
    let cancelled = false;

    agentApi
      .getProfile()
      .then((profile) => {
        if (!cancelled) {
          setSelectedSkillIds(profile.skillIds);
          setIsLoading(false);
        }
      })
      .catch(() => {
        if (!cancelled) {
          setLoadFailed(true);
          setIsLoading(false);
        }
      });

    return () => {
      cancelled = true;
    };
  }, []);

  const saveProfile = async (skillIds: string[], source: EntranceTab) => {
    setIsSaving(true);
    setSaveFailed(false);
    setSaveSucceeded(false);
    try {
      const result = await agentApi.putProfile({ skillIds, source });
      setSelectedSkillIds(result.skillIds);
      setSaveSucceeded(true);
    } catch {
      setSaveFailed(true);
    } finally {
      setIsSaving(false);
    }
  };

  const handleInterviewComplete = (skillIds: string[]) => {
    setSelectedSkillIds(skillIds);
    void saveProfile(skillIds, 'interview');
  };

  const handleInterviewSkip = () => {
    setActiveTab('manual');
  };

  const handleManualSave = () => {
    void saveProfile(selectedSkillIds, 'manual');
  };

  const tabs: { key: EntranceTab; label: string }[] = [
    { key: 'interview', label: t('profilePage.tab.interview') },
    { key: 'manual', label: t('profilePage.tab.manual') },
  ];

  return (
    <AppPage>
      <PageHeader title={t('profilePage.title')} description={t('profilePage.description')} />

      <div className="mt-5 flex gap-2" role="tablist" aria-label={t('profilePage.title')}>
        {tabs.map((tab) => (
          <button
            key={tab.key}
            type="button"
            role="tab"
            aria-selected={activeTab === tab.key}
            onClick={() => setActiveTab(tab.key)}
            className={cn(
              'rounded-xl border px-4 py-2 text-sm font-medium transition-all',
              activeTab === tab.key
                ? 'border-cyan/60 bg-cyan/10 text-foreground shadow-soft-card'
                : 'border-border/60 bg-card/50 text-secondary-text hover:border-cyan/40 hover:bg-card',
            )}
          >
            {tab.label}
          </button>
        ))}
      </div>

      <div className="mt-5 space-y-4">
        {isLoading ? (
          <Loading />
        ) : loadFailed ? (
          <InlineAlert variant="danger" message={t('profilePage.loadError')} />
        ) : (
          <SectionCard title={tabs.find((tab) => tab.key === activeTab)?.label ?? ''}>
            {activeTab === 'interview' ? (
              <InterviewWizard
                onComplete={handleInterviewComplete}
                onSkip={handleInterviewSkip}
                isSaving={isSaving}
              />
            ) : (
              <div className="space-y-4">
                <StrategyCenter
                  selected={selectedSkillIds}
                  onChange={setSelectedSkillIds}
                  maxSelected={MAX_SELECTED_SKILLS}
                />
                {selectedSkillIds.length === 0 ? (
                  <p className="text-xs text-secondary-text">{t('profilePage.manualEmptyHint')}</p>
                ) : null}
                <div className="flex justify-end">
                  <Button
                    variant="primary"
                    onClick={handleManualSave}
                    disabled={selectedSkillIds.length === 0 || isSaving}
                    isLoading={isSaving}
                    loadingText={t('profilePage.saving')}
                  >
                    {t('profilePage.save')}
                  </Button>
                </div>
              </div>
            )}
            {saveFailed ? (
              <div className="mt-4">
                <InlineAlert variant="danger" message={t('profilePage.saveError')} />
              </div>
            ) : null}
            {saveSucceeded ? (
              <div className="mt-4">
                <InlineAlert variant="success" message={t('profilePage.saveSuccess')} />
              </div>
            ) : null}
          </SectionCard>
        )}
      </div>
    </AppPage>
  );
};

export default ProfilePage;
