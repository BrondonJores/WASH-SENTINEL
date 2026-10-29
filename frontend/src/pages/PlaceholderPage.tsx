import { EmptyState, PageHeader } from '../components/ui';
import type { IconName } from '../components/icons';

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
  return (
    <div>
      <PageHeader title={title} description={description} />
      <EmptyState
        icon={icon}
        title="Page en construction"
        description={`Chantier admin — étape ${step}. Cette page arrive au prochain commit.`}
      />
    </div>
  );
}
