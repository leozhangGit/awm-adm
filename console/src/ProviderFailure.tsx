import { JsonDetail, Notice } from "./components.tsx";
import { providerFailureText } from "./feedback.ts";
import type { ProviderFailureView } from "./feedback.ts";

export function ProviderFailure({
  failure,
}: {
  failure?: ProviderFailureView | null;
}) {
  if (!failure) return null;
  return (
    <div className="provider-failure">
      <Notice error>
        {providerFailureText(failure).map((line) => (
          <p key={line}>{line}</p>
        ))}
      </Notice>
      <JsonDetail label="Provider failure details and usage" value={failure} />
    </div>
  );
}
