import { EmptyState, PageHeader } from '../components/ui';
import type { IconName } from '../components/icons';
import { pick, useUILang } from '../lib/i18n';

export default function PlaceholderPage({
  icon,
  title,
  description,
  step,
}: {
  icon: IconName;
  title: string;
  description: string;
  step: number;
}) {
  const ui = useUILang();
  return (
    <div>
      <PageHeader title={title} description={description} />
      <EmptyState
        icon={icon}
        title={pick(ui, 'Page en construction', 'Page under construction')}
        description={pick(ui, `Chantier admin — étape ${step}. Cette page arrive au prochain commit.`, `Admin work in progress — step ${step}. This page lands with the next commit.`)}
      />
    </div>
  );
}
