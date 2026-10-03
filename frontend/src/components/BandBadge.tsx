/**
 * Emission band shown as colour + icon + word, so the meaning never relies
 * on colour alone (WCAG 1.4.1). Shared by the carbon card, hotel cards and
 * transport routes.
 */
import { BAND_META } from "@/lib/bands";
import { isBand } from "@/lib/payloads";

export function BandBadge({ band, short = false }: { band: unknown; short?: boolean }) {
  if (!isBand(band)) return null;
  const { label, text, surface, Icon } = BAND_META[band];
  return (
    <span
      className={`inline-flex shrink-0 items-center gap-1 rounded-full border px-2 py-0.5 text-xs font-medium ${surface} ${text}`}
    >
      <Icon className="size-3" aria-hidden="true" />
      {short ? (
        <>
          {label.split(" ")[0]}
          <span className="sr-only"> emissions</span>
        </>
      ) : (
        label
      )}
    </span>
  );
}
